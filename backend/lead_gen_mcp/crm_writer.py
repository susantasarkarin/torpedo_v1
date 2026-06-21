"""
CRM writer — Option A: HTTP client to the in-house CRM REST API.

Endpoint: POST /api/crm/contacts
Auth: internal service token via X-Service-Token header.

Every write is idempotent: each contact carries
  external_id = SHA-256(profile_url)
stored in customFields. The writer pre-checks the CRM for existing contacts
by querying GET /api/crm/contacts?external_id=<id> before creating.

One bad write never kills the batch — all errors are collected in `failed`.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional

import httpx

from .schemas import CRMPushOutput, EnrichedLead
from . import state as st

CRM_BASE_URL = os.getenv("CRM_BASE_URL", "http://localhost:8000")
CRM_SERVICE_TOKEN = os.getenv("CRM_SERVICE_TOKEN", "")

_HEADERS = {
    "X-Service-Token": CRM_SERVICE_TOKEN,
    "Content-Type": "application/json",
}


def _external_id(profile_url: str) -> str:
    return hashlib.sha256(profile_url.strip().lower().encode()).hexdigest()


def _build_contact_payload(lead: EnrichedLead, run_id: str) -> Dict[str, Any]:
    first, *rest = (lead.name or "").split() or [""]
    last = " ".join(rest) if rest else ""
    eid = _external_id(lead.profile_url)

    return {
        "email": lead.email,
        "firstName": first or None,
        "lastName": last or None,
        "company": lead.company,
        "tags": ["lead-gen-pipeline", lead.icp_id],
        "customFields": {
            "external_id": eid,
            "source_query": lead.source_query,
            "icp_id": lead.icp_id,
            "hunter_confidence": lead.hunter_confidence,
            "run_id": run_id,
            "profile_url": lead.profile_url,
            "icp_score": lead.icp_score,
            "verification_status": lead.verification_status,
        },
    }


async def _contact_exists(client: httpx.AsyncClient, external_id: str) -> Optional[str]:
    """
    Return the CRM contact ID if a contact with this external_id already exists,
    else None.
    """
    try:
        resp = await client.get(
            f"{CRM_BASE_URL}/api/crm/contacts",
            params={"external_id": external_id},
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items", [])
            for item in items:
                cf = item.get("customFields") or item.get("custom_fields") or {}
                if cf.get("external_id") == external_id:
                    return str(item.get("_id") or item.get("id", ""))
    except Exception:
        pass
    return None


async def push_to_crm(
    leads: List[EnrichedLead],
    run_id: str,
) -> CRMPushOutput:
    """
    Push enriched leads to the in-house CRM.
    - Pre-deduplicates against CRM by external_id
    - Upserts lead status in local SQLite
    - Never raises — all errors are in output.failed
    """
    created: List[str] = []
    skipped_duplicates: List[str] = []
    failed: List[Dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        for lead in leads:
            eid = _external_id(lead.profile_url)

            try:
                # Check CRM for existing contact
                existing_id = await _contact_exists(client, eid)
                if existing_id:
                    skipped_duplicates.append(eid)
                    st.upsert_lead({**lead.model_dump(), "status": "pushed", "crm_contact_id": existing_id})
                    continue

                payload = _build_contact_payload(lead, run_id)
                resp = await client.post(
                    f"{CRM_BASE_URL}/api/crm/contacts",
                    json=payload,
                    headers=_HEADERS,
                    timeout=15,
                )
                resp.raise_for_status()
                body = resp.json()
                crm_id = str(body.get("_id") or body.get("id", ""))

                created.append(eid)
                st.upsert_lead({**lead.model_dump(), "status": "pushed", "crm_contact_id": crm_id})

            except Exception as exc:
                failed.append({"external_id": eid, "error": str(exc)})
                st.upsert_lead({**lead.model_dump(), "status": "failed"})

    return CRMPushOutput(
        created=created,
        skipped_duplicates=skipped_duplicates,
        failed=failed,
    )
