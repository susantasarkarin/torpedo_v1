"""
Finance reports behind /admin/finance/reports (2026-10-02: the page asked for
/finance/reports/* and no such endpoint existed, so every report was empty).

All amounts are shown in INR. Each invoice, bill and expense is converted at
the rate of ITS OWN DATE (owner, 2026-10-02: an invoice's rate is the one on
the day it was raised and must never change later). A rate recorded on the
document itself (exchange_rate) wins; otherwise the day's rate is fetched once
from frankfurter (ECB) and locked in finance_db.invoice_fx -- never refetched
or overwritten. Only a document with no date falls back to today's rate. There is no bank ledger: cash is what invoices record as received minus
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


_FX_CACHE: Dict[str, Any] = {"at": 0.0, "rates": None, "as_of": None}
FX_TTL_SECONDS = 6 * 3600


def _live_fx() -> Optional[Dict[str, Any]]:
    """INR per unit of each currency, from open.er-api.com (free, no key),
    refreshed at most every 6 hours (owner, 2026-10-02: real-time rates)."""
    import time
    import requests
    if _FX_CACHE["rates"] and time.time() - _FX_CACHE["at"] < FX_TTL_SECONDS:
        return _FX_CACHE
    try:
        d = requests.get("https://open.er-api.com/v6/latest/INR", timeout=10).json()
        if d.get("result") != "success":
            return _FX_CACHE if _FX_CACHE["rates"] else None
        rates = {k.upper(): round(1 / v, 4) for k, v in d["rates"].items() if v}
        _FX_CACHE.update(at=time.time(), rates=rates, as_of=d.get("time_last_update_utc"))
        return _FX_CACHE
    except Exception:
        return _FX_CACHE if _FX_CACHE["rates"] else None


def fx_rates() -> Dict[str, float]:
    """Live rates; the defaults only if the rate service cannot be reached.
    FINANCE_FX_RATES (JSON) still overrides a currency when set."""
    rates = dict(DEFAULT_FX)
    live = _live_fx()
    if live:
        rates.update(live["rates"])
    try:
        rates.update({k.upper(): float(v) for k, v in json.loads(os.getenv("FINANCE_FX_RATES", "{}")).items()})
    except Exception:
        pass
    rates["INR"] = 1.0
    return rates


def fx_source() -> str:
    return f"live rates as of {_FX_CACHE['as_of']}" if _FX_CACHE.get("rates") else "fallback rates (rate service unreachable)"


def _inr(amount, doc, conv) -> float:
    return float(amount or 0) * conv.rate(doc)


_DATE_FIELDS = ("invoice_date", "bill_date", "expense_date", "date", "payment_date")


def _historical(currency: str, day: str) -> Optional[float]:
    """INR per unit of `currency` on `day` (YYYY-MM-DD; a holiday gives the
    last business day before it)."""
    import requests
    try:
        d = requests.get(f"https://api.frankfurter.dev/v1/{day}", params={"from": currency, "to": "INR"},
                         timeout=10).json()
        r = (d.get("rates") or {}).get("INR")
        return float(r) if r else None
    except Exception:
        return None


class Converter:
    """Per-document rates, locked once known."""

    def __init__(self, db):
        self.db = db
        self.live = fx_rates()
        self.locked: Dict[str, float] = {}
        self.daily: Dict[tuple, Optional[float]] = {}
        self.counts = {"locked": 0, "on_document": 0, "today": 0}
        try:
            for x in db["invoice_fx"].find({}, {"rate": 1}):
                self.locked[str(x["_id"])] = float(x["rate"])
        except Exception:
            pass

    def _key(self, doc) -> Optional[str]:
        i = doc.get("_id")
        if i is None:
            return None
        coll = "bill" if doc.get("bill_date") else "expense" if doc.get("expense_date") else "invoice"
        return f"{coll}:{i}"

    def rate(self, doc) -> float:
        cur = _cur(doc)
        if cur == "INR":
            return 1.0
        own = doc.get("exchange_rate")
        try:
            if own and float(own) > 0:
                self.counts["on_document"] += 1
                return float(own)
        except (TypeError, ValueError):
            pass
        key = self._key(doc)
        if key and key in self.locked:
            self.counts["locked"] += 1
            return self.locked[key]
        day = next((_dt(doc.get(f)) for f in _DATE_FIELDS if _dt(doc.get(f))), None)
        if key and day:
            ds = day.strftime("%Y-%m-%d")
            if (cur, ds) not in self.daily:
                self.daily[(cur, ds)] = _historical(cur, ds)
            r = self.daily[(cur, ds)]
            if r:
                self.locked[key] = r
                try:  # insert-only: an existing locked rate is never overwritten
                    self.db["invoice_fx"].update_one({"_id": key}, {"$setOnInsert": {
                        "currency": cur, "rate": r, "rate_date": ds, "source": "frankfurter (ECB)",
                        "locked_at": datetime.utcnow()}}, upsert=True)
                except Exception:
                    pass
                self.counts["locked"] += 1
                return r
        self.counts["today"] += 1
        return self.live.get(cur, 1.0)


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


_SHOWN = ("USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD")


def _meta(conv, basis: str) -> Dict[str, Any]:
    c = conv.counts
    src = (f"each document's own-date rate ({c['locked'] + c['on_document']} converted at their date"
           + (f", {c['today']} with no date at today's rate" if c["today"] else "") + ")")
    return {"currency": "INR", "fx_rates": {k: conv.live[k] for k in _SHOWN if k in conv.live},
            "fx_source": src, "basis": basis}


def profit_loss(db, start=None, end=None) -> Dict[str, Any]:
    rates = Converter(db)
    s, e = _range(start, end)
    in_range = lambda d, f: (lambda t: t is not None and s <= t <= e)(_dt(d.get(f)))
    sales = sum(_inr(i.get("subtotal") if i.get("subtotal") is not None else i.get("total_amount"), i, rates)
                for i in _live(db["invoices"].find({})) if in_range(i, "invoice_date"))
    cogs = sum(_inr(b.get("subtotal") if b.get("subtotal") is not None else b.get("total_amount"), b, rates)
               for b in _live(db["bills"].find({})) if in_range(b, "bill_date"))
    operating = sum(_inr(x.get("amount") or x.get("total_amount"), x, rates)
                    for x in _live(db["expenses"].find({})) if in_range(x, "expense_date") or in_range(x, "date"))
    revenue = {"total_sales": round(sales, 2), "other_income": 0.0, "total": round(sales, 2)}
    expenses = {"cogs": round(cogs, 2), "operating": round(operating, 2), "total": round(cogs + operating, 2)}
    return {"revenue": revenue, "expenses": expenses, "net_profit": round(sales - cogs - operating, 2),
            "period": {"start": s.date().isoformat(), "end": e.date().isoformat()},
            **_meta(rates, "Invoices (before tax) less bills and expenses dated in the period")}


def balance_sheet(db, start=None, end=None) -> Dict[str, Any]:
    rates = Converter(db)
    _, e = _range(start, end)
    upto = lambda d, f: (lambda t: t is None or t <= e)(_dt(d.get(f)))
    invoices = [i for i in _live(db["invoices"].find({})) if upto(i, "invoice_date")]
    bills = [b for b in _live(db["bills"].find({})) if upto(b, "bill_date")]
    expenses = [x for x in _live(db["expenses"].find({})) if upto(x, "expense_date")]
    receivables = sum(_inr(_balance(i), i, rates) for i in invoices)
    payables = sum(_inr(_balance(b), b, rates) for b in bills)
    collected = sum(_inr(_paid(i), i, rates) for i in invoices)
    paid_out = sum(_inr(_paid(b), b, rates) for b in bills) + \
        sum(_inr(x.get("amount") or x.get("total_amount"), x, rates) for x in expenses)
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
        buckets[key] += _inr(bal, d, rates)
    out = {k: round(v, 2) for k, v in buckets.items()}
    out["total"] = round(sum(buckets.values()), 2)
    out["count"] = count
    return out


def aging(db, kind: str, start=None, end=None) -> Dict[str, Any]:
    rates = Converter(db)
    _, e = _range(start, end)
    coll = "invoices" if kind == "receivables" else "bills"
    data = _aging(_live(db[coll].find({})), rates, e)
    return {**data, "as_of": e.date().isoformat(),
            **_meta(rates, f"Unpaid {'invoices' if coll == 'invoices' else 'bills'} by days past due")}


def gst(db, start=None, end=None) -> Dict[str, Any]:
    rates = Converter(db)
    s, e = _range(start, end)
    in_range = lambda d, f: (lambda t: t is not None and s <= t <= e)(_dt(d.get(f)))
    tax = lambda d: d.get("tax_total") if d.get("tax_total") is not None else d.get("tax_amount") or 0
    output = sum(_inr(tax(i), i, rates) for i in _live(db["invoices"].find({})) if in_range(i, "invoice_date"))
    inp = sum(_inr(tax(b), b, rates) for b in _live(db["bills"].find({})) if in_range(b, "bill_date")) + \
        sum(_inr(x.get("gst_amount") or x.get("tax_amount") or 0, x, rates)
            for x in _live(db["expenses"].find({})) if in_range(x, "expense_date"))
    return {"output_gst": round(output, 2), "input_gst": round(inp, 2), "net_gst": round(output - inp, 2),
            "period": {"start": s.date().isoformat(), "end": e.date().isoformat()},
            **_meta(rates, "Tax on invoices (output) and on bills and expenses (input) dated in the period")}


def cash_flow(db, start=None, end=None) -> Dict[str, Any]:
    """Money in and out per month. Without a bank ledger, money in is what
    invoices record as received, dated by invoice date."""
    rates = Converter(db)
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
            add(t.strftime("%Y-%m"), "inflow", _inr(_paid(i), i, rates))
    for b in _live(db["bills"].find({})):
        t = _dt(b.get("bill_date"))
        if t and s <= t <= e:
            add(t.strftime("%Y-%m"), "outflow", _inr(_paid(b), b, rates))
    for x in _live(db["expenses"].find({})):
        t = _dt(x.get("expense_date"))
        if t and s <= t <= e:
            add(t.strftime("%Y-%m"), "outflow", _inr(x.get("amount") or x.get("total_amount"), x, rates))
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
