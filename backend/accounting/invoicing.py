"""Quotation / invoice / credit note rules and their journal postings (CRM
plan 3.9 steps 1-8). Pure.

Tax values are config (accounting section) because they are the CA's call:
gst_rate defaults to 18% and every rate/section is shown on the CA pack. An
entity without a GSTIN, or a client without a determinable place of supply,
is blocked rather than guessed. Issued invoices are never edited: changes are
credit notes.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from accounting import ledger

DEFAULTS: Dict[str, Any] = {
    "gst_rate": 0.18,                      # CA to confirm (SAC 998371 market research)
    "lut_for_exports": True,               # export of services under LUT: zero-rated
    "invoice_variance_review_pct": 0.05,   # invoice vs quotation > 5% -> Review Queue
    "quotation_validity_days": 30,
    "upcoming_window_days": 7,
    "overdue_mail_every_days": 14,
    "credit_hold_after_days": 60,
    "tds_sections": {},                    # owner/CA: {"194C": 0.02, "194J": 0.10} -- blank = vendor payment to review
    "client_tds_rates": [0.02, 0.10],      # rates clients may deduct (receipt = invoice - TDS)
}


def financial_year(d: date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def next_number(prefix: str, kind: str, d: date, existing: List[str]) -> str:
    """<prefix>-<INV|QT|CN>-<FY>-<seq 4>, per entity series and financial year."""
    head = f"{prefix}-{kind}-{financial_year(d)}-"
    seq = max([int(n[len(head):]) for n in existing if n.startswith(head) and n[len(head):].isdigit()] or [0])
    return f"{head}{seq + 1:04d}"


def state_code(gstin: Optional[str]) -> Optional[str]:
    g = (gstin or "").strip()
    return g[:2] if len(g) >= 2 and g[:2].isdigit() else None


def gst_split(taxable: float, *, entity_gstin: str, client_country: str, client_gstin: Optional[str] = None,
              client_state_code: Optional[str] = None, cfg=DEFAULTS) -> Dict[str, Any]:
    """CGST+SGST inside the entity's state, IGST across states, LUT (zero) for
    clients outside India. Returns {'blocked': reason} when it cannot tell."""
    own = state_code(entity_gstin)
    if not own:
        return {"blocked": "entity GSTIN not set (owner)"}
    if (client_country or "").upper() not in ("IN", "INDIA"):
        if cfg["lut_for_exports"]:
            return {"type": "export_lut", "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "tax": 0.0,
                    "note": "Supply meant for export under LUT without payment of IGST"}
        tax = round(taxable * cfg["gst_rate"], 2)
        return {"type": "export_igst", "cgst": 0.0, "sgst": 0.0, "igst": tax, "tax": tax}
    pos = state_code(client_gstin) or client_state_code
    if not pos:
        return {"blocked": "client place of supply unknown (no GSTIN or state)"}
    if pos == own:
        half = round(taxable * cfg["gst_rate"] / 2, 2)
        return {"type": "intra", "cgst": half, "sgst": half, "igst": 0.0, "tax": round(2 * half, 2)}
    tax = round(taxable * cfg["gst_rate"], 2)
    return {"type": "inter", "cgst": 0.0, "sgst": 0.0, "igst": tax, "tax": tax}


def invoice_amount(*, accepted_completes: int, cpi: float, change_orders: List[Dict[str, Any]] = (),
                   fees: List[Dict[str, Any]] = (), discounts: List[Dict[str, Any]] = (),
                   already_billed: float = 0.0) -> Dict[str, Any]:
    """reconciled completes x CPI + change orders + fees - discounts, less any
    partial invoice already raised on the project."""
    base = round(accepted_completes * float(cpi), 2)
    co = round(sum(float(c.get("amount") or 0) for c in change_orders), 2)
    fe = round(sum(float(f.get("amount") or 0) for f in fees), 2)
    di = round(sum(float(d.get("amount") or 0) for d in discounts), 2)
    return {"base": base, "change_orders": co, "fees": fe, "discounts": di, "already_billed": round(already_billed, 2),
            "taxable": round(base + co + fe - di - already_billed, 2)}


def due_date(issued: date, payment_terms_days: Optional[int]) -> date:
    return issued + timedelta(days=int(payment_terms_days if payment_terms_days is not None else 30))


def invoice_checks(*, taxable: float, quotation_total: Optional[float], account: Dict[str, Any],
                   po_number: Optional[str], cfg=DEFAULTS) -> Dict[str, Any]:
    hold, review = [], []
    if account.get("requires_po") and not po_number:
        hold.append("PO number required by this account")
    if quotation_total:
        v = abs(taxable - quotation_total) / quotation_total
        if v > cfg["invoice_variance_review_pct"]:
            review.append(f"invoice {taxable} differs from quotation {quotation_total} by {v:.0%}")
    if taxable <= 0:
        review.append("nothing to bill")
    return {"hold": hold, "review": review, "send": not hold and not review}


def credit_note(invoice: Dict[str, Any], rejected_completes: int, cpi: float, reason: str) -> Dict[str, Any]:
    """Post-invoice rejections: a new document against the invoice, same tax split."""
    taxable = round(rejected_completes * float(cpi), 2)
    inv_taxable = float(invoice["taxable"]) or 1
    ratio = taxable / inv_taxable
    tax = {k: round(float((invoice.get("gst") or {}).get(k) or 0) * ratio, 2) for k in ("cgst", "sgst", "igst")}
    return {"against_invoice": invoice["number"], "taxable": taxable, "gst": {**tax, "tax": round(sum(tax.values()), 2)},
            "total": round(taxable + sum(tax.values()), 2), "reason": reason, "currency": invoice.get("currency")}


# ---------------------------------------------------------------- postings (INR books)


def _gst_lines(gst: Dict[str, Any], fx: float, side: str) -> List[Dict[str, Any]]:
    out = []
    for k, acct in (("cgst", "2100"), ("sgst", "2110"), ("igst", "2120")):
        v = round(float(gst.get(k) or 0) * fx, 2)
        if v:
            out.append({"account": acct, side: v})
    return out


def post_invoice(inv: Dict[str, Any], entity: str, fx: float = 1.0) -> Dict[str, Any]:
    rev = "4000" if inv.get("service_type", "data") == "data" else "4100"
    taxable = round(float(inv["taxable"]) * fx, 2)
    gl = _gst_lines(inv.get("gst") or {}, fx, "credit")
    total = round(taxable + sum(l["credit"] for l in gl), 2)
    return ledger.entry(entity=entity, on=inv["date"], memo=f"Invoice {inv['number']}",
                        lines=[{"account": "1100", "debit": total, "party": inv.get("customer_id")},
                               {"account": rev, "credit": taxable}] + gl,
                        source={"type": "invoice", "id": inv["number"]}, currency=inv.get("currency", "INR"),
                        fx_rate=fx if fx != 1.0 else None)


def post_credit_note(cn: Dict[str, Any], entity: str, on: date, number: str, fx: float = 1.0) -> Dict[str, Any]:
    taxable = round(float(cn["taxable"]) * fx, 2)
    gl = _gst_lines(cn.get("gst") or {}, fx, "debit")
    total = round(taxable + sum(l["debit"] for l in gl), 2)
    return ledger.entry(entity=entity, on=on, memo=f"Credit note {number} against {cn['against_invoice']}",
                        lines=[{"account": "4000", "debit": taxable}] + gl + [{"account": "1100", "credit": total}],
                        source={"type": "credit_note", "id": number})


def post_receipt(*, entity: str, on: date, invoice_number: str, ar_settled: float, received: float,
                 tds: float = 0.0, bank_charges: float = 0.0, party: Optional[str] = None) -> Dict[str, Any]:
    """Clears ar_settled (book INR) from receivables: bank + client TDS (a
    receivable from the department, never a short payment) + bank charges;
    whatever is left is FX loss (positive) or gain (negative)."""
    lines = [{"account": "1000", "debit": round(received, 2)}]
    if tds:
        lines.append({"account": "1150", "debit": round(tds, 2)})
    if bank_charges:
        lines.append({"account": "6000", "debit": round(bank_charges, 2)})
    fx = round(ar_settled - received - tds - bank_charges, 2)
    if fx > 0:
        lines.append({"account": "4900", "debit": fx})
    elif fx < 0:
        lines.append({"account": "4900", "credit": -fx})
    lines.append({"account": "1100", "credit": round(ar_settled, 2), "party": party})
    return ledger.entry(entity=entity, on=on, memo=f"Receipt against {invoice_number}", lines=lines,
                        source={"type": "receipt", "id": invoice_number})


def vendor_bill_tds(amount: float, section: Optional[str], cfg=DEFAULTS) -> Dict[str, Any]:
    rate = (cfg.get("tds_sections") or {}).get(section or "")
    if rate is None:
        return {"review": f"no TDS rate configured for section {section!r} (CA/owner)"}
    tds = round(amount * float(rate), 2)
    return {"section": section, "rate": rate, "tds": tds, "net_payable": round(amount - tds, 2)}


def post_vendor_bill(*, entity: str, on: date, bill_no: str, taxable: float, input_gst: float, tds: float,
                     vendor_id: str, cost_account: str = "5000") -> Dict[str, Any]:
    lines = [{"account": cost_account, "debit": round(taxable, 2)}]
    if input_gst:
        lines.append({"account": "1200", "debit": round(input_gst, 2)})
    if tds:
        lines.append({"account": "2200", "credit": round(tds, 2)})
    lines.append({"account": "2000", "credit": round(taxable + input_gst - tds, 2), "party": vendor_id})
    return ledger.entry(entity=entity, on=on, memo=f"Vendor bill {bill_no}", lines=lines,
                        source={"type": "vendor_bill", "id": bill_no})


def post_incentives(*, entity: str, on: date, month: str, amount: float) -> Dict[str, Any]:
    return ledger.entry(entity=entity, on=on, memo=f"Panel incentives {month}",
                        lines=[{"account": "5100", "debit": round(amount, 2)}, {"account": "2300", "credit": round(amount, 2)}],
                        source={"type": "incentives", "id": month})


# ---------------------------------------------------------------- receivables (consolidated per contact)


def _open(inv) -> bool:
    return inv.get("status") not in ("paid", "void", "draft") and float(inv.get("balance_due") or 0) > 0


def receivable_mails(invoices: List[Dict[str, Any]], today: date, *, last_overdue_mail: Dict[str, date],
                     cfg=DEFAULTS) -> Dict[str, Any]:
    """Weekly upcoming (Mondays), overdue every 14 days per contact, and the
    >60-day escalation + credit hold per account."""
    up: Dict[str, list] = {}
    over: Dict[str, list] = {}
    hold = set()
    for inv in invoices:
        if not _open(inv) or not inv.get("contact_email"):
            continue
        due = inv["due_date"].date() if isinstance(inv["due_date"], datetime) else inv["due_date"]
        days = (today - due).days
        if days > 0:
            over.setdefault(inv["contact_email"], []).append({**inv, "days_overdue": days})
            if days > cfg["credit_hold_after_days"]:
                hold.add(inv.get("account_id"))
        elif -cfg["upcoming_window_days"] <= days <= 0 and today.weekday() == 0:
            up.setdefault(inv["contact_email"], []).append(inv)
    overdue_mails = [{"to": c, "invoices": [i["number"] for i in v], "max_days": max(i["days_overdue"] for i in v)}
                     for c, v in over.items()
                     if not last_overdue_mail.get(c) or (today - last_overdue_mail[c]).days >= cfg["overdue_mail_every_days"]]
    return {"upcoming": [{"to": c, "invoices": [i["number"] for i in v]} for c, v in up.items()],
            "overdue": overdue_mails, "credit_hold_accounts": sorted(a for a in hold if a)}
