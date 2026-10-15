"""
Priority order for the local-model slot (2026-10-14).

interactive -> rfq -> extraction -> bulk, with aging so bulk work is delayed
but never starved. Priority decides WHO gets the next slot; capacity
(LOCAL_LLM_MAX_CONCURRENCY) stays 1 -- these tests pin both.
"""
import threading
import time

import fakeredis
import pytest


@pytest.fixture
def gate(monkeypatch):
    from leads import local_llm_gate
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(local_llm_gate, "_client", fake)
    monkeypatch.setattr(local_llm_gate, "_get_client", lambda: fake)
    monkeypatch.delenv("LOCAL_LLM_MAX_CONCURRENCY", raising=False)
    monkeypatch.setattr(local_llm_gate, "_POLL_SECONDS", 0.02)
    yield local_llm_gate
    fake.flushall()


def _waiter(gate, prio, order, started, timeout=5.0):
    def run():
        started.set()
        with gate.acquire_local_llm_slot(timeout=timeout, priority=prio):
            order.append(prio)
            time.sleep(0.05)
    t = threading.Thread(target=run)
    t.start()
    return t


def _queue_len(gate):
    return gate._get_client().zcard(gate._WAITERS_KEY)


def _until_queued(gate, n, timeout=5.0):
    """Wait until n waiters are in line -- not a fixed sleep, which is flaky under load."""
    end = time.monotonic() + timeout
    while _queue_len(gate) < n and time.monotonic() < end:
        time.sleep(0.01)
    assert _queue_len(gate) >= n


def test_rfq_goes_before_bulk_that_arrived_first(gate):
    order = []
    with gate.acquire_local_llm_slot(timeout=1, priority="interactive"):
        s1, s2 = threading.Event(), threading.Event()
        bulk = _waiter(gate, "bulk", order, s1)
        _until_queued(gate, 1)
        rfq = _waiter(gate, "rfq", order, s2)
        _until_queued(gate, 2)
    bulk.join(5); rfq.join(5)
    assert order == ["rfq", "bulk"]


def test_full_priority_order(gate):
    order = []
    with gate.acquire_local_llm_slot(timeout=1, priority="interactive"):
        threads = []
        for i, prio in enumerate(("bulk", "extraction", "rfq", "interactive")):
            threads.append(_waiter(gate, prio, order, threading.Event()))
            _until_queued(gate, i + 1)
    for t in threads:
        t.join(5)
    assert order == ["interactive", "rfq", "extraction", "bulk"]


def test_aging_lets_a_long_waiting_bulk_job_ahead(gate, monkeypatch):
    """Fairness: bulk that has waited longer than the aging gap beats newer work."""
    monkeypatch.setenv("LOCAL_LLM_PRIORITY_AGING_SECONDS", "0.1")
    order = []
    with gate.acquire_local_llm_slot(timeout=1, priority="interactive"):
        s1, s2 = threading.Event(), threading.Event()
        bulk = _waiter(gate, "bulk", order, s1)
        _until_queued(gate, 1)
        time.sleep(0.6)                     # bulk head start 0.3s (3 x 0.1) -- long since passed
        rfq = _waiter(gate, "rfq", order, s2)
        _until_queued(gate, 2)
    bulk.join(5); rfq.join(5)
    assert order == ["bulk", "rfq"]


def test_capacity_stays_one_with_priorities(gate):
    inside, peak = [0], [0]
    lock = threading.Lock()

    def run(prio):
        with gate.acquire_local_llm_slot(timeout=5, priority=prio):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            time.sleep(0.05)
            with lock:
                inside[0] -= 1

    ts = [threading.Thread(target=run, args=(p,)) for p in ("bulk", "rfq", "extraction", "interactive", "rfq")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert peak[0] == 1


def test_timeout_raises_and_leaves_no_waiter_behind(gate):
    with gate.acquire_local_llm_slot(timeout=1, priority="interactive"):
        with pytest.raises(gate.LocalLLMQueueTimeout) as e:
            with gate.acquire_local_llm_slot(timeout=0.2, priority="extraction"):
                pass
        assert "priority=extraction" in str(e.value)
        assert _queue_len(gate) == 0


def test_a_crashed_waiter_cannot_hold_the_front_of_the_line(gate):
    client = gate._get_client()
    # A waiter that died: in the line with the best possible place, no heartbeat.
    client.zadd(gate._WAITERS_KEY, {"ghost": 0})
    with gate.acquire_local_llm_slot(timeout=1, priority="bulk"):
        pass
    assert client.zscore(gate._WAITERS_KEY, "ghost") is None


def test_counters_and_priority_are_recorded(gate):
    with gate.acquire_local_llm_slot(timeout=1, priority="rfq"):
        with pytest.raises(gate.LocalLLMQueueTimeout):
            with gate.acquire_local_llm_slot(timeout=0.1, priority="bulk"):
                pass
    s = gate.daily_stats()
    assert s["rfq:calls"] == "1"
    assert s["bulk:timeouts"] == "1"
    assert float(s["bulk:wait_s"]) >= 0.1


def test_priority_from_context_and_queue_wait(gate):
    assert gate.current_priority() == "interactive"
    with gate.llm_priority("bulk"):
        assert gate.current_priority() == "bulk"
        with gate.queue_wait(30, priority="rfq"):
            assert gate.current_priority() == "rfq"
            assert gate.queue_timeout_seconds() == 30
        assert gate.current_priority() == "bulk"
    assert gate.current_priority() == "interactive"
    with pytest.raises(ValueError):
        with gate.llm_priority("urgent"):
            pass
