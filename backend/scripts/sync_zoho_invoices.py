"""Bring finance_db.invoices in line with a Zoho invoice export (owner, 2026-10-26).

    venv/bin/python scripts/sync_zoho_invoices.py EXPORT.csv            # dry run
    venv/bin/python scripts/sync_zoho_invoices.py EXPORT.csv --apply    # needs a mongodump < 3 h old

seed_invoices_csv.py inserts invoices it has not seen; this updates the ones it
has: status, balance due, amount paid, payment status, order number (client
PO / reference) and branch, matched on the Zoho INVOICE_ID, else invoice number.

Kept as Torpedo decided, reported, never overwritten:
  written_off      (e.g. Rerez, written off 2026-10-02) -- Zoho still says Overdue
  void / cancelled
Flagged: invoices billed to one of our own companies (inter-company), so they
are not chased as client receivables. Every change keeps the old value in
zoho_sync_history. Nothing is deleted; a Draft in Zoho never replaces a real
status here.
"""
import argparse
import glob
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OWN_COMPANIES = re.compile(r"cogentix\s+research|survey\s*fieldwork|bim\s*wave", re.I)
KEEP_LOCAL = {"written_off", "void", "cancelled"}
FIELDS = ("status", "balance_due", "amount_paid", "payment_status", "po_reference", "branch")


def backup_age_hours(d="/var/www/campaign_platform/backups") -> float:
    dumps = sorted(glob.glob(os.path.join(d, "*", "full.archive.gz")))
    return (time.time() - os.path.getmtime(dumps[-1])) / 3600 if dumps else float("inf")


def zoho_fields(z):
    import seed_invoices_csv as seed
    total, bal = float(z["total"] or 0), float(z["balance"] or 0)
    return {"status": z["status"], "balance_due": round(bal, 2), "amount_paid": round(max(total - bal, 0), 2),
            "payment_status": seed.payment_status(total, bal), "po_reference": z["po_reference"] or None,
            "branch": z["branch"] or None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply and backup_age_hours() > 3:
        sys.exit("refusing to apply: newest mongodump is older than 3 h")
    import seed_invoices_csv as seed
    from database import get_database
    fin = get_database("finance_db")
    zoho, _fmt = seed.normalise(seed.read_rows(a.csv))
    now = datetime.utcnow()
    counts, samples = Counter(), {}
    for z in zoho:
        inv = (fin["invoices"].find_one({"external_invoice_id": z["zoho_invoice_id"]}) if z["zoho_invoice_id"] else None) \
            or fin["invoices"].find_one({"invoice_number": z["invoice_number"]})
        if not inv:
            counts["not_in_torpedo (seed_invoices_csv inserts these)"] += 1
            continue
        want = zoho_fields(z)
        upd = {}
        if OWN_COMPANIES.search(z["customer_name"] or "") and not inv.get("intercompany"):
            upd["intercompany"] = True
            counts["flagged inter-company"] += 1
            samples.setdefault("intercompany", []).append(f"{z['invoice_number']} {z['customer_name']} {z['total']:,.2f}")
        local = (inv.get("status") or "").lower()
        if local in KEEP_LOCAL:
            if want["status"] != local:
                counts[f"kept local {local} (Zoho says {want['status']})"] += 1
            want = {k: v for k, v in want.items() if k in ("po_reference", "branch")}
        if want.get("status") == "draft" and local not in ("", "draft"):
            want.pop("status", None)
        changes = {k: v for k, v in want.items() if v is not None and inv.get(k) != v}
        # fill-only: invoices created here as drafts can lack the dates/amounts Zoho has
        for k, v in (("due_date", z["due_date"]), ("invoice_date", z["invoice_date"]), ("total", z["total"]),
                     ("total_amount", z["total"]), ("currency_code", z["currency"])):
            if v not in (None, "") and inv.get(k) in (None, "", 0):
                changes[k] = v
        if not changes and not upd:
            counts["unchanged"] += 1
            continue
        for k in changes:
            counts[f"changed {k}"] += 1
        if "status" in changes:
            key = f"{inv.get('status')} -> {changes['status']}"
            counts[f"status {key}"] += 1
            samples.setdefault(key, [])
            if len(samples[key]) < 6:
                samples[key].append(f"{z['invoice_number']} {z['customer_name'][:30]} balance {want.get('balance_due')}")
        if a.apply:
            hist = {"at": now, "source": os.path.basename(a.csv), "old": {k: inv.get(k) for k in changes}}
            fin["invoices"].update_one({"_id": inv["_id"]}, {"$set": {**changes, **upd, "zoho_synced_at": now, "updated_at": now},
                                                             "$push": {"zoho_sync_history": hist}})
    print(f"{'APPLIED' if a.apply else 'DRY RUN'}: {len(zoho)} invoices in the export")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5}  {k}")
    for k, ss in samples.items():
        print(f"-- {k}")
        for s in ss:
            print("    ", s)


if __name__ == "__main__":
    main()
