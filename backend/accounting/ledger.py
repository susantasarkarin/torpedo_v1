"""Double-entry ledger per BU entity (CRM plan 3.9). Pure.

Journal entries are immutable: a mistake is fixed with a reversal entry,
never an edit. Amounts are in the entity's book currency (INR); a foreign
document carries its own currency and the locked FX rate on the entry.
Collection (when wired): finance_db.journal, one document per entry.
"""
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

# type: asset | liability | equity | income | expense
CHART: Dict[str, Dict[str, str]] = {
    "1000": {"name": "Bank", "type": "asset"},
    "1100": {"name": "Accounts receivable", "type": "asset"},
    "1150": {"name": "TDS receivable (deducted by clients)", "type": "asset"},
    "1200": {"name": "GST input credit", "type": "asset"},
    "1300": {"name": "Inter-company receivable", "type": "asset"},
    "2000": {"name": "Accounts payable", "type": "liability"},
    "2100": {"name": "Output CGST", "type": "liability"},
    "2110": {"name": "Output SGST", "type": "liability"},
    "2120": {"name": "Output IGST", "type": "liability"},
    "2130": {"name": "Output GST (split pending, imported)", "type": "liability"},
    "2200": {"name": "TDS payable", "type": "liability"},
    "2300": {"name": "Panel incentives payable", "type": "liability"},
    "2400": {"name": "Inter-company payable", "type": "liability"},
    "3000": {"name": "Owner's equity / opening balance", "type": "equity"},
    "4000": {"name": "Revenue - data services", "type": "income"},
    "4100": {"name": "Revenue - research services", "type": "income"},
    "4900": {"name": "FX gain / loss", "type": "income"},
    "5000": {"name": "Vendor sample cost", "type": "expense"},
    "5100": {"name": "Panel incentive cost", "type": "expense"},
    "5200": {"name": "Other direct cost", "type": "expense"},
    "6000": {"name": "Bank charges", "type": "expense"},
    "6100": {"name": "Bad debts written off", "type": "expense"},
    "1050": {"name": "Receipts not yet matched to bank (imported)", "type": "asset"},
}
PL_TYPES = ("income", "expense")


class LedgerError(ValueError):
    pass


def entry(*, entity: str, on: date, memo: str, lines: List[Dict[str, Any]], source: Dict[str, Any],
          currency: str = "INR", fx_rate: Optional[float] = None, chart=CHART) -> Dict[str, Any]:
    """lines: [{'account': '1100', 'debit': x} | {'account': '4000', 'credit': x}, ...]."""
    dr = round(sum(float(l.get("debit") or 0) for l in lines), 2)
    cr = round(sum(float(l.get("credit") or 0) for l in lines), 2)
    if not lines or dr != cr or dr == 0:
        raise LedgerError(f"unbalanced entry: debit {dr} vs credit {cr}")
    for l in lines:
        if l["account"] not in chart:
            raise LedgerError(f"unknown account {l['account']}")
        if (l.get("debit") or 0) < 0 or (l.get("credit") or 0) < 0:
            raise LedgerError("negative amounts are not allowed; reverse instead")
    if not entity:
        raise LedgerError("entity required")
    return {"entity": entity, "date": on, "memo": memo, "currency": currency, "fx_rate": fx_rate,
            "lines": [{"account": l["account"], "debit": round(float(l.get("debit") or 0), 2),
                       "credit": round(float(l.get("credit") or 0), 2), **({"party": l["party"]} if l.get("party") else {})}
                      for l in lines],
            "source": source, "reverses": None}


def reversal(original: Dict[str, Any], on: date, reason: str, original_id: str) -> Dict[str, Any]:
    e = entry(entity=original["entity"], on=on, memo=f"Reversal: {reason}",
              lines=[{"account": l["account"], "debit": l["credit"], "credit": l["debit"], "party": l.get("party")}
                     for l in original["lines"]], source={"type": "reversal", "id": original_id},
              currency=original.get("currency", "INR"), fx_rate=original.get("fx_rate"))
    e["reverses"] = original_id
    return e


def _d(v) -> date:
    return v.date() if isinstance(v, datetime) else v


def balances(entries: Iterable[Dict[str, Any]], entity: str, *, until: Optional[date] = None,
             since: Optional[date] = None) -> Dict[str, float]:
    """Debit-positive balance per account."""
    out: Dict[str, float] = defaultdict(float)
    for e in entries:
        if e["entity"] != entity:
            continue
        d = _d(e["date"])
        if (until and d > until) or (since and d < since):
            continue
        for l in e["lines"]:
            out[l["account"]] += l["debit"] - l["credit"]
    return {k: round(v, 2) for k, v in out.items()}


def trial_balance(entries, entity: str, until: Optional[date] = None, chart=CHART) -> Dict[str, Any]:
    b = balances(entries, entity, until=until)
    rows = [{"account": a, "name": chart[a]["name"], "debit": max(v, 0), "credit": max(-v, 0)} for a, v in sorted(b.items())]
    td, tc = round(sum(r["debit"] for r in rows), 2), round(sum(r["credit"] for r in rows), 2)
    return {"rows": rows, "total_debit": td, "total_credit": tc, "balanced": td == tc}


def profit_and_loss(entries, entity: str, since: date, until: date, chart=CHART) -> Dict[str, Any]:
    b = balances(entries, entity, since=since, until=until)
    income = {a: -v for a, v in b.items() if chart[a]["type"] == "income"}
    expense = {a: v for a, v in b.items() if chart[a]["type"] == "expense"}
    ti, te = round(sum(income.values()), 2), round(sum(expense.values()), 2)
    return {"income": income, "expense": expense, "total_income": ti, "total_expense": te, "net_profit": round(ti - te, 2)}


def balance_sheet(entries, entity: str, until: date, chart=CHART) -> Dict[str, Any]:
    b = balances(entries, entity, until=until)
    assets = {a: v for a, v in b.items() if chart[a]["type"] == "asset"}
    liab = {a: -v for a, v in b.items() if chart[a]["type"] == "liability"}
    equity = {a: -v for a, v in b.items() if chart[a]["type"] == "equity"}
    retained = round(-sum(v for a, v in b.items() if chart[a]["type"] in PL_TYPES), 2)
    ta = round(sum(assets.values()), 2)
    tle = round(sum(liab.values()) + sum(equity.values()) + retained, 2)
    return {"assets": assets, "liabilities": liab, "equity": equity, "retained_earnings": retained,
            "total_assets": ta, "total_liabilities_equity": tle, "balanced": ta == tle}
