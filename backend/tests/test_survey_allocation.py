"""Survey allocation: value ordering, segment learning, quota-closed skip, fail-open."""
import asyncio
from datetime import date

import pytest

from services import survey_allocation as sa


class FakeCol:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.calls = rows or [], fail, 0

    def aggregate(self, pipeline):
        self.calls += 1
        if self.fail:
            raise RuntimeError("mongo down")
        rows = self.rows

        async def gen():
            for r in rows:
                yield r
        return gen()


def row(pid, status, n, g="m", y=1995, recent=False, stale=True):
    return {"_id": {"pid": pid, "status": status, "g": g, "y": y, "recent": recent, "stale": stale}, "n": n}


def proj(no, cpi=None, ir=None, prio=None):
    return {"surveyNo": no, "cpi": cpi, "clientIR": ir, "routingPriority": prio}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sa._CACHE.clear()
    monkeypatch.delenv("SURVEY_ALLOCATION", raising=False)


def run(coro):
    return asyncio.run(coro)


def test_segment_of():
    today = date(2026, 10, 19)
    assert sa.segment_of({"gender": "Male", "birthday_year": 2004}, today) == "m|18-24"
    assert sa.segment_of({"gender": "f", "birthday_year": "1980"}, today) == "f|45-54"
    assert sa.segment_of({}, today) == "?|?"


def test_higher_value_first():
    # same conversion history; higher CPI wins
    rows = [row("A", "COMPLETE", 10), row("A", "TERMINATED", 30), row("B", "COMPLETE", 10), row("B", "TERMINATED", 30)]
    out = run(sa.rank(FakeCol(rows), [proj("A", cpi=100), proj("B", cpi=200)], {"gender": "m", "birthday_year": 1995}))
    assert [p["surveyNo"] for p in out] == ["B", "A"]
    assert out[0]["_alloc"]["rank"] == 1 and out[0]["_alloc"]["of"] == 2


def test_converting_project_beats_terminating_one():
    rows = [row("A", "TERMINATED", 60), row("B", "COMPLETE", 20), row("B", "TERMINATED", 20)]
    out = run(sa.rank(FakeCol(rows), [proj("A", cpi=150), proj("B", cpi=150)], {"gender": "m", "birthday_year": 1995}))
    assert [p["surveyNo"] for p in out] == ["B", "A"]


def test_segment_history_overrides_project_rate():
    # A converts women well but terminates every man; a man should go to B
    rows = [row("A", "COMPLETE", 30, g="f"), row("A", "TERMINATED", 25, g="m"),
            row("B", "COMPLETE", 8, g="m"), row("B", "TERMINATED", 32, g="m")]
    man = {"gender": "m", "birthday_year": 1995}
    woman = {"gender": "f", "birthday_year": 1995}
    assert [p["surveyNo"] for p in run(sa.rank(FakeCol(rows), [proj("A", 150), proj("B", 150)], man))] == ["B", "A"]
    sa._CACHE.clear()
    assert [p["surveyNo"] for p in run(sa.rank(FakeCol(rows), [proj("A", 150), proj("B", 150)], woman))] == ["A", "B"]


def test_quota_closed_project_skipped():
    rows = [row("A", "COMPLETE", 40), row("A", "OVERQUOTA", 4, recent=True), row("B", "TERMINATED", 10)]
    out = run(sa.rank(FakeCol(rows), [proj("A", 150), proj("B", 150)], {}))
    assert [p["surveyNo"] for p in out] == ["B"]


def test_quota_not_closed_when_completes_still_coming():
    rows = [row("A", "OVERQUOTA", 4, recent=True), row("A", "COMPLETE", 1, recent=True)]
    out = run(sa.rank(FakeCol(rows), [proj("A", 150)], {}))
    assert [p["surveyNo"] for p in out] == ["A"]


def test_open_incompletes_ignored_stale_count_as_dropout():
    fresh = [row("A", "INCOMPLETE", 50, stale=False), row("A", "COMPLETE", 5)]
    stats = run(sa.project_stats(FakeCol(fresh), ["A"]))
    assert stats["A"]["decided"] == 5
    sa._CACHE.clear()
    stale = [row("A", "INCOMPLETE", 50, stale=True), row("A", "COMPLETE", 5)]
    assert run(sa.project_stats(FakeCol(stale), ["A"]))["A"]["decided"] == 55


def test_manual_priority_still_wins():
    rows = [row("A", "TERMINATED", 60), row("B", "COMPLETE", 30)]
    out = run(sa.rank(FakeCol(rows), [proj("A", 150, prio=1), proj("B", 150)], {}))
    assert [p["surveyNo"] for p in out] == ["A", "B"]


def test_missing_cpi_uses_median_and_prior_from_client_ir():
    out = run(sa.rank(FakeCol([]), [proj("A", None, ir=80), proj("B", 100, ir=20), proj("C", 300, ir=20)], {}))
    a = next(p for p in out if p["surveyNo"] == "A")["_alloc"]
    assert a["cpi"] == 200 and a["pProject"] == 0.2
    assert next(p for p in out if p["surveyNo"] == "B")["_alloc"]["pProject"] == 0.05


def test_quota_closed_from_48h_history():
    rows = [row("A", "OVERQUOTA", 18), row("B", "OVERQUOTA", 9), row("B", "COMPLETE", 1)]
    out = run(sa.rank(FakeCol(rows), [proj("A", 150), proj("B", 150)], {}))
    assert [p["surveyNo"] for p in out] == ["B"]


def test_fail_open_and_priority_mode(monkeypatch):
    ps = [proj("A", 100), proj("B", 500)]
    assert [p["surveyNo"] for p in run(sa.rank(FakeCol(fail=True), list(ps), {}))] == ["A", "B"]
    monkeypatch.setenv("SURVEY_ALLOCATION", "priority")
    col = FakeCol([])
    assert [p["surveyNo"] for p in run(sa.rank(col, list(ps), {}))] == ["A", "B"] and col.calls == 0


def test_stats_cached():
    col = FakeCol([row("A", "COMPLETE", 1)])
    run(sa.project_stats(col, ["A"]))
    run(sa.project_stats(col, ["A"]))
    assert col.calls == 1
