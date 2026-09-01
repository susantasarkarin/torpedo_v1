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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mirror failure accounting (TOR-13)
# ---------------------------------------------------------------------------
# Every mirror below is best-effort and swallows its exception, by design: a
# spine write must never break the legacy write that triggered it. But nothing
# counted the swallows, so a mirror that had been failing all day looked
# exactly like one that had never been called — and the drift sat invisible
# until the 02:30 reconcile, or forever for anything the reconcile doesn't
# specifically handle.
#
# Failures are now counted in memory (cheap, for the health endpoint) AND
# written to crm_db.spine_mirror_failures with the source id, so "which
# records are missing from the spine" is an answerable question.

_FAILURE_COUNTS: Dict[str, int] = {}


def _record_failure(kind: str, error: Exception,
                    source: Optional[str] = None,
                    source_id: Optional[str] = None) -> None:
    """Log at WARNING, count, and persist enough to find the record later."""
    _FAILURE_COUNTS[kind] = _FAILURE_COUNTS.get(kind, 0) + 1
    logger.warning("[spine] %s mirror failed (non-fatal) source=%s id=%s: %s",
                   kind, source, source_id, error)
    try:
        crm = _crm()
        crm._db()["spine_mirror_failures"].insert_one({
            "kind": kind,
            "source": source,
            "source_id": source_id,
            "error": f"{type(error).__name__}: {error}"[:500],
            "at": datetime.utcnow(),
        })
    except Exception:
        # The failure log failing is not worth escalating — the WARNING above
        # already reached journalctl, which is the floor we care about.
        logger.debug("[spine] could not persist mirror failure", exc_info=True)


def mirror_stats() -> Dict[str, Any]:
    """
    Mirror health since process start, plus the persisted failure backlog.
    Surfaced by GET /api/crm/spine-health.
    """
    total_fail = sum(_FAILURE_COUNTS.values())
    stats: Dict[str, Any] = {
        "since_process_start": {
            "failed": total_fail,
            "by_kind": dict(_FAILURE_COUNTS),
        },
        # The number to watch. It should be 0. Anything else means legacy
        # writes are landing without their spine counterpart, and the 02:30
        # reconcile will only catch the subset it explicitly handles.
        "healthy": total_fail == 0,
    }
    try:
        col = _crm()._db()["spine_mirror_failures"]
        since = datetime.utcnow() - timedelta(days=7)
        stats["persisted_failures_7d"] = col.count_documents({"at": {"$gte": since}})
        stats["recent_failures"] = [
            {k: v for k, v in doc.items() if k != "_id"}
            for doc in col.find({"at": {"$gte": since}}).sort("at", -1).limit(20)
        ]
    except Exception:
        stats["persisted_failures_7d"] = None
    return stats



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
        _record_failure("lead mirror", e)
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
        _record_failure("bulk lead mirror", e)
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
        _record_failure("sales account mirror", e)
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
        _record_failure("finance party mirror", e)
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
        _record_failure("invoice mirror", e)
        return None


def mirror_finance_parties_bulk(names: List[str], party: str,
                                source: Optional[str] = None) -> Dict[str, str]:
    """
    Bulk variant of mirror_finance_party_to_spine for CSV imports.
    Returns {name: spine_account_id} for every name that mirrored, so the
    caller can write crm_account_id back-references onto the legacy docs.
    party: client|vendor.
    """
    mapping: Dict[str, str] = {}
    try:
        crm = _crm()
        for name in {(n or "").strip() for n in names}:
            if not name:
                continue
            try:
                account, created = crm.get_or_create_account(
                    name,
                    defaults={"account_type": party,
                              "metadata": {"source": source or f"finance_{party}"}})
                mapping[name] = account["_id"]
                if created:
                    crm.log_activity({
                        "type": "account_created",
                        "object_type": "account",
                        "object_id": account["_id"],
                        "account_id": account["_id"],
                        "summary": f"Account mirrored from finance import ({party}: {name})",
                        "at": datetime.utcnow().isoformat(),
                    })
            except Exception:
                continue
        return mapping
    except Exception as e:
        _record_failure("bulk finance party mirror", e)
        return mapping


def mirror_invoices_bulk(items: List[Tuple[Dict[str, Any], Optional[str], Optional[str]]]
                         ) -> int:
    """
    Bulk variant of mirror_invoice_to_spine for CSV imports.
    items = [(invoice_dict, customer_name, source_id)]. One get_or_create per
    unique customer plus two insert_many calls. Returns count mirrored.
    """
    try:
        if not items:
            return 0
        crm = _crm()
        now = datetime.utcnow()
        account_cache: Dict[str, str] = {}
        docs = []
        for invoice, customer_name, source_id in items:
            account_id = None
            cname = (customer_name or "").strip()
            if cname:
                ckey = cname.lower()
                if ckey not in account_cache:
                    account, _ = crm.get_or_create_account(
                        cname, defaults={"account_type": "client",
                                         "metadata": {"source": "finance_invoice"}})
                    account_cache[ckey] = account["_id"]
                account_id = account_cache[ckey]
            docs.append({
                "invoice_number": invoice.get("invoice_number") or invoice.get("number"),
                "account_id": account_id,
                "amount": invoice.get("total") or invoice.get("amount") or 0,
                "currency": invoice.get("currency") or invoice.get("currency_code") or "USD",
                "status": invoice.get("status") or "draft",
                "due_date": invoice.get("due_date"),
                "metadata": {"source": "finance", "source_id": source_id},
                "created_at": now,
                "updated_at": now,
            })
        result = crm._col("invoices").insert_many(docs, ordered=False)
        activities = [{
            "type": "invoice_created",
            "object_type": "invoice",
            "object_id": str(inv_id),
            "account_id": doc.get("account_id"),
            "summary": f"Invoice {doc.get('invoice_number') or inv_id} "
                       f"({doc.get('amount')} {doc.get('currency')})",
            "at": now.isoformat(),
            "created_at": now,
            "updated_at": now,
        } for inv_id, doc in zip(result.inserted_ids, docs)]
        if activities:
            crm._col("activities").insert_many(activities, ordered=False)
        return len(result.inserted_ids)
    except Exception as e:
        _record_failure("bulk invoice mirror", e)
        return 0


