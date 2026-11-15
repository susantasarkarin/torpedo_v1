"""
One-off seed: load a Zoho bills (accounts-payable) export into finance_db.

Consumes the detailed Zoho "Bill.csv" export (one row per line item). Groups
rows by Bill ID, aggregates line items, auto-creates any missing vendor (with
GSTIN / GST treatment / currency), and inserts one bill per Zoho bill into
finance_db.bills with every field the Bills UI reads (total_amount, subtotal,
tax_total, balance_due, amount_paid, currency_code, lowercased status). The
list page resolves vendor_name via a $lookup on vendor_id, so vendors must
exist first (handled here).

Idempotent: skips bill numbers already present (per vendor); refreshes each
affected vendor's total_payables / total_paid.

Usage
-----
    python backend/seed_bills_csv.py [path/to/Bill.csv] [--offline|--commit]

--offline : parse preview, no DB.   (default) : dry run.   --commit : write.
"""

import os
import re
import sys
import csv
import io
import warnings
from collections import OrderedDict
from datetime import datetime

from pymongo import MongoClient
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
load_dotenv(os.path.join(HERE, ".env"))

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    sys.exit("MONGO_URI not set (looked in backend/.env)")

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"]


def to_float(raw) -> float:
    if raw is None:
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", str(raw).strip())
    try:
        return float(s) if s not in ("", "-", ".", "-.") else 0.0
    except ValueError:
        return 0.0


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


def derive_status(zoho_status: str, balance: float, total: float) -> str:
    z = (zoho_status or "").strip().lower()
    if balance <= 0.005:
        return "paid"
    if z == "overdue":
        return "overdue"
    if 0 < balance < total:
        return "partial"
    return "pending"          # Open / Sent


def parse_bills(rows):
    """Group line-item rows by Bill ID into one normalised bill each."""
    groups = OrderedDict()
    for r in rows:
        bid = (r.get("Bill ID") or "").strip()
        key = bid or (r.get("Bill Number") or "").strip()
        groups.setdefault(key, []).append(r)

    bills = []
    for key, grp in groups.items():
        head = grp[0]
        total = to_float(head.get("Total"))
        balance = to_float(head.get("Balance"))
        cur = (head.get("Currency Code") or "INR").strip() or "INR"

        items, tax_total = [], 0.0
        for r in grp:
            name = (r.get("Item Name") or "").strip()
            desc = (r.get("Description") or "").strip()
            amt = to_float(r.get("Item Total"))
            if not name and not desc and amt == 0:
                continue
            items.append({
                "name": name or (r.get("Account") or "").strip() or "Item",
                "description": desc,
                "account": (r.get("Account") or "").strip(),
                "quantity": to_float(r.get("Quantity")) or 1,
                "rate": to_float(r.get("Rate")) or amt,
                "amount": amt,
                "hsn_sac": (r.get("HSN/SAC") or "").strip(),
                "tax_percent": to_float(r.get("Tax Percentage")),
                "tax_amount": to_float(r.get("Tax Amount")),
            })
            tax_total += (to_float(r.get("CGST")) + to_float(r.get("SGST"))
                          + to_float(r.get("IGST")))

        bills.append({
            "bill_number": (head.get("Bill Number") or "").strip(),
            "zoho_bill_id": key,
            "vendor_name": (head.get("Vendor Name") or "").strip(),
            "gstin": (head.get("GST Identification Number (GSTIN)") or "").strip(),
            "gst_treatment": (head.get("GST Treatment") or "").strip(),
            "bill_date": parse_date(head.get("Bill Date")),
            "due_date": parse_date(head.get("Due Date")),
            "currency": cur,
            "subtotal": to_float(head.get("SubTotal")),
            "tax_total": round(tax_total, 2),
            "total": total,
            "balance": balance,
            "status": derive_status(head.get("Bill Status"), balance, total),
            "branch": (head.get("Branch Name") or "").strip(),
            "po_reference": (head.get("PurchaseOrder") or "").strip(),
            "notes": (head.get("Vendor Notes") or "").strip()[:500],
            "items": items,
        })
    return bills


