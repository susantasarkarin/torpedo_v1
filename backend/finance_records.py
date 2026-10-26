"""One list / record API for every Finance tab (owner, 2026-10-26).

The Finance pages share the Sales list (LeadTable) and one record page that
opens in its own tab, so each kind is configuration here, not a page of code:
  list    server paging, search over the kind's text fields, status filter,
          sort on whitelisted columns; customer names and per-customer
          counts joined for the page only
  get     the whole record (minus internal bulk) plus its links
  update  any field except the protected ones; the previous values are
          kept in edit_history and the change is audited
Customers are the CRM accounts we quote or bill (backfill finance_customers):
hidden / merged records never list.
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

KINDS: Dict[str, Dict[str, Any]] = {
    "customers": {"col": "customers", "search": ["name", "legal_name", "company_name", "email", "gstin"],
                  "sort": ["name", "created_at"], "default_sort": ("name", 1)},
    "estimates": {"col": "estimates", "search": ["estimate_number", "project_name", "customer_name"],
                  "sort": ["estimate_number", "date", "expiry_date", "status", "total_amount", "customer_name"],
                  "default_sort": ("date", -1),
                  "base": {"archived_backlog": {"$ne": True}, "is_latest": {"$ne": False}}},
    "invoices": {"col": "invoices", "search": ["invoice_number", "customer_name", "po_reference", "project_name"],
                 "sort": ["invoice_number", "invoice_date", "due_date", "status", "total", "balance_due"],
                 "default_sort": ("invoice_date", -1)},
    "payments_received": {"col": "payments_received", "search": ["payment_number", "reference", "customer_name",
                                                                 "invoice_number"],
                          "sort": ["payment_date", "amount"], "default_sort": ("payment_date", -1)},
    "payments_made": {"col": "payments_made", "search": ["payment_number", "reference", "vendor_name", "bill_number"],
                      "sort": ["payment_date", "amount"], "default_sort": ("payment_date", -1)},
    "vendors": {"col": "vendors", "search": ["name", "company_name", "email", "gstin"],
                "sort": ["name", "created_at"], "default_sort": ("name", 1)},
    "bills": {"col": "bills", "search": ["bill_number", "vendor_name", "reference"],
              "sort": ["bill_number", "bill_date", "due_date", "status", "total"], "default_sort": ("bill_date", -1)},
    "purchase_orders": {"col": "purchase_orders", "search": ["po_number", "vendor_name", "reference"],
                        "sort": ["po_number", "date", "status", "total"], "default_sort": ("date", -1)},
    "expenses": {"col": "expenses", "search": ["description", "category", "vendor_name", "reference"],
                 "sort": ["date", "amount", "category"], "default_sort": ("date", -1)},
    "items": {"col": "items", "search": ["name", "description", "sku"], "sort": ["name", "rate"],
              "default_sort": ("name", 1)},
}

PROTECTED = {"_id", "created_at", "backfill", "zoho_sync_history", "edit_history", "fills", "snapshot", "fingerprint",
             "version", "estimate_group_id", "is_latest", "superseded_by", "previous_version_id", "journal_entry_id",
             "ledger", "merged_into", "external_invoice_id"}
HEAVY = {"zoho_sync_history": 0, "snapshot": 0, "fills": 0, "edit_history": 0, "fingerprint": 0}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?$")


def _oid(v) -> Optional[ObjectId]:
    try:
        return ObjectId(str(v))
    except Exception:
        return None


def _kind(kind: str) -> Dict[str, Any]:
    if kind not in KINDS:
        raise KeyError(kind)
    return KINDS[kind]


def list_records(fin, kind: str, *, page=1, page_size=25, search=None, status=None, sort=None, order=None):
    k = _kind(kind)
    q: Dict[str, Any] = {"is_deleted": {"$ne": True}, **(k.get("base") or {})}
    if status:
        q["status"] = status
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        ors = [{f: rx} for f in k["search"]]
        if kind in ("estimates", "invoices", "payments_received"):        # by customer name too
            ids = [str(c["_id"]) for c in fin.customers.find({"name": rx}, {"_id": 1}).limit(200)]
            if ids:
                ors.append({"customer_id": {"$in": ids}})
        q["$or"] = ors
    by, direction = k["default_sort"]
    if sort in k["sort"]:
        by, direction = sort, (1 if order == "asc" else -1)
    col = fin[k["col"]]
    total = col.count_documents(q)
    rows = list(col.find(q, HEAVY).sort([(by, direction), ("_id", -1)]).skip((page - 1) * page_size).limit(page_size))
    _join(fin, kind, rows)
    return {"records": rows, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


def _join(fin, kind: str, rows: List[Dict[str, Any]]) -> None:
    cids = {_oid(r.get("customer_id")) for r in rows if r.get("customer_id")} - {None}
    if cids:
        names = {str(c["_id"]): c.get("name") for c in fin.customers.find({"_id": {"$in": list(cids)}}, {"name": 1})}
        for r in rows:
            if names.get(str(r.get("customer_id"))):
                r["customer_name"] = names[str(r.get("customer_id"))]
    if kind == "customers" and rows:
        ids = [str(r["_id"]) for r in rows]
        inv = {d["_id"]: d for d in fin.invoices.aggregate([
            {"$match": {"customer_id": {"$in": ids}, "is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$customer_id", "n": {"$sum": 1}, "due": {"$sum": {"$ifNull": ["$balance_due", 0]}}}}])}
        est = {d["_id"]: d["n"] for d in fin.estimates.aggregate([
            {"$match": {"customer_id": {"$in": ids}, "is_latest": {"$ne": False}, "archived_backlog": {"$ne": True}}},
            {"$group": {"_id": "$customer_id", "n": {"$sum": 1}}}])}
        for r in rows:
            i = inv.get(str(r["_id"])) or {}
            r.update(invoice_count=i.get("n", 0), balance_due_total=round(i.get("due", 0) or 0, 2),
                     estimate_count=est.get(str(r["_id"]), 0))


def get_record(fin, kind: str, rid: str) -> Optional[Dict[str, Any]]:
    k = _kind(kind)
    oid = _oid(rid)
    doc = fin[k["col"]].find_one({"_id": oid}, {"snapshot": 0, "fingerprint": 0}) if oid else None
    if not doc:
        return None
    _join(fin, kind, [doc])
    if kind == "customers":
        cid = str(doc["_id"])
        doc["invoices"] = list(fin.invoices.find({"customer_id": cid, "is_deleted": {"$ne": True}},
                                                 {"invoice_number": 1, "invoice_date": 1, "status": 1, "total": 1,
                                                  "balance_due": 1, "currency_code": 1}).sort("invoice_date", -1).limit(100))
        doc["estimates"] = list(fin.estimates.find({"customer_id": cid, "is_latest": {"$ne": False},
                                                    "archived_backlog": {"$ne": True}},
                                                   {"estimate_number": 1, "date": 1, "status": 1, "total_amount": 1,
                                                    "project_name": 1, "currency": 1}).sort("date", -1).limit(100))
    return doc


def _coerce(v):
    if isinstance(v, str) and ISO_DATE.match(v.strip()):
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "").replace(" ", "T"))
        except ValueError:
            return v
    return v


def update_record(fin, kind: str, rid: str, data: Dict[str, Any], *, actor: str = "user",
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    k = _kind(kind)
    now = now or datetime.utcnow()
    oid = _oid(rid)
    col = fin[k["col"]]
    doc = col.find_one({"_id": oid}) if oid else None
    if not doc:
        raise LookupError(rid)
    changes = {f: _coerce(v) for f, v in (data or {}).items()
               if f not in PROTECTED and not f.startswith("$") and "." not in f and doc.get(f) != _coerce(v)}
    for f in ("customer_name", "invoice_count", "estimate_count", "balance_due_total", "invoices", "estimates"):
        changes.pop(f, None)                               # joined for display, not stored
    if not changes:
        return {"changed": []}
    items = changes.get("items") or changes.get("line_items")
    if isinstance(items, list) and kind in ("estimates", "invoices", "bills", "purchase_orders"):
        for it in items:
            if isinstance(it, dict):
                qty, rate = float(it.get("quantity") or 0), float(it.get("rate") or it.get("unit_price") or 0)
                it["rate"] = it["unit_price"] = rate
                it["amount"] = round(qty * rate, 2)
        sub = round(sum(float(i.get("amount") or 0) for i in items if isinstance(i, dict)), 2)
        tax = float(changes.get("tax_amount", doc.get("tax_amount")) or 0)
        changes.update(items=items, line_items=items, subtotal=sub)
        total_key = "total_amount" if kind == "estimates" else "total"
        changes[total_key] = round(sub + tax, 2)
        if kind == "estimates":
            changes["total"] = changes["total_amount"]
    old = {f: doc.get(f) for f in changes}
    col.update_one({"_id": oid}, {"$set": {**changes, "updated_at": now},
                                  "$push": {"edit_history": {"at": now, "by": actor, "old": old}}})
    try:
        from platform_core.audit import log_action
        log_action(actor=actor, action="update", entity_type=kind.rstrip("s"), entity_id=rid,
                   reason="edited on the finance record page: " + ", ".join(sorted(changes)), source="finance_records")
    except Exception:
        pass
    return {"changed": sorted(changes)}
