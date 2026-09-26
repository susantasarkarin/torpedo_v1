"""
DETERMINISTIC BUCKET CLASSIFIER -- no model, no API, runs entirely on the VM
=============================================================================

The user's standing rule is local-only AI inference, and the local models
(1.5B, 3B) both fail lead bucketing badly (docs/AI_MIGRATION_STATUS.md,
2026-09-20: all-REJECT collapse, confidently wrong on clean titles). This
module replaces "ask a model" with rules for the leads that are genuinely
decidable from title/industry/company alone, and defers everything else to
REVIEW rather than guess. It calls no model and no external API.

Design, tuned against the mistakes found in the first version (2026-09-20
experiment, ~30% decided / ~50% accuracy among those):

1. Deterministic exclusions run first (leads/bucket_classifier.check_exclusion)
   -- students, HR, vendor sales roles, retired, etc. Unchanged, proven.
2. Company-name exclusions: a market-research VENDOR/competitor (Ipsos, Kantar,
   NielsenIQ, ...) or an ACADEMIC institution is never a buyer, regardless of
   title. This was the single largest source of "confident and wrong" in the
   first version -- "Global COO at Ipsos" title-matched SFW's research
   patterns and had no company-based check to catch it.
3. Title patterns are checked bucket-by-bucket in a fixed priority order
   (BIM > COGENTIX_RESEARCH > SFW) and are now closer to mutually exclusive:
   the old SFW pattern set included a bare `insights?` that fired on almost
   every COGENTIX_RESEARCH title too ("Consumer Insights Manager" is a
   COGENTIX lead, not SFW), which was the largest single accuracy loss for
   COGENTIX_RESEARCH (33% correct, 28% wrong). SFW's insights-only pattern
   now requires it NOT be a "consumer/customer/shopper/brand" flavoured
   insights title.
4. A company-name industry proxy covers the common case where the industry
   field is empty (frequent in this data) but the company name alone settles
   it -- a recognisable FMCG/consumer-goods major is decisive for
   COGENTIX_RESEARCH the same way "Construction"/"Engineering" already is.
5. Every bucket assignment additionally requires industry (real OR proxied)
   to not actively DISAGREE with the title's bucket -- a title match at the
   wrong industry (e.g. "Marketing Director" at a pure software company) is
   sent to REVIEW rather than guessed, matching the finding that most of
   those were correct rejects, not false ones.

Measured against the same ~11k real 'cheap'-method verdicts (26 Aug-1 Sep):
this final, strictest configuration decides only 5.0% of leads but is right
95.5% of the time it does (BIM 95%, SFW 15% coverage/100% correct,
COGENTIX_RESEARCH 5% coverage/90% correct). Looser intermediate versions were
tried and measured up to ~30% coverage at ~50% accuracy -- rejected as unsafe
for anything beyond REVIEW-queue triage. There is no configuration of these
rules that reaches high coverage AND high accuracy: REJECT is 74% of all
verdicts and is overwhelmingly a soft "no fit found" judgment call
(docs finding, 2026-09-20: only ~2% of REJECTs carry a hard, rule-matchable
reason), which no keyword rule can safely reproduce -- the honest ceiling for
a rules-only classifier is low coverage, not low accuracy.

This is therefore used as a REVIEW-queue triage aid (auto-decide the ~5% it is
confident about, leave everything else exactly where it already goes), not as
a Bedrock/local-model replacement.
"""
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from leads.bucket_classifier import check_exclusion
from leads.outreach_config import REJECT_BUCKET, REVIEW_BUCKET

# ---------------------------------------------------------------- company signals

# Market-research vendors/competitors: someone sells research services FOR a
# living there, they don't buy it from us. Title-based exclusion
# (check_exclusion) does not see the company name, so this is the only place
# that catches "COO at Ipsos" / "Research Director at Forrester".
VENDOR_COMPANIES = re.compile(
    r"ipsos|kantar|nielsen|gfk\b|yougov|forrester|escalent|dynata|toluna|qualtrics|"
    r"surveymonkey|momentive|gartner|\bidc\b|inmoment|medallia|ascribe|cint\b|"
    r"prolific|qualvu|comscore|mintel|euromonitor|globaldata|decision analyst|"
    r"schlesinger|savanta|bva nudge|walr\b|suzy\b|pureprofile|market\.biz|"
    r"esomar|marketresearch|survey research", re.I)

ACADEMIC = re.compile(r"university|college|\.edu\b|institute of|academy of", re.I)

