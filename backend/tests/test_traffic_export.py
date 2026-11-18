"""Traffic list filter + streaming CSV export (owner 2026-11-18: export was slow and
the status filter did not match stored statuses)."""
import csv
import io
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.traffic_service import raw_statuses_for, traffic_filter_query
from routers import traffic


def test_display_status_maps_to_stored_statuses():
    assert "TERMINATED" in raw_statuses_for("Terminate")
    assert "OVERQUOTA" in raw_statuses_for("Quota Full")
    assert raw_statuses_for("Complete") == ["complete", "COMPLETE"]
    assert "INCOMPLETE" in raw_statuses_for("Incomplete")
    assert raw_statuses_for("") == []


def test_filter_query_combines_status_search_and_survey():
    q = traffic_filter_query("Quota Full", "2656", "S1")
    assert "OVERQUOTA" in q["status"]["$in"]
    assert q["assignedSurveyId"] == "S1"
    assert {"vendorId": {"$regex": "2656", "$options": "i"}} in q["$or"]


class _Cursor:
    def __init__(self, docs):
        self.docs = docs
        self.closed = False

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def batch_size(self, n):
        return self

    def __iter__(self):
        return iter(self.docs)

    def close(self):
        self.closed = True


class _Col:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def find(self, query, projection=None):
        self.calls.append((query, projection))
        return _Cursor(list(self.docs))


def _client(monkeypatch, docs):
    col = _Col(docs)
    monkeypatch.setattr(traffic, "url_parameters_collection", col)
    app = FastAPI()
    app.include_router(traffic.router)
    return TestClient(app), col


def test_export_streams_only_exported_fields_with_default_window(monkeypatch):
    now = datetime.utcnow()
    docs = [{"_id": f"id{i}", "status": "TERMINATED", "vendorId": "2656", "createdAt": now} for i in range(2500)]
    client, col = _client(monkeypatch, docs)
    r = client.get("/api/traffic/export/csv", params={"status": "Terminate"}, headers={"Authorization": "x"})
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["SFWID", "Status", "Vendor ID"]
    assert len(rows) == 2501
    query, projection = col.calls[0]
    assert "TERMINATED" in query["status"]["$in"]
    assert query["createdAt"]["$gte"] > now - timedelta(days=31)   # default: last 30 days
    assert "fingerprintComponents" not in projection and projection["status"] == 1


def test_export_rejects_bad_date(monkeypatch):
    client, _ = _client(monkeypatch, [])
    r = client.get("/api/traffic/export/csv", params={"start_date": "18-11-2026"}, headers={"Authorization": "x"})
    assert r.status_code == 400
