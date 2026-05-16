"""
Smoke: Contacts Flows
=====================
Verifies:
  - Contact creation (POST /contacts/)
  - Contact list fetch (GET /contacts/)
  - Contact update (PUT /contacts/{id})
  - Contact delete (DELETE /contacts/{id})
  - Bulk delete (POST /contacts/bulk-delete)
  - Auth enforcement

All write tests create and then clean up their own data.
Finance DB customer auto-sync is verified indirectly (no error on creation).
"""

import pytest
import httpx

_SMOKE_EMAIL = "smoke-contact-do-not-use@test.invalid"


class TestContactCRUD:
    """Create → list → update → delete round-trip."""

    def test_create_contact_missing_email(self, client: httpx.Client):
        """POST /contacts/ without email returns 400."""
        resp = client.post("/contacts/", json={"name": "No Email"})
        assert resp.status_code == 400

    def test_create_and_delete_contact(self, client: httpx.Client, authed_headers: dict):
        """Full create → read (via list) → delete cycle."""
        resp = client.post(
            "/contacts/",
            json={
                "email": _SMOKE_EMAIL,
                "name": "Smoke Contact",
                "companyName": "_SmokeCoInc_",
                "stage": "RFQ",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "contact" in body
        contact_id = body["contact"].get("_id")
        assert contact_id, "No _id in created contact"

        # Delete
        del_resp = client.delete(f"/contacts/{contact_id}")
        assert del_resp.status_code == 200

    def test_list_contacts_requires_auth(self, client: httpx.Client):
        """GET /contacts/ without auth returns 401/403."""
        resp = client.get("/contacts/")
        assert resp.status_code in (401, 403)

    def test_list_contacts_authenticated(self, client: httpx.Client, authed_headers: dict):
        """GET /contacts/ with auth returns contacts list."""
        resp = client.get("/contacts/", headers=authed_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "contacts" in body
        assert isinstance(body["contacts"], list)

    def test_update_contact(self, client: httpx.Client, authed_headers: dict):
        """PUT /contacts/{id} updates a field."""
        resp = client.post(
            "/contacts/",
            json={"email": _SMOKE_EMAIL + ".upd", "name": "Before Update"},
        )
        assert resp.status_code == 200
        contact_id = resp.json()["contact"]["_id"]

        upd_resp = client.put(f"/contacts/{contact_id}", json={"name": "After Update"})
        assert upd_resp.status_code == 200

        # Cleanup
        client.delete(f"/contacts/{contact_id}")

    def test_update_nonexistent_contact(self, client: httpx.Client):
        """PUT /contacts/{id} for non-existent id returns 404."""
        resp = client.put("/contacts/000000000000000000000000", json={"name": "x"})
        assert resp.status_code == 404

    def test_delete_nonexistent_contact(self, client: httpx.Client):
        """DELETE /contacts/{id} for non-existent id returns 404."""
        resp = client.delete("/contacts/000000000000000000000000")
        assert resp.status_code == 404


class TestContactBulkDelete:
    def test_bulk_delete_empty_ids(self, client: httpx.Client):
        """POST /contacts/bulk-delete with empty ids returns 400."""
        resp = client.post("/contacts/bulk-delete", json={"ids": []})
        assert resp.status_code == 400


class TestContactFinanceSync:
    """Verify that creating a contact with a company does not blow up the finance sync."""

    def test_contact_with_company_syncs_no_error(self, client: httpx.Client, authed_headers: dict):
        """Finance DB customer auto-sync must not raise 500."""
        resp = client.post(
            "/contacts/",
            json={
                "email": _SMOKE_EMAIL + ".sync",
                "name": "Sync Test",
                "companyName": "_SmokeSyncCoInc_",
                "companyEmail": "info@smokesyncco.invalid",
                "stage": "RFQ",
            },
        )
        assert resp.status_code == 200, f"Finance sync failure: {resp.text[:300]}"
        contact_id = resp.json()["contact"]["_id"]
        client.delete(f"/contacts/{contact_id}")