# Well-known consumer-goods majors: a decisive industry proxy for
# COGENTIX_RESEARCH when the industry field is blank, which it very often is.
# Not exhaustive by design -- a miss here falls through to REVIEW, never a
# wrong guess, so the cost of an incomplete list is coverage, not accuracy.
FMCG_MAJORS = re.compile(
    r"unilever|procter\s*&?\s*gamble|\bp&g\b|nestle|nestlé|pepsico|coca-?cola|"
    r"mondelez|kellogg|general mills|colgate|reckitt|kimberly-?clark|"
    r"johnson\s*&?\s*johnson|loreal|l'oreal|mars\b|danone|kraft heinz|"
    r"beiersdorf|henkel|estee lauder|estée lauder|diageo|heineken|ab inbev|"
    r"anheuser|constellation brands|hershey|mondelez|britannia|itc limited|"
    r"hindustan unilever|marico|dabur|godrej consumer|patanjali", re.I)

AEC_INDUSTRY = re.compile(r"construction|architecture|engineering|\baec\b|infrastructure|building", re.I)
RESEARCH_INDUSTRY = re.compile(r"market research|research services", re.I)
FMCG_INDUSTRY = re.compile(r"consumer goods|fmcg|\bcpg\b|retail|beverage|apparel", re.I)

# Titles that name a research role but are NOT market research (product/UX
# research, academic research). These matched SFW's research-role patterns in
# the first version and were the majority of its false positives.
NON_MARKET_RESEARCH = re.compile(
    r"\bux\b|user research|product research|academic research|clinical research|"
    r"research scholar|research assistant professor|r&d\b|research and development",
    re.I)

# ---------------------------------------------------------------- title patterns

BIM_PATTERNS: Tuple[str, ...] = (
    r"\bbim\b", r"\bvdc\b", r"virtual design (?:and|&) construction",
    r"\brevit\b", r"\bnavisworks\b", r"\bcad\b", r"digital (?:delivery|construction)",
)

# Checked BEFORE SFW, and deliberately specific: "consumer/customer/shopper/
# brand insights" is COGENTIX, not SFW's bare "insights".
COGENTIX_PATTERNS: Tuple[str, ...] = (
    r"consumer (?:insights?|research|intelligence|understanding)",
    r"(?:customer|shopper|brand) insights?",
    r"\bcmo\b", r"chief marketing officer",
    r"(?:vp|vice president|head|director|svp|evp)(?: of)? (?:global )?(?:brand|marketing)",
    r"(?:marketing|brand) (?:director|head|manager|lead)",
)

# Patterns that already bake in a role/seniority qualifier -- safe on their own.
SFW_PATTERNS: Tuple[str, ...] = (
    r"panel(?:s)? (?:manager|management|operations)",
    r"(?:head|director|vp|vice president|chief) (?:of )?market research",
)
# NOT included: a bare "research director"/"director of research"/"research
# manager" with no "market" qualifier. Measured 2026-09-26: "research" alone
# means market research far less often than the bucket's own persona list
# assumes -- real hits included a petroleum company, a financial regulator and
# a fraud-detection vendor, none with an industry field to catch them. "market"
# must be explicit; a title that only implies it is a REVIEW, not a guess.
# Topic-only: says "market research"/"primary research"/"fieldwork" but names
# no role. Measured 2026-09-26: a bare "Market Researcher" (no manager/
# director/lead) is overwhelmingly a REJECT in the ground truth -- the person
# DOES the research (often at a vendor/competitor), they don't buy it, and
# without any buying-authority word this can't tell the difference. These
# patterns are therefore only trusted when ALSO paired with a qualifier from
# ROLE_QUALIFIER (checked in _title_bucket).
SFW_TOPIC_ONLY_PATTERNS: Tuple[str, ...] = (
    r"market(?:ing)? research", r"primary research", r"fieldwork",
    r"\b(?:quantitative|qualitative) research\b",
)
ROLE_QUALIFIER = re.compile(
    r"director|manager|head|\blead\b|\bvp\b|vice president|chief|principal|"
    r"svp|evp|coordinator|specialist", re.I)
# A title combining a research topic with sales/lead-gen/BD is a vendor-side
# role selling INTO companies (or a lead-gen specialist whose "market
# research" is one skill among several), not a buyer -- "Market Research and
# Lead Generation" was measured 2026-09-26 as reliably REJECT.
SALES_OR_LEADGEN = re.compile(r"lead generation|business development|\bsales\b", re.I)
# A bare "insights"/"survey" with no other SFW-specific term was tried and
# measured (2026-09-26): it decided SFW for hundreds of REJECT leads (any
# unrelated "X Insights Manager" role -- shipping, HR, government) and for
# many COGENTIX_RESEARCH leads its own more specific patterns didn't happen to
# name ("Chocolate Insights Manager" never says "consumer insights" outright).
# Deliberately not reinstated: this pattern's false-positive rate at the SFW
# bucket accounted for the large majority of every wrong decided answer.
# Nothing replaces it -- a title this thin goes to REVIEW.

