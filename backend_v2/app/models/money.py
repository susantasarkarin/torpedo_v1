"""
Money — never a bare float, never a string, never a provider-shaped nested dict.

v1 represented money as a raw Python `float` in every one of the ~40 monetary fields
the lineage map found (data_lineage_map.md §2), plus at least two places where it
arrived as a **string** and was defensively `float()`-cast at the read site (a bug
class, not a coincidence — `cint_service.py`'s CPI comparison did a *lexicographic*
string comparison on one of these). schema_catalogue.md §0 fixes the shape once,
here, for every entity in the system rather than per-field.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_ISO_4217 = re.compile(r"^[A-Z]{3}$")


class Money(BaseModel):
    """Integer minor units (e.g. paise, cents) — never float, never Decimal in transit."""

    amount_minor: int
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _currency_is_iso4217_shaped(cls, v: str) -> str:
        v = v.upper()
        if not _ISO_4217.match(v):
            raise ValueError(f"currency must be a 3-letter ISO 4217 code, got {v!r}")
        return v

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            # v1 summed total_receivables/total_payables across mixed currencies with
            # no FX normalization (D-38) and produced arithmetically meaningless
            # scalars. Refusing to add mismatched currencies is the structural fix.
            raise ValueError(
                f"cannot add Money in different currencies: {self.currency} + {other.currency}"
            )
        return Money(amount_minor=self.amount_minor + other.amount_minor, currency=self.currency)

    def __repr__(self) -> str:
        return f"Money({self.amount_minor}, {self.currency!r})"
