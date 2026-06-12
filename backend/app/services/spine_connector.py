"""
SPINE CONNECTOR — cross-module integration into the canonical CRM spine
=======================================================================
Every module (leads, sales, finance, panel, RFQ) historically wrote only to
its own legacy collections, so information never flowed between them. This
module mirrors module events into the canonical `crm_db` spine
(accounts / contacts / leads / invoices + the `activities` link layer) so
any module — and the AI agents — can see the full picture via /api/crm/*.

Design rules (same as routers/rfq.mirror_rfq_to_spine):
- Best-effort and NON-FATAL: a mirror failure must never break the legacy
  write path. Every public function swallows exceptions and returns None.
- Idempotent-ish: dedupe through crm_service.get_or_create_account /
  get_or_create_contact (normalized name / email).
- Provenance: every mirrored doc carries metadata.source / source_id.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _crm():
    try:
        from . import crm_service
    except ImportError:  # flat-import fallback (uvicorn run from backend/)
        from app.services import crm_service
    return crm_service


def mirror_lead_to_spine(lead: Dict[str, Any], source: str,
                         source_id: Optional[str] = None) -> Optional[str]:
    """
    Mirror an ingested lead into crm_db: dedupe/create Account (by company)
    and Contact (by email), create a canonical lead, link via an activity.
    Returns the canonical lead id, or None.
    """
    try:
        crm = _crm()
        email = (lead.get("email") or "").strip().lower()
        company = (lead.get("company_name") or lead.get("companyName")
                   or lead.get("company") or "").strip()
        name = (lead.get("name") or lead.get("full_name")
                or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip())

        account_id = None
        if company:
            account, _ = crm.get_or_create_account(
                company, defaults={"metadata": {"source": source}})
            account_id = account["_id"]

        contact_id = None
        if email:
            contact, _ = crm.get_or_create_contact(
                email, defaults={"name": name, "account_id": account_id,
                                 "metadata": {"source": source}})
            contact_id = contact["_id"]

        canonical = crm.create("leads", {
            "name": name or email or company,
            "email": email or None,
            "title": lead.get("title") or lead.get("job_title"),
            "account_id": account_id,
            "contact_id": contact_id,
            "status": "new",
            "metadata": {"source": source, "source_id": source_id,
                         "industry": lead.get("company_industry") or lead.get("industry")},
        })

        crm.log_activity({
            "type": "lead_ingested",
            "object_type": "lead",
            "object_id": canonical["_id"],
            "lead_id": canonical["_id"],
            "account_id": account_id,
            "contact_id": contact_id,
            "summary": f"Lead ingested from {source}",
            "at": datetime.utcnow().isoformat(),
        })
        return canonical["_id"]
    except Exception as e:
        logger.warning(f"[spine] lead mirror failed (non-fatal): {e}")
        return None


def mirror_leads_bulk(items: List[Tuple[Dict[str, Any], Optional[str]]],
                      source: str) -> int:
    """
    Bulk variant of mirror_lead_to_spine for large imports: one
    get_or_create per UNIQUE company/email plus two insert_many calls,
    instead of ~5 round trips per lead. items = [(lead_dict, source_id)].
    Best-effort/non-fatal like every other mirror. Returns count mirrored.
    """
    try:
        if not items:
            return 0
        crm = _crm()
        now = datetime.utcnow()
        account_cache: Dict[str, str] = {}
        contact_cache: Dict[str, str] = {}
        lead_docs = []

        for lead, source_id in items:
            email = (lead.get("email") or "").strip().lower()
            company = (lead.get("company_name") or lead.get("companyName")
                       or lead.get("company") or "").strip()
            name = (lead.get("name") or lead.get("full_name")
                    or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip())

            account_id = None
            if company:
                ckey = company.lower()
                if ckey not in account_cache:
                    account, _ = crm.get_or_create_account(
                        company, defaults={"metadata": {"source": source}})
                    account_cache[ckey] = account["_id"]
                account_id = account_cache[ckey]

            contact_id = None
            if email:
                if email not in contact_cache:
                    contact, _ = crm.get_or_create_contact(
                        email, defaults={"name": name, "account_id": account_id,
                                         "metadata": {"source": source}})
                    contact_cache[email] = contact["_id"]
                contact_id = contact_cache[email]

            doc = {k: v for k, v in {
                "name": name or email or company,
                "email": email or None,
                "title": lead.get("title") or lead.get("job_title"),
                "account_id": account_id,
                "contact_id": contact_id,
                "status": "new",
                "metadata": {"source": source, "source_id": source_id,
                             "industry": lead.get("company_industry") or lead.get("industry")},
                "created_at": now,
                "updated_at": now,
            }.items() if v is not None}
            lead_docs.append(doc)

        result = crm._col("leads").insert_many(lead_docs, ordered=False)
        activities = [{
            "type": "lead_ingested",
            "object_type": "lead",
            "object_id": str(lead_id),
            "lead_id": str(lead_id),
            "account_id": doc.get("account_id"),
            "contact_id": doc.get("contact_id"),
            "summary": f"Lead ingested from {source}",
            "at": now.isoformat(),
            "created_at": now,
            "updated_at": now,
        } for lead_id, doc in zip(result.inserted_ids, lead_docs)]
        if activities:
            crm._col("activities").insert_many(activities, ordered=False)
        return len(result.inserted_ids)
    except Exception as e:
        logger.warning(f"[spine] bulk lead mirror failed (non-fatal): {e}")
        return 0


def mirror_sales_account_to_spine(name: str, source_id: Optional[str] = None,
                                  account_type: str = "client",
                                  extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Mirror a sales account into crm_db accounts (deduped by name)."""
    try:
        if not (name or "").strip():
            return None
        crm = _crm()
        account, created = crm.get_or_create_account(
            name.strip(),
            defaults={"account_type": account_type,
                      "metadata": {"source": "sales_accounts",
                                   "source_id": source_id, **(extra or {})}})
        if created:
            crm.log_activity({
                "type": "account_created",
                "object_type": "account",
                "object_id": account["_id"],
                "account_id": account["_id"],
                "summary": f"Account mirrored from sales module ({name})",
                "at": datetime.utcnow().isoformat(),
            })
        return account["_id"]
    except Exception as e:
        logger.warning(f"[spine] sales account mirror failed (non-fatal): {e}")
        return None


