"""
One-off seed: load a Zoho invoice export into finance_db.

Supports TWO export shapes (auto-detected from the header row):

  * DETAILED  ("Invoice.csv")  - the full Zoho export, one row per line item.
    Rich: explicit Currency Code, Customer ID, GSTIN, GST Treatment, SubTotal,
    Total, Balance, per-line items, tax breakdown, branch. PREFERRED.
  * SIMPLE    ("Invoices.csv") - one row per invoice, amounts carry currency
    glyphs (mojibake ₹ / €) and thousand separators. Fallback only.

What it does
------------
1. Reads the CSV (several encodings tried; Zoho double-encodes ₹/€ in the
   simple export, so the mojibake forms are accepted too).
2. Groups detailed rows by Invoice ID and aggregates their line items.
3. Auto-creates any customer not already in finance_db.customers, carrying
   GSTIN / GST treatment / Zoho id / currency when available.
4. Inserts one invoice per Zoho invoice into finance_db.invoices, setting every
   field the list UI / detail page read (total, total_amount, subtotal,
   tax_total, balance_due, amount_paid, currency_code, lowercased status,
   payment_status) plus items[], branch, po_reference, gstin, tds.
5. Idempotent: skips invoice numbers already present; refreshes each affected
   customer's total_receivables / total_paid.

Usage
-----
    python backend/seed_invoices_csv.py [path/to/export.csv] [--commit]

Without --commit it is a DRY RUN: parses everything, reports the plan, writes
nothing. Re-run with --commit to write.
"""

import os
import re
import sys
import csv
import io
import warnings
from collections import OrderedDict
from datetime import datetime

warnings.filterwarnings("ignore", category=DeprecationWarning)

from pymongo import MongoClient
from dotenv import load_dotenv

# --- config -----------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
load_dotenv(os.path.join(HERE, ".env"))

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    sys.exit("MONGO_URI not set (looked in backend/.env)")

# detailed export uses ISO dates; simple export uses dd/mm/yyyy
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"]