def main():
    argv = sys.argv[1:]
    commit = "--commit" in argv
    offline = "--offline" in argv
    argv = [a for a in argv if a not in ("--commit", "--offline")]
    csv_path = argv[0] if argv else os.path.join(ROOT, "Bill.csv")

    if not os.path.exists(csv_path):
        sys.exit(f"CSV not found: {csv_path}\n"
                 f"Save the Zoho Bill.csv export there, or pass a path.")

    rows = read_rows(csv_path)
    fields = set(rows[0].keys()) if rows else set()
    if not {"Bill ID", "Total", "Vendor Name"} <= fields:
        sys.exit(f"Unrecognised bills CSV header. Columns: {sorted(fields)[:8]} ...")

    bills = parse_bills(rows)
    print(f"Read {len(rows)} rows from {csv_path}")
    print(f"Parsed {len(bills)} bills")
    mode = "OFFLINE PARSE-ONLY (no DB)" if offline else \
           ("COMMIT" if commit else "DRY RUN (no writes)")
    print(f"Mode: {mode}\n")

    if offline:
        vendors_col = bills_col = None
        existing_vendors, max_num = {}, 0
    else:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        finance_db = client["finance_db"]
        vendors_col = finance_db["vendors"]
        bills_col = finance_db["bills"]
        existing_vendors = {v["name"]: str(v["_id"])
                            for v in vendors_col.find({}, {"name": 1})}
        max_num = 0
        for v in vendors_col.find({"vendor_number": {"$regex": r"^VEND-\d+$"}},
                                  {"vendor_number": 1}):
            try:
                max_num = max(max_num, int(v["vendor_number"].split("-")[1]))
            except (ValueError, IndexError):
                pass

    # plan new vendors (first-seen metadata)
    meta, order = {}, []
    for b in bills:
        name = b["vendor_name"]
        if not name or name in existing_vendors:
            continue
        if name not in meta:
            order.append(name)
            meta[name] = {"currency": b["currency"], "gstin": b["gstin"],
                          "gst_treatment": b["gst_treatment"]}
        elif b["gstin"] and not meta[name]["gstin"]:
            meta[name]["gstin"] = b["gstin"]

    print(f"Vendors: {len(existing_vendors)} existing, {len(order)} to create")
    for n in order:
        m = meta[n]
        print(f"   + {n}  ({m['currency']}{', GSTIN ' + m['gstin'] if m['gstin'] else ''})")

    if commit and order:
        docs = []
        for i, name in enumerate(order, start=1):
            m = meta[name]
            docs.append({
                "name": name,
                "vendor_number": f"VEND-{str(max_num + i).zfill(5)}",
                "vendor_type": "supplier",
                "company_name": name,
                "currency": m["currency"],
                "currency_code": m["currency"],
                "gstin": m["gstin"],
                "gst_treatment": m["gst_treatment"] or "unregistered",
                "status": "active",
                "total_payables": 0,
                "total_paid": 0,
                "notes": "Auto-created from Zoho bill import",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })
        res = vendors_col.insert_many(docs, ordered=False)
        for name, _id in zip(order, res.inserted_ids):
            existing_vendors[name] = str(_id)
        print(f"   inserted {len(res.inserted_ids)} vendors")
    else:
        for i, name in enumerate(order, start=1):
            existing_vendors[name] = f"<new#{i}>"

    # bills
    existing_numbers = set() if offline else {
        d["bill_number"] for d in bills_col.find({}, {"bill_number": 1})
        if d.get("bill_number")}

    docs, skipped, errors, seen = [], [], [], set()
    pay, paid = {}, {}

    for b in bills:
        try:
            name = b["vendor_name"]
            if not name:
                errors.append(f"{b['zoho_bill_id']}: missing vendor")
                continue
            num = b["bill_number"]
            dedupe_key = f"{name}|{num}"
            if num and (dedupe_key in seen or
                        (num in existing_numbers and name in existing_vendors)):
                skipped.append(num)
                continue
            if num:
                seen.add(dedupe_key)

            total, balance = b["total"], b["balance"]
            amount_paid = round(total - balance, 2)
            docs.append({
                "bill_number": num,
                "vendor_id": existing_vendors.get(name),
                "bill_date": b["bill_date"] or datetime.utcnow(),
                "due_date": b["due_date"],
                "currency_code": b["currency"],
                "currency": b["currency"],
                "items": b["items"],
                "subtotal": b["subtotal"],
                "tax_total": b["tax_total"],
                "tax_amount": b["tax_total"],
                "total": total,
                "total_amount": total,
                "balance_due": balance,
                "amount_paid": amount_paid,
                "status": b["status"],
                "gstin": b["gstin"],
                "gst_treatment": b["gst_treatment"],
                "po_reference": b["po_reference"],
                "branch": b["branch"],
                "external_bill_id": b["zoho_bill_id"],
                "notes": b["notes"] or "Imported from Zoho Bill.csv",
                "is_deleted": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })
            pay[name] = pay.get(name, 0) + balance
            paid[name] = paid.get(name, 0) + amount_paid
        except Exception as e:  # noqa: BLE001
            errors.append(f"{b.get('zoho_bill_id')}: {e}")

    print(f"\nBills: {len(docs)} to insert, {len(skipped)} skipped "
          f"(already present), {len(errors)} errors")
    for e in errors[:20]:
        print(f"   ! {e}")

    if commit and docs:
        res = bills_col.insert_many(docs, ordered=False)
        print(f"   inserted {len(res.inserted_ids)} bills")
        for name in set(list(pay) + list(paid)):
            vid = existing_vendors.get(name)
            if not vid or vid.startswith("<new"):
                continue
            vendors_col.update_one(
                {"name": name},
                {"$inc": {"total_payables": round(pay.get(name, 0), 2),
                          "total_paid": round(paid.get(name, 0), 2)},
                 "$set": {"updated_at": datetime.utcnow()}})
        print("   updated vendor payable/paid totals")

    by_cur = {}
    for d in docs:
        c = d["currency_code"]
        by_cur.setdefault(c, [0, 0.0, 0.0])
        by_cur[c][0] += 1
        by_cur[c][1] += d["total"]
        by_cur[c][2] += d["balance_due"]
    print("\nTotals by currency (planned):")
    for c, (n, tot, bal) in sorted(by_cur.items()):
        print(f"   {c}: {n} bills, total {tot:,.2f}, outstanding {bal:,.2f}")

    if not commit:
        print("\nDRY RUN complete - re-run with --commit to write.")


if __name__ == "__main__":
    main()