def mirror_finance_party_to_spine(name: str, party: str,
                                  source_id: Optional[str] = None) -> Optional[str]:
    """Mirror a finance customer/vendor into crm_db accounts. party: client|vendor."""
    try:
        if not (name or "").strip():
            return None
        crm = _crm()
        account, created = crm.get_or_create_account(
            name.strip(),
            defaults={"account_type": party,
                      "metadata": {"source": f"finance_{party}", "source_id": source_id}})
        if created:
            crm.log_activity({
                "type": "account_created",
                "object_type": "account",
                "object_id": account["_id"],
                "account_id": account["_id"],
                "summary": f"Account mirrored from finance ({party}: {name})",
                "at": datetime.utcnow().isoformat(),
            })
        return account["_id"]
    except Exception as e:
        logger.warning(f"[spine] finance party mirror failed (non-fatal): {e}")
        return None


def mirror_invoice_to_spine(invoice: Dict[str, Any], customer_name: Optional[str],
                            source_id: Optional[str] = None) -> Optional[str]:
    """
    Mirror a finance invoice into crm_db invoices linked to its account,
    and attach an activity so it shows on the account timeline.
    """
    try:
        crm = _crm()
        account_id = None
        if (customer_name or "").strip():
            account, _ = crm.get_or_create_account(
                customer_name.strip(),
                defaults={"account_type": "client",
                          "metadata": {"source": "finance_invoice"}})
            account_id = account["_id"]

        doc = crm.create("invoices", {
            "invoice_number": invoice.get("invoice_number") or invoice.get("number"),
            "account_id": account_id,
            "amount": invoice.get("total") or invoice.get("amount") or 0,
            "currency": invoice.get("currency") or "USD",
            "status": invoice.get("status") or "draft",
            "due_date": invoice.get("due_date"),
            "metadata": {"source": "finance", "source_id": source_id},
        })

        crm.log_activity({
            "type": "invoice_created",
            "object_type": "invoice",
            "object_id": doc["_id"],
            "account_id": account_id,
            "summary": f"Invoice {doc.get('invoice_number') or doc['_id']} "
                       f"({doc.get('amount')} {doc.get('currency')})",
            "at": datetime.utcnow().isoformat(),
        })
        return doc["_id"]
    except Exception as e:
        logger.warning(f"[spine] invoice mirror failed (non-fatal): {e}")
        return None


def mirror_panelist_registration_to_spine(email: str, name: Optional[str] = None,
                                          country: Optional[str] = None) -> Optional[str]:
    """
    Mirror a completed panelist registration (double opt-in) as a canonical
    Contact + activity, so panel growth is visible on the CRM side.
    """
    try:
        email = (email or "").strip().lower()
        if not email:
            return None
        crm = _crm()
        contact, _ = crm.get_or_create_contact(
            email, defaults={"name": name,
                             "metadata": {"source": "panel", "country": country}})
        crm.log_activity({
            "type": "panelist_registered",
            "object_type": "contact",
            "object_id": contact["_id"],
            "contact_id": contact["_id"],
            "summary": f"Panelist completed registration ({country or 'unknown country'})",
            "at": datetime.utcnow().isoformat(),
        })
        return contact["_id"]
    except Exception as e:
        logger.warning(f"[spine] panelist mirror failed (non-fatal): {e}")
        return None
