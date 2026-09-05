"""
SurveyProvider — the fourth instance of this codebase's recurring pattern
(`app.leadgen.ai.AIClassifier`, `app.outreach.providers.SendProvider`,
`app.outreach.drafting.MessageDrafter`, now this): a `Protocol` at the external-
dependency boundary, tested against fakes, no real HTTP client for Cint built here.

endpoint_catalogue.md §0's governing rule applies here specifically: "a provider
timeout falls back to the next-best eligible survey, never to a hardcoded default
survey" — `AllocationService.allocate()` (service.py) calls `build_redirect_url()`
per candidate and moves to the next one on `SurveyProviderUnavailable`, rather than
either crashing or silently defaulting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.panel.models import Survey


class SurveyProviderUnavailable(Exception):
    """Raised on a provider timeout/error — never silently swallowed, never treated
    as 'no survey available' (a different, business-meaningful outcome)."""


@dataclass(frozen=True)
class SurveyProjection:
    quota_remaining: int
    cpi_minor: int
    conversion_rate: float


class SurveyProvider(Protocol):
    async def build_redirect_url(self, *, survey: Survey, respondent_ref: str) -> str:
        """May raise SurveyProviderUnavailable."""
        ...

    async def refresh(self, *, survey: Survey) -> SurveyProjection:
        """Re-fetches the PROJECTION fields (schema_catalogue.md §5.1) — never
        computed by Torpedo. May raise SurveyProviderUnavailable."""
        ...