# --- small helpers ----------------------------------------------------------
def to_float(raw) -> float:
    """Best-effort float from a plain Zoho numeric cell."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", s)  # detailed export is already dot-decimal
    try:
        return float(s) if s not in ("", "-", ".", "-.") else 0.0
    except ValueError:
        return 0.0


def parse_money_glyph(raw: str):
    """SIMPLE export: detect currency from glyph and strip symbols/commas."""
    raw = (raw or "").strip()
    if not raw:
        return "INR", 0.0
    if "$" in raw:
        cur = "USD"
    elif "€" in raw or "¬" in raw or "â¬" in raw:   # euro / mojibake euro tail
        cur = "EUR"
    else:
        cur = "INR"                                  # rupee ₹ / mojibake â¹
    num = re.sub(r"[^0-9.,-]", "", raw)
    if cur == "EUR":                                 # 1.234,56  -> 1234.56
        num = num.replace(".", "").replace(",", ".")
    else:                                            # 1,234.56  -> 1234.56
        num = num.replace(",", "")
    try:
        return cur, float(num or 0)
    except ValueError:
        return cur, 0.0


def parse_date(raw):
    raw = (raw or "").strip()
    if not raw or raw == "1970-01-01":
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def read_rows(path: str):
    with open(path, "rb") as fh:
        contents = fh.read()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            decoded = contents.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = contents.decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(decoded)))


def derive_status(zoho_status: str, balance: float) -> str:
    z = (zoho_status or "").strip().lower()
    if z == "draft":
        return "draft"
    if balance <= 0.005:
        return "paid"
    if z == "overdue":
        return "overdue"
    return "sent"            # Open / Sent / Closed-with-balance


def payment_status(total: float, balance: float) -> str:
    if balance <= 0.005:
        return "paid"
    if balance < total:
        return "partial"
    return "unpaid"


# --- normalisation: both shapes -> list of invoice dicts --------------------
def parse_detailed(rows):
    """Group line-item rows by Invoice ID into one normalised invoice each."""
    groups = OrderedDict()
    for r in rows:
        inv_id = (r.get("Invoice ID") or "").strip()
        key = inv_id or (r.get("Invoice Number") or "").strip()
        groups.setdefault(key, []).append(r)

    invoices = []
    for key, grp in groups.items():
        head = grp[0]
        total = to_float(head.get("Total"))
        balance = to_float(head.get("Balance"))
        cur = (head.get("Currency Code") or "INR").strip() or "INR"

        items, tax_total = [], 0.0
        for r in grp:
            name = (r.get("Item Name") or "").strip()
            desc = (r.get("Item Desc") or "").strip()
            amt = to_float(r.get("Item Total"))
            if not name and not desc and amt == 0:
                continue
            items.append({
                "name": name or (desc[:60] if desc else "Item"),
                "description": desc,
                "quantity": to_float(r.get("Quantity")) or 1,
                "rate": to_float(r.get("Item Price")),
                "amount": amt,
                "hsn_sac": (r.get("HSN/SAC") or "").strip(),
                "tax_percent": to_float(r.get("Item Tax %")),
                "tax_amount": to_float(r.get("Item Tax Amount")),
            })
            tax_total += (to_float(r.get("CGST")) + to_float(r.get("SGST"))
                          + to_float(r.get("IGST")))

        invoices.append({
            "invoice_number": (head.get("Invoice Number") or "").strip(),
            "zoho_invoice_id": key,
            "customer_name": (head.get("Customer Name") or "").strip(),
            "customer_zoho_id": (head.get("Customer ID") or "").strip(),
            "gstin": (head.get("GST Identification Number (GSTIN)") or "").strip(),
            "gst_treatment": (head.get("GST Treatment") or "").strip(),
            "invoice_date": parse_date(head.get("Invoice Date")),
            "due_date": parse_date(head.get("Due Date")),
            "currency": cur,
            "subtotal": to_float(head.get("SubTotal")),
            "tax_total": round(tax_total, 2),
            "total": total,
            "balance": balance,
            "tds_amount": to_float(head.get("TDS Amount")),
            "status": derive_status(head.get("Invoice Status"), balance),
            "branch": (head.get("Branch Name") or "").strip(),
            "po_reference": (head.get("PurchaseOrder") or "").strip(),
            "notes": (head.get("Subject") or head.get("Notes") or "").strip()[:500],
            "items": items,
        })
    return invoices


def parse_simple(rows):
    invoices = []
    for r in rows:
        cur, total = parse_money_glyph(r.get("Amount", ""))
        _, balance = parse_money_glyph(r.get("Balance Due", ""))
        invoices.append({
            "invoice_number": (r.get("Invoice#") or "").strip(),
            "zoho_invoice_id": (r.get("INVOICE_ID") or "").strip(),
            "customer_name": (r.get("Customer Name") or "").strip(),
            "customer_zoho_id": "",
            "gstin": "",
            "gst_treatment": "",
            "invoice_date": parse_date(r.get("Date")),
            "due_date": parse_date(r.get("Due Date")),
            "currency": cur,
            "subtotal": total,
            "tax_total": 0.0,
            "total": total,
            "balance": balance,
            "tds_amount": 0.0,
            "status": derive_status(r.get("Status"), balance),
            "branch": (r.get("Branch") or "").strip(),
            "po_reference": (r.get("Order Number") or "").strip(),
            "notes": "",
            "items": [],
        })
    return invoices


def normalise(rows):
    fields = set(rows[0].keys()) if rows else set()
    if {"Invoice ID", "Total", "Currency Code"} <= fields:
        return parse_detailed(rows), "DETAILED"
    if {"Invoice#", "Amount"} <= fields:
        return parse_simple(rows), "SIMPLE"
    sys.exit(f"Unrecognised CSV header. Columns seen: {sorted(fields)[:8]} ...")


# --- main -------------------------------------------------------------------
def find_csv(args):
    if args:
        return args[0]
    for name in ("Invoice.csv", "Invoices.csv"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "Invoice.csv")


def main():
    argv = sys.argv[1:]
    commit = "--commit" in argv
    offline = "--offline" in argv
    argv = [a for a in argv if a not in ("--commit", "--offline")]
    csv_path = find_csv(argv)

    if not os.path.exists(csv_path):
        sys.exit(f"CSV not found: {csv_path}\n"
                 f"Save the Zoho export there, or pass a path as the first argument.")

    rows = read_rows(csv_path)
    invoices, shape = normalise(rows)
    print(f"Read {len(rows)} rows from {csv_path}  (format: {shape})")
    print(f"Parsed {len(invoices)} invoices")
    mode = "OFFLINE PARSE-ONLY (no DB)" if offline else \
           ("COMMIT" if commit else "DRY RUN (no writes)")
    print(f"Mode: {mode}\n")

    if offline:
        customers_col = invoices_col = None
        existing_customers, max_num = {}, 0
    else:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        finance_db = client["finance_db"]
        customers_col = finance_db["customers"]
        invoices_col = finance_db["invoices"]
        # --- customers: existing map + plan new ---
        existing_customers = {c["name"]: str(c["_id"])
                              for c in customers_col.find({}, {"name": 1})}
        max_num = 0
        for c in customers_col.find({"customer_number": {"$regex": r"^CUST-\d+$"}},
                                    {"customer_number": 1}):
            try:
                max_num = max(max_num, int(c["customer_number"].split("-")[1]))
            except (ValueError, IndexError):
                pass

    # first-seen metadata per new customer
    meta = {}
    order = []
    for inv in invoices:
        name = inv["customer_name"]
        if not name or name in existing_customers:
            continue
        if name not in meta:
            order.append(name)
            meta[name] = {"currency": inv["currency"], "gstin": inv["gstin"],
                          "gst_treatment": inv["gst_treatment"],
                          "zoho_id": inv["customer_zoho_id"]}
        elif inv["gstin"] and not meta[name]["gstin"]:
            meta[name]["gstin"] = inv["gstin"]

    print(f"Customers: {len(existing_customers)} existing, {len(order)} to create")
    for n in order:
        m = meta[n]
        print(f"   + {n}  ({m['currency']}{', GSTIN ' + m['gstin'] if m['gstin'] else ''})")

    if commit and order:
        docs = []
        for i, name in enumerate(order, start=1):
            m = meta[name]
            docs.append({
                "name": name,
                "customer_number": f"CUST-{str(max_num + i).zfill(5)}",
                "customer_type": "business",
                "company_name": name,
                "currency": m["currency"],
                "currency_code": m["currency"],
                "gstin": m["gstin"],
                "gst_treatment": m["gst_treatment"] or "unregistered",
                "zoho_customer_id": m["zoho_id"],
                "status": "active",
                "total_receivables": 0,
                "total_paid": 0,
                "notes": "Auto-created from Zoho invoice import",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })
        res = customers_col.insert_many(docs, ordered=False)
        for name, _id in zip(order, res.inserted_ids):
            existing_customers[name] = str(_id)
        print(f"   inserted {len(res.inserted_ids)} customers")
    else:
        for i, name in enumerate(order, start=1):
            existing_customers[name] = f"<new#{i}>"

    # --- invoices ---
    existing_numbers = set() if offline else {
        d["invoice_number"]
        for d in invoices_col.find({}, {"invoice_number": 1})
        if d.get("invoice_number")}

    docs, skipped, errors, seen = [], [], [], set()
    recv, paid = {}, {}

    for inv in invoices:
        try:
            name = inv["customer_name"]
            if not name:
                errors.append(f"{inv['zoho_invoice_id']}: missing customer")
                continue
            num = inv["invoice_number"]
            if num and (num in existing_numbers or num in seen):
                skipped.append(num)
                continue
            if num:
                seen.add(num)

            total, balance = inv["total"], inv["balance"]
            amount_paid = round(total - balance, 2)
            docs.append({
                "invoice_number": num,
                "customer_id": existing_customers.get(name),
                "customer_zoho_id": inv["customer_zoho_id"],
                "invoice_date": inv["invoice_date"] or datetime.utcnow(),
                "due_date": inv["due_date"],
                "currency_code": inv["currency"],
                "currency": inv["currency"],
                "items": inv["items"],
                "subtotal": inv["subtotal"],
                "tax_total": inv["tax_total"],
                "tax_amount": inv["tax_total"],
                "tds_amount": inv["tds_amount"],
                "discount_type": "flat",
                "discount_value": 0.0,
                "total": total,
                "total_amount": total,
                "balance_due": balance,
                "amount_paid": amount_paid,
                "status": inv["status"],
                "payment_status": payment_status(total, balance),
                "gstin": inv["gstin"],
                "gst_treatment": inv["gst_treatment"],
                "po_reference": inv["po_reference"],
                "branch": inv["branch"],
                "external_invoice_id": inv["zoho_invoice_id"],
                "notes": inv["notes"] or "Imported from Zoho export",
                "is_deleted": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })
            recv[name] = recv.get(name, 0) + balance
            paid[name] = paid.get(name, 0) + amount_paid
        except Exception as e:  # noqa: BLE001
            errors.append(f"{inv.get('zoho_invoice_id')}: {e}")

    print(f"\nInvoices: {len(docs)} to insert, {len(skipped)} skipped "
          f"(already present), {len(errors)} errors")
    for e in errors[:20]:
        print(f"   ! {e}")

    if commit and docs:
        res = invoices_col.insert_many(docs, ordered=False)
        print(f"   inserted {len(res.inserted_ids)} invoices")
        for name in set(list(recv) + list(paid)):
            cid = existing_customers.get(name)
            if not cid or cid.startswith("<new"):
                continue
            customers_col.update_one(
                {"name": name},
                {"$inc": {"total_receivables": round(recv.get(name, 0), 2),
                          "total_paid": round(paid.get(name, 0), 2)},
                 "$set": {"updated_at": datetime.utcnow()}})
        print("   updated customer receivable/paid totals")

    # --- summary by currency ---
    by_cur = {}
    for d in docs:
        c = d["currency_code"]
        by_cur.setdefault(c, [0, 0.0, 0.0])
        by_cur[c][0] += 1
        by_cur[c][1] += d["total"]
        by_cur[c][2] += d["balance_due"]
    print("\nTotals by currency (planned):")
    for c, (n, tot, bal) in sorted(by_cur.items()):
        print(f"   {c}: {n} invoices, total {tot:,.2f}, outstanding {bal:,.2f}")

    if not commit:
        print("\nDRY RUN complete - re-run with --commit to write.")


if __name__ == "__main__":
    main()
