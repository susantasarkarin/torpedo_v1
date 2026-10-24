"""Platform API: every endpoint requires a session; config writes are audited."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import platform_api
from session_state import verify_session


def _client(monkeypatch, user="owner"):
    app = FastAPI()
    app.include_router(platform_api.router)
    if user:
        app.dependency_overrides[verify_session] = lambda: user
        app.dependency_overrides[platform_api.require_approve] = lambda: user
    return TestClient(app)


def test_requires_login(monkeypatch):
    c = _client(monkeypatch, user=None)
    assert c.get("/api/platform/review-queue").status_code == 401


def test_config_put_rejects_unknown_keys(monkeypatch):
    from platform_core import config_store
    def _set(section, values, actor):
        raise ValueError("unknown keys for pricing: x")
    monkeypatch.setattr(config_store, "set", _set)
    r = _client(monkeypatch).put("/api/platform/config/pricing", json={"x": 1})
    assert r.status_code == 400


def test_resolve_passes_the_user_as_actor(monkeypatch):
    from platform_core import review_queue
    seen = {}
    monkeypatch.setattr(review_queue, "resolve", lambda i, a, actor, **k: seen.update(actor=actor, action=a) or {"ok": True})
    r = _client(monkeypatch).post("/api/platform/review-queue/abc/approve", json={})
    assert r.status_code == 200 and seen == {"actor": "owner", "action": "approve"}


def test_lead_export_builds_a_spreadsheet_with_header_and_rows():
    from datetime import datetime
    from openpyxl import load_workbook
    import io
    from routers.lead_export import build_workbook, COLUMNS
    data = build_workbook([{"name": "Asha", "company_name": "Acme", "outreach_bucket": "SFW",
                            "created_at": datetime(2026, 10, 1), "outreach_bucket_confidence": 0.9}])
    ws = load_workbook(io.BytesIO(data)).active
    rows = list(ws.values)
    assert rows[0][0] == "Name" and len(rows[0]) == len(COLUMNS)
    assert rows[1][0] == "Asha" and rows[1][2] == "Acme" and "SFW" in rows[1]


def test_shadow_report_masks_addresses_and_counts_outcomes():
    from datetime import datetime, timedelta
    from platform_core import shadow_report as sr
    from tests._fakemongo import FakeDB
    ea = FakeDB()
    now = datetime(2026, 10, 24, 12)
    ea["rfq_decisions"].insert_one({"decided_at": now - timedelta(hours=1), "status": "awaiting_info", "to": "raj.kumar@client.com"})
    ea["rfq_decisions"].insert_one({"decided_at": now - timedelta(hours=30), "status": "priced"})
    out = sr.build(lambda name: ea, 24, now)
    rfq = next(m for m in out["modules"] if m["module"] == "rfq")
    assert rfq["decisions"] == 1 and rfq["outcomes"] == {"awaiting_info": 1}
    assert rfq["samples"][0]["to"] == "ra***@client.com"