def mirror_email_activity_to_spine(direction: str, email: str,
                                   name: Optional[str] = None,
                                   company: Optional[str] = None,
                                   subject: Optional[str] = None,
                                   summary: Optional[str] = None,
                                   source: str = "outreach",
                                   source_id: Optional[str] = None) -> Optional[str]:
    """
    Mirror an outreach email event onto the CRM timeline: dedupe/create the
    Contact (and Account when the company is known) and log an activity so
    sends and replies show up on /api/crm timelines.
    direction: "sent" | "reply_positive" | "reply_negative" | "reply_neutral".
    """
    try:
        email = (email or "").strip().lower()
        if not email:
            return None
        crm = _crm()

        account_id = None
        if (company or "").strip():
            account, _ = crm.get_or_create_account(
                company.strip(), defaults={"metadata": {"source": source}})
            account_id = account["_id"]

        contact, _ = crm.get_or_create_contact(
            email, defaults={"name": name, "account_id": account_id,
                             "metadata": {"source": source}})

        activity_type = "email_sent" if direction == "sent" else f"email_{direction}"
        crm.log_activity({
            "type": activity_type,
            "object_type": "contact",
            "object_id": contact["_id"],
            "contact_id": contact["_id"],
            "account_id": account_id or contact.get("account_id"),
            "summary": summary or (f"Email sent: {subject}" if direction == "sent"
                                   else f"Reply received ({direction}): {subject or ''}").strip(),
            "subject": subject,
            "metadata": {"source": source, "source_id": source_id},
            "at": datetime.utcnow().isoformat(),
        })
        return contact["_id"]
    except Exception as e:
        _record_failure("email activity mirror", e)
        return None


def mirror_ops_project_to_spine(project: Dict[str, Any],
                                client_name: Optional[str] = None,
                                source_id: Optional[str] = None) -> Optional[str]:
    """
    Mirror an operations project into crm_db projects, linked to the client's
    spine account, and log an activity on the account timeline.
    """
    try:
        crm = _crm()
        account_id = None
        if (client_name or "").strip():
            account, _ = crm.get_or_create_account(
                client_name.strip(),
                defaults={"account_type": "client",
                          "metadata": {"source": "operations"}})
            account_id = account["_id"]

        doc = crm.create("projects", {
            "name": project.get("name") or project.get("code"),
            "code": project.get("code"),
            "account_id": account_id,
            "status": project.get("status") or "planning",
            "metadata": {"source": "operations", "source_id": source_id},
        })
        crm.log_activity({
            "type": "project_created",
            "object_type": "project",
            "object_id": doc["_id"],
            "project_id": doc["_id"],
            "account_id": account_id,
            "summary": f"Operations project created: {doc.get('name')}",
            "at": datetime.utcnow().isoformat(),
        })
        return doc["_id"]
    except Exception as e:
        _record_failure("ops project mirror", e)
        return None


def update_spine_account(crm_account_id: str,
                         fields: Dict[str, Any]) -> bool:
    """
    Propagate a legacy-module update (e.g. a customer rename) onto the spine
    account referenced by a stored crm_account_id back-reference.
    """
    try:
        if not crm_account_id or not fields:
            return False
        crm = _crm()
        allowed = {k: v for k, v in fields.items()
                   if k in ("name", "account_type", "status") and v}
        if "name" in allowed:
            allowed["name_normalized"] = crm._normalize_name(allowed["name"])
        if not allowed:
            return False
        return crm.update("accounts", crm_account_id, allowed) is not None
    except Exception as e:
        _record_failure("account update", e)
        return False


def mark_spine_account_deleted(crm_account_id: str, source: str) -> bool:
    """
    Flag the spine account as source-deleted when its legacy doc is removed.
    Spine records are never hard-deleted (they anchor historical activities).
    """
    try:
        if not crm_account_id:
            return False
        crm = _crm()
        updated = crm.update("accounts", crm_account_id, {
            "metadata.source_deleted": True,
            "metadata.source_deleted_from": source,
            "metadata.source_deleted_at": datetime.utcnow().isoformat(),
        })
        return updated is not None
    except Exception as e:
        _record_failure("account delete-mark", e)
        return False


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
        _record_failure("panelist mirror", e)
        return None
