"""
RFQ won -> Finance + Operations handoff.

crm_service.mark_opportunity_won() is the only path that turns a lead/RFQ into
a client. It activates a CRM-spine project and a spine invoice stub, but the
Finance and Operations modules read their own collections -- finance_db.*
and email_automation.projects -- so a won deal never showed up there, and
project-close invoicing (routers/operations.py close_project) had no project
to close. This module bridges that, once per opportunity:

  Finance     finance_db.customers   find (by CRM account) or create, CUST-xxxxx
              finance_db.work_orders WO-xxxxx, draft: scope, value, payment terms
              finance_db.contracts   CON-xxxxx, draft: value, payment terms, dates
  Operations  email_automation.projects  live project, customer_id, projectValue

Customer/contract details a machine cannot know (GSTIN, PAN, billing address,
signed terms) are left for a person: the records are drafts, flagged, and a
CRM task is opened for each.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId

logger = logging.getLogger(__name__)

DEFAULT_PAYMENT_TERMS_DAYS = 30

_client = None


def _mongo():
    global _client
    if _client is None:
        from pymongo import MongoClient
        _client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                              serverSelectionTimeoutMS=5000)
    return _client


def _next_number(col, field: str, prefix: str) -> str:
    last = col.find_one({field: {"$regex": rf"^{prefix}-\d+$"}}, sort=[(field, -1)])
    n = 0
    if last:
        try:
            n = int(last[field].split("-", 1)[1])
        except (ValueError, IndexError):
            n = col.count_documents({})
    return f"{prefix}-{str(n + 1).zfill(5)}"


def _oid(value) -> Optional[ObjectId]:
    try:
        return ObjectId(str(value)) if value else None
    except Exception:
        return None


def _payment_terms_days(opportunity: Dict[str, Any]) -> int:
    raw = opportunity.get("payment_terms")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    m = re.search(r"(\d+)", str(raw or ""))
    return int(m.group(1)) if m else DEFAULT_PAYMENT_TERMS_DAYS


def _find_or_create_customer(fin, account: Dict[str, Any], contact: Dict[str, Any],
                             opportunity: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    customers = fin["customers"]
    account_id = str(account.get("_id")) if account.get("_id") else None
    name = (account.get("name") or opportunity.get("title") or "New client").strip()

    customer = None
    if account_id:
        customer = customers.find_one({"crm_account_id": account_id})
    if not customer and name:
        customer = customers.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
    if customer:
        if account_id and not customer.get("crm_account_id"):
            customers.update_one({"_id": customer["_id"]}, {"$set": {"crm_account_id": account_id}})
        return {**customer, "_created": False}

    doc = {
        "name": name,
        "company_name": name,
        "customer_number": _next_number(customers, "customer_number", "CUST"),
        "customer_type": "business",
        "email": (contact.get("email") or "").lower(),
        "phone": contact.get("phone") or "",
        "currency": opportunity.get("currency") or (opportunity.get("metadata") or {}).get("rfq", {}).get("currency") or "",
        "payment_terms": _payment_terms_days(opportunity),
        "gst_treatment": "",
        "gstin": "",
        "pan": "",
        "billing_address": {},
        "status": "active",
        "crm_account_id": account_id,
        "source": "rfq_won",
        "opportunity_id": str(opportunity["_id"]),
        "needs_details": True,   # GSTIN / PAN / billing address to be filled by finance
        "total_receivables": 0,
        "total_paid": 0,
        "created_at": now,
        "updated_at": now,
    }
    res = customers.insert_one(doc)
    doc["_id"] = res.inserted_id
    return {**doc, "_created": True}


def _open_task(title: str, opportunity_id: str, due: datetime, description: str = "") -> None:
    try:
        from app.services import crm_service
        crm_service.create("tasks", {
            "title": title, "description": description,
            "linked_object_type": "opportunity", "linked_object_id": opportunity_id,
            "due_date": due, "status": "open", "source": "rfq_won_handoff",
        })
    except Exception as e:
        logger.warning("won handoff: task creation failed: %s", e)


def handoff_won_opportunity(opportunity: Dict[str, Any],
                            crm_project: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create the Finance customer, work order, contract and Operations project
    for a won opportunity. Idempotent per opportunity; never raises."""
    try:
        return _handoff(opportunity, crm_project)
    except Exception as e:
        logger.exception("won handoff failed for opportunity %s", opportunity.get("_id"))
        return {"error": str(e)}


