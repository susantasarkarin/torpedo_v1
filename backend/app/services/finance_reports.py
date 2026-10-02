"""
Finance reports behind /admin/finance/reports (2026-10-02: the page asked for
/finance/reports/* and no such endpoint existed, so every report was empty).

All amounts are shown in INR. Invoices are mostly USD and carry no exchange
rate, so other currencies are converted at FINANCE_FX_RATES (JSON in .env,
e.g. {"USD": 84.1}) or the defaults below; every report returns the rates it
used. There is no bank ledger: cash is what invoices record as received minus
what bills and expenses record as paid, and each report says what it is
derived from.
"""
import json
import os
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

DEFAULT_FX = {"INR": 1.0, "USD": 83.0, "EUR": 90.0, "GBP": 105.0, "AED": 22.6, "SGD": 61.0, "AUD": 54.0, "CAD": 61.0}
_CLOSED = {"void", "draft", "cancelled", "canceled", "written_off"}


def fx_rates() -> Dict[str, float]:
    rates = dict(DEFAULT_FX)
    try:
        rates.update({k.upper(): float(v) for k, v in json.loads(os.getenv("FINANCE_FX_RATES", "{}")).items()})
    except Exception:
        pass
    return rates


def _inr(amount, currency, rates) -> float:
    return float(amount or 0) * rates.get((currency or "INR").upper(), 1.0)


def _cur(doc) -> str:
    return (doc.get("currency_code") or doc.get("currency") or "INR").upper()


def _dt(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "")[:19])
        except ValueError:
            return None
    return None


def _range(start: Optional[str], end: Optional[str]):
    s = _dt(start) or datetime(datetime.utcnow().year, 1, 1)
    e = (_dt(end) or datetime.utcnow()).replace(hour=23, minute=59, second=59)
    return s, e


def _live(docs: Iterable[Dict[str, Any]]):
    for d in docs:
        if d.get("is_deleted") or str(d.get("status") or "").lower() in _CLOSED:
            continue
        yield d


def _balance(d) -> float:
    if d.get("balance_due") is not None:
        return float(d.get("balance_due") or 0)
    return max(0.0, float(d.get("total_amount") or d.get("total") or 0) - float(d.get("amount_paid") or 0))


def _paid(d) -> float:
    if d.get("amount_paid") is not None:
        return float(d.get("amount_paid") or 0)
    if str(d.get("status") or "").lower() == "paid":
        return float(d.get("total_amount") or d.get("total") or 0)
    return float(d.get("total_amount") or d.get("total") or 0) - _balance(d)


def _meta(rates, basis: str) -> Dict[str, Any]:
    return {"currency": "INR", "fx_rates": {k: v for k, v in rates.items() if k != "INR"}, "basis": basis}


def profit_loss(db, start=None, end=None) -> Dict[str, Any]:
    rates = fx_rates()
    s, e = _range(start, end)
    in_range = lambda d, f: (lambda t: t is not None and s <= t <= e)(_dt(d.get(f)))
    sales = sum(_inr(i.get("subtotal") if i.get("subtotal") is not None else i.get("total_amount"), _cur(i), rates)
                for i in _live(db["invoices"].find({})) if in_range(i, "invoice_date"))
    cogs = sum(_inr(b.get("subtotal") if b.get("subtotal") is not None else b.get("total_amount"), _cur(b), rates)
               for b in _live(db["bills"].find({})) if in_range(b, "bill_date"))
    operating = sum(_inr(x.get("amount") or x.get("total_amount"), _cur(x), rates)
                    for x in _live(db["expenses"].find({})) if in_range(x, "expense_date") or in_range(x, "date"))
    revenue = {"total_sales": round(sales, 2), "other_income": 0.0, "total": round(sales, 2)}
    expenses = {"cogs": round(cogs, 2), "operating": round(operating, 2), "total": round(cogs + operating, 2)}
    return {"revenue": revenue, "expenses": expenses, "net_profit": round(sales - cogs - operating, 2),
            "period": {"start": s.date().isoformat(), "end": e.date().isoformat()},
            **_meta(rates, "Invoices (before tax) less bills and expenses dated in the period")}


def balance_sheet(db, start=None, end=None) -> Dict[str, Any]:
    rates = fx_rates()
    _, e = _range(start, end)
    upto = lambda d, f: (lambda t: t is None or t <= e)(_dt(d.get(f)))
    invoices = [i for i in _live(db["invoices"].find({})) if upto(i, "invoice_date")]
    bills = [b for b in _live(db["bills"].find({})) if upto(b, "bill_date")]
    expenses = [x for x in _live(db["expenses"].find({})) if upto(x, "expense_date")]
    receivables = sum(_inr(_balance(i), _cur(i), rates) for i in invoices)
    payables = sum(_inr(_balance(b), _cur(b), rates) for b in bills)
    collected = sum(_inr(_paid(i), _cur(i), rates) for i in invoices)
    paid_out = sum(_inr(_paid(b), _cur(b), rates) for b in bills) + \
        sum(_inr(x.get("amount") or x.get("total_amount"), _cur(x), rates) for x in expenses)
    cash = collected - paid_out
    assets = {"cash": round(cash, 2), "receivables": round(receivables, 2), "inventory": 0.0,
              "total": round(cash + receivables, 2)}
    liabilities = {"payables": round(payables, 2), "other": 0.0, "total": round(payables, 2)}
    equity_total = round(assets["total"] - liabilities["total"], 2)
    return {"assets": assets, "liabilities": liabilities,
            "equity": {"retained_earnings": equity_total, "total": equity_total},
            "as_of": e.date().isoformat(),
            **_meta(rates, "Cash = receipts recorded on invoices less bill and expense payments (no bank ledger); "
                           "equity is what balances assets and liabilities")}


