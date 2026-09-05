"""
compute_totals — the one function that derives Invoice/Bill subtotal/tax_total/total
from line items. Deliberately the only place this arithmetic happens: `FinanceService`
calls this and nothing else computes a total, so there is exactly one implementation
to get right rather than N call sites each doing their own `$inc`-style summation
(the shape of D-38 — v1's AR/AP scalars drifted because more than one thing wrote them).

Integer minor-unit arithmetic throughout, floor division for tax (deterministic,
no float rounding drift — v1 had none at all, "no rounding in write path"). This is
line-item-level GST computation, not a full tax engine: HSN/SAC-to-rate lookup,
multi-rate-per-line splits (CGST+SGST vs IGST), and rounding-rule configurability are
out of this slice's scope — `gst_rate_bps` is supplied per line, not derived.
"""

from __future__ import annotations

from app.finance.models import LineItem
from app.models.money import Money


def compute_totals(line_items: list[LineItem], *, currency: str) -> tuple[Money, Money, Money]:
    subtotal_minor = 0
    tax_minor = 0
    for item in line_items:
        line_amount = item.unit_price_minor * item.quantity
        subtotal_minor += line_amount
        tax_minor += (line_amount * item.gst_rate_bps) // 10_000
    total_minor = subtotal_minor + tax_minor
    return (
        Money(amount_minor=subtotal_minor, currency=currency),
        Money(amount_minor=tax_minor, currency=currency),
        Money(amount_minor=total_minor, currency=currency),
    )
