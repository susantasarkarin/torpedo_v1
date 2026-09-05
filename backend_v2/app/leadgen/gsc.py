"""
GSCProvider — the seventh instance of this codebase's external-boundary `Protocol`
pattern. Search Console data (queries/pages/impressions/clicks/ctr/position/country)
is the credential-blocked half of AI lead generation — no Google credentials exist
in this environment. Everything downstream of "GSC signals already fetched" (context
assembly, the AI decision, deduplicated lead creation) is real and tested against a
fake implementation of this Protocol, never a live Search Console call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class GSCProviderUnavailable(Exception):
    """Raised, never returned as an empty signal list — mirrors every other
    provider Protocol's failure mode in this codebase."""


@dataclass(frozen=True)
class SearchSignal:
    query: str
    page: str
    impressions: int
    clicks: int
    ctr: float
    position: float
    country: str | None = None


class GSCProvider(Protocol):
    async def get_search_analytics(self, *, site_url: str, days: int = 28) -> list[SearchSignal]:
        """May raise GSCProviderUnavailable."""
        ...