def _aging(docs, rates, as_of) -> Dict[str, Any]:
    buckets = OrderedDict((k, 0.0) for k in ("current", "1_30", "31_60", "61_90", "90_plus"))
    count = 0
    for d in docs:
        bal = _balance(d)
        if bal <= 0:
            continue
        count += 1
        due = _dt(d.get("due_date")) or _dt(d.get("invoice_date")) or _dt(d.get("bill_date"))
        days = (as_of - due).days if due else 0
        key = "current" if days <= 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else \
            "61_90" if days <= 90 else "90_plus"
        buckets[key] += _inr(bal, _cur(d), rates)
    out = {k: round(v, 2) for k, v in buckets.items()}
    out["total"] = round(sum(buckets.values()), 2)
    out["count"] = count
    return out


def aging(db, kind: str, start=None, end=None) -> Dict[str, Any]:
    rates = fx_rates()
    _, e = _range(start, end)
    coll = "invoices" if kind == "receivables" else "bills"
    data = _aging(_live(db[coll].find({})), rates, e)
    return {**data, "as_of": e.date().isoformat(),
            **_meta(rates, f"Unpaid {'invoices' if coll == 'invoices' else 'bills'} by days past due")}


def gst(db, start=None, end=None) -> Dict[str, Any]:
    rates = fx_rates()
    s, e = _range(start, end)
    in_range = lambda d, f: (lambda t: t is not None and s <= t <= e)(_dt(d.get(f)))
    tax = lambda d: d.get("tax_total") if d.get("tax_total") is not None else d.get("tax_amount") or 0
    output = sum(_inr(tax(i), _cur(i), rates) for i in _live(db["invoices"].find({})) if in_range(i, "invoice_date"))
    inp = sum(_inr(tax(b), _cur(b), rates) for b in _live(db["bills"].find({})) if in_range(b, "bill_date")) + \
        sum(_inr(x.get("gst_amount") or x.get("tax_amount") or 0, _cur(x), rates)
            for x in _live(db["expenses"].find({})) if in_range(x, "expense_date"))
    return {"output_gst": round(output, 2), "input_gst": round(inp, 2), "net_gst": round(output - inp, 2),
            "period": {"start": s.date().isoformat(), "end": e.date().isoformat()},
            **_meta(rates, "Tax on invoices (output) and on bills and expenses (input) dated in the period")}


def cash_flow(db, start=None, end=None) -> Dict[str, Any]:
    """Money in and out per month. Without a bank ledger, money in is what
    invoices record as received, dated by invoice date."""
    rates = fx_rates()
    s, e = _range(start, end)
    months: "OrderedDict[str, Dict[str, float]]" = OrderedDict()
    cur = datetime(s.year, s.month, 1)
    while cur <= e:
        months[cur.strftime("%Y-%m")] = {"inflow": 0.0, "outflow": 0.0}
        cur = (cur + timedelta(days=32)).replace(day=1)

    def add(key, field, amount):
        if key in months:
            months[key][field] += amount
    for i in _live(db["invoices"].find({})):
        t = _dt(i.get("invoice_date"))
        if t and s <= t <= e:
            add(t.strftime("%Y-%m"), "inflow", _inr(_paid(i), _cur(i), rates))
    for b in _live(db["bills"].find({})):
        t = _dt(b.get("bill_date"))
        if t and s <= t <= e:
            add(t.strftime("%Y-%m"), "outflow", _inr(_paid(b), _cur(b), rates))
    for x in _live(db["expenses"].find({})):
        t = _dt(x.get("expense_date"))
        if t and s <= t <= e:
            add(t.strftime("%Y-%m"), "outflow", _inr(x.get("amount") or x.get("total_amount"), _cur(x), rates))
    rows = [{"month": k, "inflow": round(v["inflow"], 2), "outflow": round(v["outflow"], 2),
             "net": round(v["inflow"] - v["outflow"], 2)} for k, v in months.items()]
    inflow = round(sum(r["inflow"] for r in rows), 2)
    outflow = round(sum(r["outflow"] for r in rows), 2)
    return {"months": rows, "inflow": inflow, "outflow": outflow, "net": round(inflow - outflow, 2),
            "period": {"start": s.date().isoformat(), "end": e.date().isoformat()},
            **_meta(rates, "Receipts recorded on invoices (by invoice date) less bill and expense payments")}


REPORTS = {
    "profit-loss": profit_loss,
    "balance-sheet": balance_sheet,
    "gst-report": gst,
    "cash-flow": cash_flow,
    "aging/receivables": lambda db, start=None, end=None: aging(db, "receivables", start, end),
    "aging/payables": lambda db, start=None, end=None: aging(db, "payables", start, end),
}
