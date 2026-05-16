"""
Smoke: Campaign Flows
=====================
Verifies:
  - Template CRUD (create, list, update, delete)
  - List CRUD (create, fetch, delete)
  - Upload-CSV endpoint accepts valid payload
  - Reports endpoint accessible
  - Tracking pixel endpoint returns 1×1 GIF
  - Send-emails endpoint validates missing body correctly

All write tests create and then clean up their own data.
"""

import pytest
import httpx


class TestTemplateCRUD:
    """Template create → list → update → delete round-trip."""

    def test_create_template(self, client: httpx.Client):
        """POST /templates/ creates a new template."""
        payload = {
            "name": "_smoke_template_",
            "subject": "Smoke test subject",
            "htmlContent": "<p>Hello {{contact.name}}</p>",
        }
        resp = client.post("/templates/", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "template" in body
        template_id = body["template"].get("_id")
        assert template_id, "No _id in created template"

        # Cleanup
        del_resp = client.delete(f"/templates/{template_id}")
        assert del_resp.status_code == 200

    def test_list_templates_requires_auth(self, client: httpx.Client):
        """GET /templates/ without auth returns 401/403."""
        resp = client.get("/templates/")
        assert resp.status_code in (401, 403)

    def test_list_templates_authenticated(self, client: httpx.Client, authed_headers: dict):
        """GET /templates/ with auth returns templates list."""
        resp = client.get("/templates/", headers=authed_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "templates" in body
        assert isinstance(body["templates"], list)

    def test_template_update_nonexistent(self, client: httpx.Client):
        """PUT /templates/{id} for non-existent id returns 404."""
        resp = client.put("/templates/000000000000000000000000", json={"subject": "x"})
        assert resp.status_code == 404

    def test_delete_template_nonexistent(self, client: httpx.Client):
        """DELETE /templates/{id} for non-existent id returns 404."""
        resp = client.delete("/templates/000000000000000000000000")
        assert resp.status_code == 404


class TestListCRUD:
    """List create → fetch → delete round-trip."""

    def test_create_list(self, client: httpx.Client):
        """POST /create-list/ creates a contact list."""
        payload = {"name": "_smoke_list_", "description": "smoke test list"}
        resp = client.post("/create-list/", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "list" in body
        list_id = body["list"].get("_id")
        assert list_id

        # Cleanup
        del_resp = client.delete(f"/delete-list/{list_id}")
        assert del_resp.status_code == 200

    def test_list_lists_requires_auth(self, client: httpx.Client):
        """GET /lists/ without auth returns 401/403."""
        resp = client.get("/lists/")
        assert resp.status_code in (401, 403)

    def test_list_lists_authenticated(self, client: httpx.Client, authed_headers: dict):
        """GET /lists/ with auth returns list of lists."""
        resp = client.get("/lists/", headers=authed_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "lists" in body
        assert isinstance(body["lists"], list)


class TestContactsForList:
    """Upload contacts and fetch by list identifier."""

    def test_upload_csv_empty_contacts(self, client: httpx.Client):
        """POST /upload-csv/ with empty list returns 200 (0 contacts)."""
        resp = client.post("/upload-csv/", json={"contacts": []})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("contacts") == [] or "0" in body.get("message", "")

    def test_get_contacts_by_list_nonexistent(self, client: httpx.Client):
        """GET /contacts/{id} for unknown list returns 200 with empty list."""
        resp = client.get("/contacts/__smoke_no_such_list__")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("contacts") == []


class TestReportsAndTracking:
    def test_reports_require_auth(self, client: httpx.Client):
        """GET /reports/ without auth returns 401/403."""
        resp = client.get("/reports/")
        assert resp.status_code in (401, 403)

    def test_reports_authenticated(self, client: httpx.Client, authed_headers: dict):
        """GET /reports/ with auth returns campaigns list."""
        resp = client.get("/reports/", headers=authed_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "campaigns" in body

    def test_tracking_pixel_returns_gif(self, client: httpx.Client):
        """GET /track/open returns a 1×1 GIF (no auth required — tracking pixels must be public)."""
        resp = client.get("/track/open", params={"c": "_smoke_", "e": "smoke@test.invalid"})
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "image/gif"
        assert len(resp.content) > 0

    def test_send_emails_missing_body(self, client: httpx.Client):
        """POST /send-emails/ with no contacts/template returns 400."""
        resp = client.post("/send-emails/", json={})
        assert resp.status_code in (400, 422)
