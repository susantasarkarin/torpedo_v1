"""
Zoho Books (India data centre) -- the finance system of record.

Owner decision 2026-09-28: invoices, GST, payments and the CA hand-off live in
Zoho Books; the CRM reads from it and, once enabled, creates customers and
draft invoices in it.

Configuration (backend/.env on the server -- never in code or chat):
  ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET   a "Self Client" from api-console.zoho.in
  ZOHO_REFRESH_TOKEN                   written by scripts/zoho_connect.py
  ZOHO_ORG_ID                          the Books organisation id
  ZOHO_WRITE_ENABLED=false             creating anything in Books is off until
                                       the owner turns it on
India endpoints: accounts.zoho.in (OAuth), www.zohoapis.in/books/v3 (API).
"""
import logging
import os
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)

ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in")
API_BASE = os.getenv("ZOHO_BOOKS_API_BASE", "https://www.zohoapis.in/books/v3")
# Read the invoices, contacts and payments; create contacts and invoices once
# writing is enabled. Used when generating the Self Client grant code.
SCOPES = ("ZohoBooks.contacts.ALL,ZohoBooks.invoices.ALL,"
          "ZohoBooks.customerpayments.READ,ZohoBooks.settings.READ")


class ZohoNotConfigured(RuntimeError):
    pass


class ZohoError(RuntimeError):
    pass


class ZohoWriteDisabled(RuntimeError):
    pass


def _cfg(name: str) -> str:
    return (os.getenv(name) or "").strip()


def configured() -> bool:
    return all(_cfg(n) for n in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_ORG_ID"))


def missing_settings() -> List[str]:
    return [n for n in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_ORG_ID") if not _cfg(n)]


def exchange_grant_code(code: str) -> Dict[str, Any]:
    """One-time: turn a Self Client grant code into a refresh token."""
    r = requests.post(f"{ACCOUNTS_URL}/oauth/v2/token", data={
        "grant_type": "authorization_code", "code": code,
        "client_id": _cfg("ZOHO_CLIENT_ID"), "client_secret": _cfg("ZOHO_CLIENT_SECRET")}, timeout=30)
    data = r.json() if r.content else {}
    if r.status_code != 200 or "refresh_token" not in data:
        raise ZohoError(f"grant code exchange failed: {r.status_code} {data.get('error') or data}")
    return data


class _Token:
    """Access tokens last an hour; refresh a minute early, one refresh at a time."""
    value: Optional[str] = None
    expires_at: float = 0.0
    lock = threading.Lock()


def access_token() -> str:
    if not configured():
        raise ZohoNotConfigured("Zoho Books is not connected: missing " + ", ".join(missing_settings()))
    with _Token.lock:
        if _Token.value and time.time() < _Token.expires_at - 60:
            return _Token.value
        r = requests.post(f"{ACCOUNTS_URL}/oauth/v2/token", data={
            "grant_type": "refresh_token", "refresh_token": _cfg("ZOHO_REFRESH_TOKEN"),
            "client_id": _cfg("ZOHO_CLIENT_ID"), "client_secret": _cfg("ZOHO_CLIENT_SECRET")}, timeout=30)
        data = r.json() if r.content else {}
        if r.status_code != 200 or "access_token" not in data:
            raise ZohoError(f"token refresh failed: {r.status_code} {data.get('error') or data}")
        _Token.value = data["access_token"]
        _Token.expires_at = time.time() + float(data.get("expires_in", 3600))
        return _Token.value


def _request(method: str, path: str, params: Optional[Dict[str, Any]] = None,
             json: Optional[Dict[str, Any]] = None, retries: int = 3) -> Dict[str, Any]:
    params = {"organization_id": _cfg("ZOHO_ORG_ID"), **(params or {})}
    for attempt in range(retries):
        r = requests.request(method, f"{API_BASE}{path}", params=params, json=json, timeout=60,
                             headers={"Authorization": f"Zoho-oauthtoken {access_token()}"})
        if r.status_code == 429 and attempt < retries - 1:  # 100 requests/minute per org
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 401 and attempt < retries - 1:  # token revoked or expired early
            _Token.value = None
            continue
        data = r.json() if r.content else {}
        if r.status_code >= 400 or data.get("code", 0) != 0:
            raise ZohoError(f"{method} {path}: {r.status_code} {data.get('message') or data}")
        return data
    raise ZohoError(f"{method} {path}: gave up after {retries} attempts")


def get(path: str, **params) -> Dict[str, Any]:
    return _request("GET", path, params=params)


def paged(path: str, key: str, **params) -> Iterator[Dict[str, Any]]:
    """Every record of a list endpoint, 200 per page."""
    page = 1
    while True:
        data = get(path, page=page, per_page=200, **params)
        for row in data.get(key) or []:
            yield row
        if not (data.get("page_context") or {}).get("has_more_page"):
            return
        page += 1


def organization() -> Dict[str, Any]:
    return get(f"/organizations/{_cfg('ZOHO_ORG_ID')}").get("organization") or {}


def invoices(**filters) -> Iterator[Dict[str, Any]]:
    return paged("/invoices", "invoices", **filters)


def contacts(**filters) -> Iterator[Dict[str, Any]]:
    return paged("/contacts", "contacts", **filters)


def customer_payments(**filters) -> Iterator[Dict[str, Any]]:
    return paged("/customerpayments", "customerpayments", **filters)


def _require_write():
    if _cfg("ZOHO_WRITE_ENABLED").lower() != "true":
        raise ZohoWriteDisabled("Writing to Zoho Books is off (ZOHO_WRITE_ENABLED is not true)")


def create_contact(payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_write()
    return _request("POST", "/contacts", json=payload).get("contact") or {}


def create_draft_invoice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Created as a draft in Books; a person reviews and sends it there."""
    _require_write()
    return _request("POST", "/invoices", json=payload).get("invoice") or {}
