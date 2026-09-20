"""
The single mail-AI switch (sales/mail_ai_switch.py, MAIL_AI_ENABLED, default off).

Background: the 2026-09-19 "pause" only removed the beat entry. Gmail-sync
hooks and POST /rfq/resync kept enqueuing the legacy scan, which fabricates
RFQs -- so a paused pipeline was still writing. One switch now gates every
path, checked at the Celery tasks (where every enqueue path ends) and again
where work is enqueued, so nothing is even queued while it's off.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from sales import mail_ai_switch as sw


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(sw.ENV_VAR, raising=False)


def on(monkeypatch):
    monkeypatch.setenv(sw.ENV_VAR, "true")


# ---- the switch itself ----------------------------------------------------

def test_default_is_off():
    assert sw.mail_ai_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True), (" true ", True),
    ("false", False), ("0", False), ("", False), ("no", False), ("off", False), ("maybe", False)])
def test_values(monkeypatch, val, expected):
    monkeypatch.setenv(sw.ENV_VAR, val)
    assert sw.mail_ai_enabled() is expected


def test_read_live_not_at_import(monkeypatch):
    assert sw.mail_ai_enabled() is False
    on(monkeypatch)
    assert sw.mail_ai_enabled() is True


# ---- beat schedule --------------------------------------------------------

def test_beat_has_no_mail_ai_entries_while_off():
    assert sw.beat_entries() == {}


def test_beat_entries_exist_only_when_on(monkeypatch):
    on(monkeypatch)
    e = sw.beat_entries()
    assert set(e) == {"mail-pool-ai-sender-batch", "mail-pool-ai-prefilter-audit"}
    assert e["mail-pool-ai-sender-batch"]["kwargs"] == {"limit": 1}   # conservative re-enable


def test_the_live_beat_schedule_carries_no_mail_ai_entry_by_default():
    from celery_app import celery_app
    assert not [k for k in celery_app.conf.beat_schedule if k.startswith("mail-pool-ai")]


# ---- the four tasks: the choke point --------------------------------------

def _tasks():
    from tasks import mail_pool_ai_tasks as t
    return t


@pytest.mark.parametrize("task_name,target,kwargs", [
    ("process_mail_pool_batch", "sales.mail_pool_ai.process_batch", {"limit": 5}),
    ("process_mail_pool_sender_batch", "sales.mail_pool_ai.process_sender_batch", {"limit": 5}),
    ("rebuild_rfqs_all_senders_batch", "sales.mail_pool_ai.rebuild_rfqs_for_all_senders", {"limit": 5}),
    ("audit_prefiltered_mail", "sales.mail_pool_ai.audit_prefiltered_sample", {"sample": 5}),
])
def test_tasks_do_nothing_while_off(task_name, target, kwargs):
    with patch(target, side_effect=AssertionError("pipeline ran while switched off")):
        out = getattr(_tasks(), task_name)(**kwargs)
    assert out["skipped"] == "mail_ai_disabled"


@pytest.mark.parametrize("task_name,target,kwargs", [
    ("process_mail_pool_batch", "sales.mail_pool_ai.process_batch", {"limit": 5}),
    ("process_mail_pool_sender_batch", "sales.mail_pool_ai.process_sender_batch", {"limit": 5}),
    ("rebuild_rfqs_all_senders_batch", "sales.mail_pool_ai.rebuild_rfqs_for_all_senders", {"limit": 5}),
    ("audit_prefiltered_mail", "sales.mail_pool_ai.audit_prefiltered_sample", {"sample": 5}),
])
def test_tasks_run_when_on(monkeypatch, task_name, target, kwargs):
    on(monkeypatch)
    with patch(target, return_value={"ok": True}) as fn:
        out = getattr(_tasks(), task_name)(**kwargs)
    assert out == {"ok": True}
    fn.assert_called_once()


# ---- enqueue sites: nothing is even queued while off ----------------------

@pytest.mark.parametrize("module", ["app.services.gmail_service", "app.services.gmail_workspace_service"])
def test_gmail_sync_hooks_do_not_enqueue_while_off(module):
    import importlib
    svc = importlib.import_module(module)
    with patch("tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch.delay",
               side_effect=AssertionError("enqueued while switched off")):
        svc._trigger_mail_ai(40, "box@x.com")


@pytest.mark.parametrize("module", ["app.services.gmail_service", "app.services.gmail_workspace_service"])
def test_gmail_sync_hooks_enqueue_when_on(monkeypatch, module):
    import importlib
    on(monkeypatch)
    svc = importlib.import_module(module)
    with patch("tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch.delay") as delay:
        svc._trigger_mail_ai(40, "box@x.com")
    delay.assert_called_once_with(limit=10)


def test_resync_endpoints_return_409_while_off():
    from routers import rfq
    for fn in (rfq.resync_rfqs_from_mail, rfq.resync_all_rfqs_from_mail_pool):
        with patch("tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch.delay",
                   side_effect=AssertionError("queued")), \
             patch("tasks.mail_pool_ai_tasks.rebuild_rfqs_all_senders_batch.delay",
                   side_effect=AssertionError("queued")):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(fn(limit=5))
        assert exc.value.status_code == 409
        assert "switched off" in exc.value.detail


def test_resync_endpoint_queues_when_on(monkeypatch):
    from routers import rfq
    on(monkeypatch)
    with patch("tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch.delay",
               return_value=MagicMock(id="t1")):
        out = asyncio.run(rfq.resync_rfqs_from_mail(limit=5))
    assert out["success"] is True and out["task_id"] == "t1"


def test_backfill_script_queues_nothing_while_off():
    import importlib
    script = importlib.import_module("scripts.backfill_spine_rfqs")
    with patch("tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch.delay",
               side_effect=AssertionError("queued")):
        out = script.queue_mail_backfill(batches=3, per_batch=10)
    assert out == {"queued": 0, "disabled": True}
