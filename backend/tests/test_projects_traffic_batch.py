"""Project traffic stats for many projects in one read."""
from datetime import datetime, timedelta

from app.services.traffic_service import TrafficService


class _Col:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    def find(self, q, proj=None):
        self.queries.append(q)
        want = set(q["params.pid"]["$in"])
        return [d for d in self.docs if d["params"].get("api") == "false" and d["params"]["pid"] in want]


def _svc(docs):
    s = TrafficService.__new__(TrafficService)
    s.traffic_collection = _Col(docs)
    return s


def _rec(pid, status, mins=None):
    t0 = datetime(2026, 10, 1, 10, 0)
    d = {"params": {"api": "false", "pid": pid}, "status": status, "createdAt": t0.isoformat()}
    if mins:
        d["completedAt"] = (t0 + timedelta(minutes=mins)).isoformat()
    return d


def test_one_read_for_many_projects_and_same_numbers_as_one_by_one():
    docs = [_rec("A1", "complete", 10), _rec("A1", "complete", 20), _rec("A1", "terminate"),
            _rec("B2", "quotafull"), _rec("C3", "complete", 5)]
    svc = _svc(docs)
    many = svc.get_projects_traffic_stats(["A1", "B2", "Z9"])
    assert len(svc.traffic_collection.queries) == 1
    assert many["A1"]["total_started"] == 3 and many["A1"]["completes"] == 2
    assert many["Z9"]["total_started"] == 0 and many["Z9"]["median_loi"] is None
    single = _svc(docs).get_project_traffic_stats("A1")
    assert single == many["A1"]
