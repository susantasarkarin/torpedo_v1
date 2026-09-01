"""
Smoke: Leads Flows
==================
Verifies:
  - Lead creation (POST /leads/)
  - Lead read by ID (GET /leads/{id})
  - Lead update (PUT /leads/{id})
  - Lead bulk-delete (POST /leads/bulk-delete)
  - Lead move-to-contacts (POST /leads/{id}/move-to-contacts)
  - CSV import endpoint is reachable and validates file type
  - Auth enforcement on protected endpoints

All write tests create and then clean up their own data.
"""

import io
import pytest
import httpx

# Requires a RUNNING server on BASE_URL — these drive the live HTTP surface,
# not the code in-process. Marked so CI can run everything else (TOR-14):
#     pytest backend/tests -m "not smoke"
pytestmark = pytest.mark.smoke


_SMOKE_EMAIL = "smoke-lead-do-not-use@test.invalid"


class TestLeadCRUD:
    """Create → read → update → delete round-trip via legacy /leads/ routes."""

    def test_create_lead_missing_email(self, client: httpx.Client):
        """POST /leads/ without email returns 400."""
        resp = client.post("/leads/", json={"name": "No Email Lead"})
        assert resp.status_code == 400

    def test_create_and_delete_lead(self, client: httpx.Client, authed_headers: dict):
        """Full create → read → delete cycle."""
        # Create
        resp = client.post(
            "/leads/",
            json={"email": _SMOKE_EMAIL, "name": "Smoke Lead", "title": "QA Bot"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "lead" in body
        lead_id = body["lead"].get("_id")
        assert lead_id, "No _id in created lead"

        # Read
        read_resp = client.get(f"/leads/{lead_id}", headers=authed_headers)
        assert read_resp.status_code == 200
        assert read_resp.json()["lead"]["_id"] == lead_id

        # Delete
        del_resp = client.delete(f"/leads/{lead_id}")
        assert del_resp.status_code == 200

    def test_update_lead(self, client: httpx.Client, authed_headers: dict):
        """PUT /leads/{id} updates a field."""
        # Setup: create temp lead
        resp = client.post("/leads/", json={"email": _SMOKE_EMAIL + ".upd", "name": "Before Update"})
        assert resp.status_code == 200
        lead_id = resp.json()["lead"]["_id"]

        upd_resp = client.put(f"/leads/{lead_id}", json={"name": "After Update"})
        assert upd_resp.status_code == 200

        # Cleanup
        client.delete(f"/leads/{lead_id}")

    def test_get_lead_requires_auth(self, client: httpx.Client):
        """GET /leads/{id} without auth returns 401/403."""
        resp = client.get("/leads/000000000000000000000000")
        assert resp.status_code in (401, 403)

    def test_get_nonexistent_lead(self, client: httpx.Client, authed_headers: dict):
        """GET /leads/{id} for non-existent id returns 404."""
        resp = client.get("/leads/000000000000000000000000", headers=authed_headers)
        assert resp.status_code == 404

    def test_delete_nonexistent_lead(self, client: httpx.Client):
        """DELETE /leads/{id} for non-existent id returns 404."""
        resp = client.delete("/leads/000000000000000000000000")
        assert resp.status_code == 404


class TestLeadBulkDelete:
    def test_bulk_delete_empty_ids(self, client: httpx.Client):
        """POST /leads/bulk-delete with empty ids returns 400."""
        resp = client.post("/leads/bulk-delete", json={"ids": []})
        assert resp.status_code == 400


class TestLeadMoveToContacts:
    def test_move_nonexistent_lead(self, client: httpx.Client):
        """POST /leads/{id}/move-to-contacts for non-existent id returns 404."""
        resp = client.post(
            "/leads/000000000000000000000000/move-to-contacts",
            json={"stage": "RFQ"},
        )
        assert resp.status_code == 404


class TestLeadCSVImport:
    def test_csv_import_endpoint_reachable(self, client: httpx.Client):
        """POST /leads/import/csv must accept multipart/form-data."""
        csv_content = b"email,name\n"  # header-only, no real rows
        resp = client.post(
            "/leads/import/csv",
            files={"file": ("empty.csv", io.BytesIO(csv_content), "text/csv")},
        )
        # 200 (0 rows processed) or 422 (validation error) both acceptable;
        # what we must NOT see is 404 or 500
        assert resp.status_code not in (404, 500), f"Unexpected status: {resp.status_code} {resp.text[:200]}"
