"""
The canonical ICP scorer — decision B-04 (business_rules_register.md §4.0):
`icp_config.py`'s 3/2/2/1 scale (title 3, industry 2, country 2, seniority 1,
qualifying at >=4) is the ONE scorer. v1 had five or six competing, independently-
weighted implementations (register §4.0's table); this is deliberately the only one
in v2, and I-1 makes a second implementation of this function a defect by
construction, not a style question.

Two v1 incidents are ported forward as guards, per B-04's explicit port-then-delete
condition — deleting the other scorers without carrying these forward would silently
reopen both:

1. **Empty-industry guard.** A prior v1 version scored an empty `industry` string as
   matching every keyword (`"" in kw` is always `True` in Python), which put 99.8% of
   a "Dual Fit" basket there on no evidence at all (register §4.3). Guarded here by
   requiring a minimum length before any industry match is attempted.
2. **Tie-breaking to unqualified, never by list order.** A prior v1 version broke
   ties between candidate ICPs by iteration order, which a dry run showed would move
   10,790 leads into the wrong bucket "on the strength of no evidence at all"
   (register §4.3). Out of scope for *this* module specifically — see the module
   docstring below for why multi-ICP tie-breaking isn't implemented yet — but the
   principle (never resolve ambiguity by incidental order) governs anywhere this
   scorer is extended to compare multiple ICP profiles.

**Scope note:** this slice scores against ONE target ICP profile per call — there is
no persisted "multiple simultaneous ICP definitions" entity in backend_v2 yet, so
there is nothing to break ties *between*. Full multi-ICP tie-breaking (guard #2
above, applied literally) is deferred to whenever ICP profiles themselves become a
managed entity, not silently skipped — recorded here so it isn't mistaken for an
oversight later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

QUALIFY_THRESHOLD = 4
SCORER_VERSION = "icp_config_v1"  # bump this, not the weights in place, if the rule ever changes

# A representative subset of v1's seniority-marker list (leads/outreach_config.py) —
# this slice ports the SCORING MECHANISM, not the full v1 keyword corpus, which is a
# content/ops-ownership question (register §4.1: "ownership and review cadence need
# an owner") separate from the mechanism this module is responsible for.
SENIOR_TITLE_MARKERS = frozenset(
    {"vp", "vice president", "chief", "director", "head", "founder", "president", "ceo", "cto", "cfo", "coo"}
)

_MIN_MATCH_LENGTH = 3  # the empty-industry guard's actual threshold


@dataclass(frozen=True)
class ICPProfile:
    """The target profile a lead is scored against. One profile per call —
    see module docstring."""

    industries: frozenset[str] = field(default_factory=frozenset)
    countries: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ScoreResult:
    score: int
    qualifies: bool
    scorer_version: str
    breakdown: dict[str, int]


def score_lead(
    *,
    title: str | None,
    industry: str | None,
    country: str | None,
    seniority_marker_present: bool | None = None,
    profile: ICPProfile,
) -> ScoreResult:
    breakdown = {"title": 0, "industry": 0, "country": 0, "seniority": 0}

    if title and len(title.strip()) >= _MIN_MATCH_LENGTH:
        lowered = title.lower()
        if any(marker in lowered for marker in SENIOR_TITLE_MARKERS):
            breakdown["title"] = 3

    # The empty-industry guard: `industry` must clear a minimum length AND the
    # profile must actually declare industries to match against — neither side of
    # an empty-vs-empty comparison may score a point. This is the exact fix for the
    # v1 incident cited in the module docstring.
    if industry and len(industry.strip()) >= _MIN_MATCH_LENGTH and profile.industries:
        if industry.strip().lower() in {i.lower() for i in profile.industries}:
            breakdown["industry"] = 2

    if country and len(country.strip()) >= 2 and profile.countries:
        if country.strip().lower() in {c.lower() for c in profile.countries}:
            breakdown["country"] = 2

    if seniority_marker_present:
        breakdown["seniority"] = 1

    total = sum(breakdown.values())
    return ScoreResult(score=total, qualifies=total >= QUALIFY_THRESHOLD, scorer_version=SCORER_VERSION, breakdown=breakdown)
