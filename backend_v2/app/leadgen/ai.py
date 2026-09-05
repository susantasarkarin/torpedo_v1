"""
The AI enrichment boundary — a `Protocol`, not a concrete client, per spec §17
(provider-specific behavior belongs in adapters). No real model is called from this
package; `LeadGenService` is tested against fake implementations of `AIClassifier`
(see tests/test_leadgen_service.py) exactly the way `AccountReferenceRepointer`
(Slice 5) is tested against a fake — the pattern is deliberately identical.

`AIClassifier.classify()` proposes ENRICHMENT fields (e.g. inferred industry,
seniority) — it never proposes a qualification verdict. `LeadGenService` is what
enforces that AI cannot qualify or disqualify a lead: the canonical scorer
(`scoring.py`) is called unconditionally after enrichment, using whatever fields
were actually applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AIUnavailable(Exception):
    """
    Raised, never returned as a low-confidence result. This is invariant I-4 (`AI
    failure is never a business verdict`) at the type level: a caller cannot
    accidentally treat an outage as "AI answered, just not confidently" because the
    two are different exceptions/return shapes entirely, the same way
    AuthenticationFailed (401) and PermissionDenied (403) are kept structurally
    separate in the auth/rbac slices.
    """


@dataclass(frozen=True)
class AIClassificationResult:
    fields: dict  # proposed enrichment values only — never a qualification state
    confidence: float
    model: str
    model_version: str


class AIClassifier(Protocol):
    async def classify(self, *, person_fields: dict, account_fields: dict) -> AIClassificationResult:
        """May raise AIUnavailable. Never returns a qualification verdict — only
        proposed enrichment fields and a confidence score."""
        ...


AI_CONFIDENCE_THRESHOLD = 0.70  # register §4.2's bucket_classifier threshold — the one
# v1 module the register calls "the reference implementation for I-4" (§4.2). Reused
# here rather than inventing a new number.