def _handoff(opportunity: Dict[str, Any], crm_project: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    client = _mongo()
    fin, ops, crm = client["finance_db"], client["email_automation"], client["crm_db"]
    opp_id = str(opportunity["_id"])
    now = datetime.utcnow()

    existing = fin["work_orders"].find_one({"opportunity_id": opp_id})
    if existing:
        return {"skipped": "already handed off", "work_order_id": str(existing["_id"])}

    rfq = (opportunity.get("metadata") or {}).get("rfq") or {}
    account = crm["accounts"].find_one({"_id": _oid(opportunity.get("account_id") or rfq.get("account_id"))}) or {}
    contact = crm["contacts"].find_one({"_id": _oid(opportunity.get("contact_id") or rfq.get("contact_id"))}) or {}

    customer = _find_or_create_customer(fin, account, contact, opportunity, now)
    customer_id = str(customer["_id"])
    amount = float(opportunity.get("amount") or rfq.get("budget") or 0) or 0.0
    currency = opportunity.get("currency") or rfq.get("currency") or customer.get("currency") or ""
    terms = _payment_terms_days(opportunity) if opportunity.get("payment_terms") else \
        int(customer.get("payment_terms") or DEFAULT_PAYMENT_TERMS_DAYS)
    title = opportunity.get("title") or rfq.get("title") or "Project"

    # Operations project -- what the Operations page and close_project work on.
    ops_project = {
        "projectName": title,
        "client": customer.get("name"),
        "customer_id": customer_id,
        "finance_customer_id": customer_id,
        "projectValue": amount,
        "currency": currency,
        "projectStatus": "live",
        "status": "active",
        "rfqId": opp_id,
        "opportunity_id": opp_id,
        "crm_project_id": str(crm_project["_id"]) if crm_project and crm_project.get("_id") else None,
        "rfqDetails": {k: rfq.get(k) for k in ("description", "deadline", "budget", "currency",
                                               "methodology", "sample_size", "country", "loi", "ir")
                       if rfq.get(k) is not None},
        "source": "rfq_won",
        "createdAt": now,
        "created_at": now,
    }
    ops_res = ops["projects"].insert_one(ops_project)
    ops_project_id = str(ops_res.inserted_id)

    work_order = {
        "work_order_number": _next_number(fin["work_orders"], "work_order_number", "WO"),
        "opportunity_id": opp_id,
        "customer_id": customer_id,
        "customer_name": customer.get("name"),
        "project_id": ops_project_id,
        "title": title,
        "scope": rfq.get("description") or "",
        "amount": amount,
        "currency": currency,
        "payment_terms": terms,
        "status": "draft",
        "client_po_number": "",
        "created_at": now,
        "updated_at": now,
        "source": "rfq_won",
    }
    wo_res = fin["work_orders"].insert_one(work_order)

    contract = {
        "contract_number": _next_number(fin["contracts"], "contract_number", "CON"),
        "opportunity_id": opp_id,
        "customer_id": customer_id,
        "customer_name": customer.get("name"),
        "work_order_id": str(wo_res.inserted_id),
        "project_id": ops_project_id,
        "value": amount,
        "currency": currency,
        "payment_terms": terms,
        "start_date": now,
        "end_date": None,
        "status": "draft",
        "signed_at": None,
        "created_at": now,
        "updated_at": now,
        "source": "rfq_won",
    }
    con_res = fin["contracts"].insert_one(contract)

    handoff = {
        "finance_customer_id": customer_id,
        "customer_number": customer.get("customer_number"),
        "customer_created": customer["_created"],
        "work_order_id": str(wo_res.inserted_id),
        "work_order_number": work_order["work_order_number"],
        "contract_id": str(con_res.inserted_id),
        "contract_number": contract["contract_number"],
        "ops_project_id": ops_project_id,
        "handed_off_at": now,
    }
    crm["opportunities"].update_one({"_id": _oid(opp_id)}, {"$set": {"metadata.handoff": handoff}})
    if crm_project and crm_project.get("_id"):
        crm["projects"].update_one({"_id": _oid(crm_project["_id"])}, {"$set": {
            "finance_customer_id": customer_id, "ops_project_id": ops_project_id}})

    due = now + timedelta(days=2)
    if customer["_created"]:
        _open_task(f"Complete billing details for {customer.get('name')} ({customer.get('customer_number')}): GSTIN, PAN, address",
                   opp_id, due)
    _open_task(f"Confirm work order {work_order['work_order_number']} / client PO for {title}", opp_id, due)
    _open_task(f"Finalise and send contract {contract['contract_number']} for signature", opp_id, due)

    logger.info("won handoff %s: %s", opp_id, handoff)
    return handoff
