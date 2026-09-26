"""
TITLE FIT SIGNALS -- an independent check that does not trust any model
=======================================================================

Small models fail bucketing confidently: the local 3B answered REJECT at
confidence 0.9 for "BIM Manager / Product Owner" and "Research Director"
(docs/AI_MIGRATION_STATUS.md, 2026-09-20). A confidence threshold cannot catch
that, because the model's confidence is unrelated to whether it is right. The
repo's standing rule for local-model work is "an independent correctness check
must exist outside the model's own self-reported confidence". This module is that
check for the one terminal, hard-to-undo verdict: REJECT.

A title that names a role we sell to -- BIM Manager, Research Director, Consumer
Insights Lead, CMO -- is strong evidence the lead belongs to a service-line
bucket. It is not proof (a vendor's "Head of Panel Sales" also matches), so the
signal is used ONLY to stop a model from finally rejecting such a lead: the lead
goes to REVIEW with the REJECT kept as the proposal, and a person decides. It is
never used to accept a lead into a bucket automatically.

Matching is on whole words/phrases against the lower-cased title. Titles are
usually LinkedIn headlines ("Sr. Analyst @ Acme | Ex-Nielsen"), so each pattern
is deliberately specific rather than clever.
"""

import re
from typing import Dict, List, Optional, Tuple

# bucket -> patterns. Order within a bucket runs strongest first.
FIT_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "BIM": (
        r"\bbim\b",
        r"\bvdc\b",
        r"virtual design (?:and|&) construction",
        r"\brevit\b",
        r"\bnavisworks\b",
        r"\bcad\b",
        r"digital (?:delivery|construction|engineering)",
        r"design technology",
    ),
    "SFW": (
        r"market(?:ing)? research",
        r"(?:head|director|vp|vice president|lead|chief) (?:of )?research",
        r"research (?:director|manager|head|lead|operations|partnerships|officer|analyst)",
        r"research (?:and|&) insights?",
        r"\binsights?\b",
        r"\bpanel(?:s)?\b",
        r"\bsurveys?\b",
        r"fieldwork",
        r"primary research",
        r"data collection",
        r"\b(?:quantitative|qualitative)\b",
    ),
    "COGENTIX_RESEARCH": (
        r"consumer (?:insights?|research|intelligence|understanding)",
        r"(?:customer|shopper|brand) insights?",
        r"\bcmo\b",
        r"chief marketing officer",
        r"(?:vp|vice president|head|director|svp|evp)(?: of)? (?:global )?(?:brand|marketing)",
        r"(?:marketing|brand) (?:director|head|manager|lead)",
        r"head of brand",
    ),
}

_COMPILED: Dict[str, Tuple[re.Pattern, ...]] = {
    bucket: tuple(re.compile(p) for p in pats) for bucket, pats in FIT_PATTERNS.items()
}


def fit_signals(title: Optional[str]) -> List[Tuple[str, str]]:
    """Every (bucket, matched text) the title carries, strongest bucket-pattern first."""
    t = (title or "").lower()
    if not t.strip():
        return []
    found: List[Tuple[str, str]] = []
    for bucket, patterns in _COMPILED.items():
        for pat in patterns:
            m = pat.search(t)
            if m:
                found.append((bucket, m.group(0)))
                break   # one hit per bucket is enough to report
    return found


def strongest_fit(title: Optional[str]) -> Optional[Tuple[str, str]]:
    """The first (bucket, matched text) for this title, or None. Bucket order in
    FIT_PATTERNS is the tie-break: BIM terms are the most specific, then SFW."""
    hits = fit_signals(title)
    return hits[0] if hits else None