BUCKET_PATTERNS: Dict[str, Tuple[re.Pattern, ...]] = {
    "BIM": tuple(re.compile(p, re.I) for p in BIM_PATTERNS),
    "COGENTIX_RESEARCH": tuple(re.compile(p, re.I) for p in COGENTIX_PATTERNS),
    "SFW": tuple(re.compile(p, re.I) for p in SFW_PATTERNS),
}
SFW_TOPIC_ONLY = tuple(re.compile(p, re.I) for p in SFW_TOPIC_ONLY_PATTERNS)

INDUSTRY_AGREES: Dict[str, re.Pattern] = {
    "BIM": AEC_INDUSTRY,
    "SFW": RESEARCH_INDUSTRY,
    "COGENTIX_RESEARCH": FMCG_INDUSTRY,
}


@dataclass
class RuleVerdict:
    bucket: str                 # one of VALID_BUCKETS, REJECT, or REVIEW
    reason: str
    method: str = "rules"


def _title_bucket(title: str) -> Optional[str]:
    for bucket in ("BIM", "COGENTIX_RESEARCH"):
        for pat in BUCKET_PATTERNS[bucket]:
            if pat.search(title):
                return bucket
    if not NON_MARKET_RESEARCH.search(title) and not SALES_OR_LEADGEN.search(title):
        for pat in BUCKET_PATTERNS["SFW"]:
            if pat.search(title):
                return "SFW"
        if ROLE_QUALIFIER.search(title):
            for pat in SFW_TOPIC_ONLY:
                if pat.search(title):
                    return "SFW"
    return None


def classify(lead: Dict[str, object]) -> RuleVerdict:
    """
    Classify one lead with no model call. Always returns a RuleVerdict --
    never raises. A REVIEW verdict means "no rule was confident enough",
    not "this lead is bad" -- it is the intended, safe default.
    """
    title = str(lead.get("title") or lead.get("job_title") or "")
    company = str(lead.get("company") or lead.get("company_name") or "")
    industry = str(lead.get("company_industry") or lead.get("industry") or "")

    # check_exclusion (leads/bucket_classifier.py) does lead.get("title").lower()
    # with no type coercion of its own -- a non-string title (seen in
    # malformed/legacy data) would crash it. Pass it the already-normalised
    # string instead of the raw field.
    excl = check_exclusion({**lead, "title": title})
    if excl:
        return RuleVerdict(REJECT_BUCKET, excl, method="exclusion_filter")
    # No further "empty title" check needed: check_exclusion already returns
    # "no job title" as a hard REJECT for that case, before this point.

    if VENDOR_COMPANIES.search(f"{company} {title}"):
        return RuleVerdict(REVIEW_BUCKET, "company/title matches a market-research vendor or competitor")
    if ACADEMIC.search(f"{company} {title}"):
        return RuleVerdict(REVIEW_BUCKET, "affiliated with an academic institution")

    bucket = _title_bucket(title)
    if bucket is None:
        return RuleVerdict(REVIEW_BUCKET, "no bucket pattern matched the title")

    industry_pat = INDUSTRY_AGREES[bucket]
    industry_says_yes = bool(industry_pat.search(industry))
    industry_says_no = bool(industry.strip()) and not industry_says_yes
    if industry_says_no and bucket == "COGENTIX_RESEARCH" and FMCG_MAJORS.search(company):
        industry_says_no = False   # explicit industry text disagreed, but the
        industry_says_yes = True   # company name itself is decisive

    if industry_says_no:
        return RuleVerdict(REVIEW_BUCKET,
                           f"title matches {bucket} but industry {industry!r} does not agree")

    if not industry_says_yes and bucket == "COGENTIX_RESEARCH" and not FMCG_MAJORS.search(company):
        # COGENTIX needs a positive signal beyond the title (empty industry,
        # unrecognised company) -- this bucket's title patterns are the least
        # specific of the three and had the highest false-positive rate.
        return RuleVerdict(REVIEW_BUCKET, "title matches COGENTIX_RESEARCH but no industry/company signal confirms it")

    return RuleVerdict(bucket, f"title matched {bucket}" + (" (industry agrees)" if industry_says_yes else ""))
