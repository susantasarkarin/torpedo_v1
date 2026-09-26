"""
Deterministic parsing of a Google Custom Search result for a LinkedIn profile.
No model call -- shared by leads/ingestion.py and leads/ingestion_vm.py, which
previously each carried their own regex-only fallback (used whenever the
extraction model is unreachable, see extract_leads_from_google_results).

Why this exists (2026-09-26): the old fallback read company_name from a loose
"at Company" match anywhere in the title or snippet, with no bound on length.
A search title is frequently truncated by Google with "...", so "at ..."
matched literally, and a snippet that was itself a whole sentence ("My focus
is on setting clear strategy ...") became the "company name" verbatim --
feeding a domain guess and a synthetic email that was never deliverable
(zach.whitman@opentablemyfocusisonsetting...ship.com, seen in production).

LinkedIn's own search snippet often carries structured fields the profile
page itself writes -- "Experience: <Company> · Education: <School> ·
Location: <City>" -- which are a far more reliable signal than free text,
when present (~17% of real results, measured on the 2026-09-21..26 stash of
1,515 real /in/ profiles). Prefer that; fall back to the title's "at/of
Company" only with a sanity check that rejects a truncation artifact or a
multi-clause sentence; leave company_name empty rather than guess wrong --
downstream (_infer_company_domain, email pattern building) already treats an
empty company_name as "nothing to build a domain from," which is the safe
default this whole pipeline was missing.
"""
import re
from typing import Optional, Tuple

_EXPERIENCE_RE = re.compile(r"Experience:\s*([^·•|\n]+?)(?:\s*[·•]|\.\.\.|$)")
_LOCATION_RE = re.compile(r"Location:\s*([^·•|\n]+?)(?:\s*[·•]|\.\.\.|$)")

# A search title is usually "Name - Title at Company - LinkedIn"; a search
# snippet sometimes repeats "Title at Company" as its own first clause. Try
# "at" and "of" (e.g. "Chief Marketing Officer of Neighborly").
_TITLE_COMPANY_RE = re.compile(
    r"\b(?:at|of)\s+([A-Z][^|\-\n·•]*?)(?:\s*[-–|·•]|\.\.\.|$)", re.UNICODE)

# A snippet that is pure LinkedIn chrome (a private/inactive profile, or the
# cookie-consent boilerplate Google sometimes indexes instead of real
# content) carries no usable signal at all -- worth knowing so a downstream
# caller can choose to skip it rather than build a lead from nothing.
_NO_SIGNAL_MARKERS = (
    "user agreement", "privacy policy", "cookie policy",
    "join to view profile", "report this profile", "close menu",
)

_TRUNCATION_ARTIFACTS = {"...", "…", ".", ""}
_MAX_COMPANY_WORDS = 8
_MAX_COMPANY_CHARS = 60

# Some LinkedIn users literally put one of these in their own "Experience"
# company field (between jobs, freelancing, or as a placeholder) -- found on
# 5/250 real high-confidence rows in the 2026-09-21..26 stash. These are
# structurally "high confidence" (LinkedIn's own field) but are not a company,
# so a domain guess from one (tbc.com, selfemployed.com) is exactly the wrong-
# domain failure mode this module exists to stop.
_PLACEHOLDER_COMPANY_NAMES = {
    "tbc", "tbd", "n/a", "na", "none", "self", "self employed", "self-employed",
    "freelance", "freelancer", "confidential", "stealth", "stealth startup",
    "unemployed", "currently unemployed", "various", "various clients",
    "retired", "independent", "open to work",
}


def _clean_company(raw: Optional[str]) -> str:
    """Reject anything that looks like a truncation artifact, a sentence
    fragment, or a non-company placeholder -- the exact failure mode that let
    a LinkedIn headline become an "email domain" in production."""
    text = (raw or "").strip().strip(".").strip()
    if text in _TRUNCATION_ARTIFACTS:
        return ""
    if text.lower() in _PLACEHOLDER_COMPANY_NAMES:
        return ""
    if len(text) > _MAX_COMPANY_CHARS or text.count(" ") > _MAX_COMPANY_WORDS:
        return ""
    return text


def extract_structured_snippet_fields(snippet: Optional[str]) -> dict:
    """Pull LinkedIn's own 'Experience: X · Location: Y' fields out of a
    search snippet when present. Returns only the keys it found something
    for -- callers should never assume both are present."""
    snippet = snippet or ""
    out = {}
    m = _EXPERIENCE_RE.search(snippet)
    if m:
        company = _clean_company(m.group(1))
        if company:
            out["company_name"] = company
    m = _LOCATION_RE.search(snippet)
    if m:
        loc = m.group(1).strip().rstrip(",").strip()
        if loc and "linkedin" not in loc.lower() and loc not in _TRUNCATION_ARTIFACTS:
            out["location"] = loc
    return out


def extract_company_from_free_text(*texts: Optional[str]) -> str:
    """Fall back to a title/snippet's own '... at Company ...' or '... of
    Company ...' clause, in the order given. Returns '' rather than a
    truncation artifact or an oversized match."""
    for text in texts:
        m = _TITLE_COMPANY_RE.search(text or "")
        if m:
            company = _clean_company(m.group(1))
            if company:
                return company
    return ""


def has_no_real_signal(snippet: Optional[str]) -> bool:
    """True when a search result's snippet is LinkedIn/Google chrome (a
    private or inactive profile, or an indexed cookie-consent notice) with no
    profile content at all -- a caller may want to skip these rather than
    mint a lead with every field empty."""
    low = (snippet or "").strip().lower()
    return any(marker in low for marker in _NO_SIGNAL_MARKERS)


def resolve_company_and_location(title: Optional[str], snippet: Optional[str]
                                 ) -> Tuple[str, str]:
    """The one entry point callers should use: structured snippet fields win
    when present, then the title's own clause, then the snippet's own clause.
    Returns (company_name, location); either may be ''.

    Validated 2026-09-26 against 1,515 real stashed profiles: the structured
    "Experience:" field is reliably a real company name. The free-text
    fallback still occasionally captures a title/sentence fragment ("Business
    & Have Equity Stake In the Company", "Creative") rather than a company --
    good enough to show a human, not good enough to build a domain guess and
    a synthetic email from (that exact chain is what produced the
    undiliverable-address incident this module was written to stop). Use
    resolve_company_with_confidence() when the caller needs to draw that line.
    """
    structured = extract_structured_snippet_fields(snippet)
    company = structured.get("company_name") or extract_company_from_free_text(title, snippet)
    location = structured.get("location", "")
    return company, location


def resolve_company_with_confidence(title: Optional[str], snippet: Optional[str]
                                    ) -> Tuple[str, str, bool]:
    """Same result as resolve_company_and_location, plus whether company_name
    came from LinkedIn's own structured field (high_confidence=True) rather
    than a free-text guess (False). Callers building a company_domain/email
    guess should gate that on high_confidence -- see the module docstring."""
    structured = extract_structured_snippet_fields(snippet)
    if structured.get("company_name"):
        return structured["company_name"], structured.get("location", ""), True
    return extract_company_from_free_text(title, snippet), structured.get("location", ""), False
