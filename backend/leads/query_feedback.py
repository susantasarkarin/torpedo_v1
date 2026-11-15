"""Lead-search feedback loop (owner, 2026-11-15): the AI's verdict on the leads a search found tunes the next searches.

    search ran  ->  record_run(): which leads each query returned          (email_automation.search_query_leads)
    AI bucket   ->  every lead already gets SFW / COGENTIX_RESEARCH / BIM (good) or REJECT (junk) from lead_bucketing
    daily cycle ->  score_queries(): good-rate per query from those verdicts
                    retire a query by rule when it has enough judged leads and almost none are good
                    ask Haiku (task query_refinement) for exclusion terms and replacement queries,
                    shown the best queries and the junk it produced (job titles + company names only, no personal names)
    next search ->  apply_hints() adds the exclusions (-term), drops retired queries, seeds proven ones

Guardrails: nothing happens below `min_judged` verdicts per ICP; exclusions are single short words that are not
part of the ICP's own titles/industries/countries; at most `max_excludes` are active; every cycle is kept in the
hint's history (rollback = delete the doc or set enabled false); the kill switch is torpedo_settings.config
_id "query_feedback" {"enabled": false}. Hints live in email_automation.icp_search_hints (one doc per ICP slug).
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

GOOD = ("SFW", "COGENTIX_RESEARCH", "BIM")
JUNK = ("REJECT",)
DEFAULTS = {"enabled": True, "min_judged": 40, "min_per_query": 10, "retire_below": 0.10, "good_above": 0.5,
            "max_excludes": 8, "max_seeds": 10, "max_retired": 200, "cycle_hours": 20}
TASK = "query_refinement"

SCHEMA = {
    "type": "object",
    "required": ["exclude_terms", "new_queries", "reason"],
    "properties": {"exclude_terms": {"type": "array", "items": {"type": "string"}},
                   "new_queries": {"type": "array", "items": {"type": "string"}},
                   "reason": {"type": "string"}},
}
SYSTEM = ("You improve Google searches that find LinkedIn profiles of business buyers. You are shown which searches "
          "found the right people and which found the wrong people. Reply only with JSON.")
PROMPT = """ICP (who we want)
Titles: {designations}
Industries: {industries}
Countries: {countries}

SEARCHES THAT FOUND THE RIGHT PEOPLE (good-rate in brackets)
{winners}

SEARCHES THAT FOUND THE WRONG PEOPLE (good-rate in brackets)
{losers}

WRONG PEOPLE THEY RETURNED (title | company)
{junk}

Write:
- exclude_terms: up to {max_excludes} single words (or at most 2 words) that appear in the wrong people's titles/companies but would never appear for the right people. They will be added to searches as -term. Never a word from the ICP's titles, industries or countries.
- new_queries: {n} new searches in the style of the winners, that avoid the wrong kind of people. Each under 150 characters, no site: filters.
- reason: one short sentence.

JSON: {{"exclude_terms": ["..."], "new_queries": ["..."], "reason": "..."}}"""


def settings(gd) -> Dict[str, Any]:
    doc = gd("torpedo_settings")["config"].find_one({"_id": "query_feedback"}) or {}
    return {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}}


def qkey(q: str) -> str:
    """A query without its -exclusions, lower-cased, for comparing."""
    q = re.sub(r'\s-"[^"]+"|\s-\S+', "", " " + (q or ""))
    return re.sub(r"\s+", " ", q).strip().lower()


def _fmt_term(t: str) -> str:
    return f'-"{t}"' if " " in t else f"-{t}"


def apply_hints(queries: List[str], hints: Optional[Dict[str, Any]], max_len: int = 240) -> List[str]:
    """Drop retired queries and add the active exclusions. Pure; the queries' own words are never changed."""
    if not hints or not hints.get("enabled", True):
        return list(queries)
    retired = {qkey(x) for x in hints.get("retired", [])}
    terms = [t for t in hints.get("exclude_terms", []) if t]
    out, seen = [], set()
    for q in queries:
        k = qkey(q)
        if k in retired or k in seen:
            continue
        seen.add(k)
        extra = [t for t in terms if f"-{t}" not in q.lower()]
        while extra and len(q) + 1 + len(" ".join(_fmt_term(t) for t in extra)) > max_len:
            extra.pop()
        out.append(q + (" " + " ".join(_fmt_term(t) for t in extra) if extra else ""))
    return out


def merge_seeds(queries: List[str], hints: Optional[Dict[str, Any]], used: Iterable[str], count: int) -> List[str]:
    """Proven queries not used yet go first, up to half the batch."""
    if not hints or not hints.get("enabled", True):
        return queries
    done = {qkey(u) for u in used}
    seeds = [s for s in hints.get("seed_queries", []) if qkey(s) not in done][: max(1, count // 2)]
    rest = [q for q in queries if qkey(q) not in {qkey(s) for s in seeds}]
    return (seeds + rest)[:count]


def load_hints(gd, slug: str) -> Optional[Dict[str, Any]]:
    try:
        return gd("email_automation")["icp_search_hints"].find_one({"_id": slug})
    except Exception:
        return None


# ------------------------------------------------------------------ attribution


def record_run(gd, icp: Optional[str], query: str, leads: List[Dict[str, Any]], imported: int, duplicates: int,
               now: Optional[datetime] = None) -> None:
    """Best effort; a failure here must never stop a search."""
    try:
        gd("email_automation")["search_query_leads"].insert_one({
            "icp": icp or "", "query": query, "qkey": qkey(query), "found": len(leads), "imported": imported,
            "duplicates": duplicates, "urls": [l.get("linkedin_url") for l in leads if l.get("linkedin_url")][:100],
            "at": now or datetime.utcnow()})
    except Exception:
        logger.exception("query feedback: could not record a search run")


# ------------------------------------------------------------------ scoring


def score_queries(runs: Iterable[Dict[str, Any]], verdicts: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """qkey -> {query, runs, found, judged, good, junk, good_rate}; only leads with a GOOD or REJECT verdict count as judged."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        s = out.setdefault(r.get("qkey") or qkey(r["query"]), {"query": r["query"], "runs": 0, "found": 0, "judged": 0,
                                                              "good": 0, "junk": 0, "urls": []})
        s["runs"] += 1
        s["found"] += r.get("found", 0)
        for u in r.get("urls", []):
            s["urls"].append(u)
            v = verdicts.get(u)
            if v in GOOD:
                s["good"] += 1
                s["judged"] += 1
            elif v in JUNK:
                s["junk"] += 1
                s["judged"] += 1
    for s in out.values():
        s["good_rate"] = round(s["good"] / s["judged"], 3) if s["judged"] else None
    return out


def verdicts_for(gd, urls: List[str]) -> Dict[str, str]:
    col = gd("email_automation")["leads_enriched"]
    out: Dict[str, str] = {}
    urls = list({u for u in urls if u})
    for i in range(0, len(urls), 1000):
        for l in col.find({"linkedin_url": {"$in": urls[i:i + 1000]}, "outreach_bucket": {"$exists": True}},
                          {"linkedin_url": 1, "outreach_bucket": 1}):
            out[l["linkedin_url"]] = l["outreach_bucket"]
    return out


def junk_examples(gd, scored: Dict[str, Dict[str, Any]], verdicts: Dict[str, str], limit: int = 25) -> List[str]:
    """Titles and company names (never personal names) of REJECTed leads from the worst queries."""
    worst = sorted((s for s in scored.values() if s["junk"]), key=lambda s: -s["junk"])[:8]
    urls = [u for s in worst for u in s["urls"] if verdicts.get(u) in JUNK][: limit * 3]
    col = gd("email_automation")["leads_enriched"]
    rows, seen = [], set()
    for l in col.find({"linkedin_url": {"$in": urls}}, {"title": 1, "company_name": 1}):
        line = f"{(l.get('title') or '?')[:60]} | {(l.get('company_name') or '?')[:50]}"
        if line not in seen:
            seen.add(line)
            rows.append(line)
        if len(rows) >= limit:
            break
    return rows


# ------------------------------------------------------------------ refinement


def icp_words(icp: Dict[str, Any]) -> set:
    return {w for v in (icp.get("designations") or []) + (icp.get("industries") or []) + (icp.get("countries") or [])
            for w in re.findall(r"[a-z]{3,}", str(v).lower())}


def check_refinement(icp: Dict[str, Any], cfg: Dict[str, Any]):
    protected = icp_words(icp)

    def check(d, _text):
        p = []
        for t in d.get("exclude_terms") or []:
            words = re.findall(r"[a-z]+", str(t).lower())
            if not words or len(words) > 2 or not re.fullmatch(r"[A-Za-z][A-Za-z ]{1,24}", str(t)):
                p.append(f"bad exclusion term {t!r}")
            elif protected & set(words):
                p.append(f"exclusion {t!r} is part of the ICP itself")
        if len(d.get("exclude_terms") or []) > int(cfg["max_excludes"]):
            p.append("too many exclusion terms")
        return p
    return check


def refine(icp: Dict[str, Any], scored: Dict[str, Dict[str, Any]], junk: List[str], cfg: Dict[str, Any], ladder=None,
           used: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """Haiku (then Sonnet) proposes exclusions and replacement queries. None when the model gave nothing usable."""
    from leads import query_variants_ai as qv
    if ladder is None:
        from platform_core import ladder
    judged = [s for s in scored.values() if s["judged"] >= 3]
    winners = sorted((s for s in judged if s["good_rate"] >= cfg["good_above"]), key=lambda s: -s["good_rate"])[:6]
    losers = sorted((s for s in judged if s["good_rate"] < cfg["retire_below"] * 2), key=lambda s: s["good_rate"])[:6]
    fmt = lambda xs: "\n".join(f"- {s['query'][:120]} [{s['good_rate']:.0%} of {s['judged']}]" for s in xs) or "- (none yet)"
    n = 8
    body = PROMPT.format(designations=qv._fmt(icp.get("designations")), industries=qv._fmt(icp.get("industries")),
                         countries=qv._fmt(icp.get("countries")), winners=fmt(winners), losers=fmt(losers),
                         junk="\n".join(f"- {j}" for j in junk) or "- (none)", max_excludes=cfg["max_excludes"], n=n)
    res = ladder.run(task=TASK, system=SYSTEM, body=body, schema=SCHEMA, code_check=check_refinement(icp, cfg),
                     ref={"collection": "email_automation.icp_search_hints", "id": icp.get("slug", "")},
                     enqueue_on_fail=False)
    data = res.get("data") if res and res.get("status") in ("ok", "review") else None
    if not data:
        return None
    new_q = qv.clean(data.get("new_queries") or [], icp, list(used), n)
    return {"exclude_terms": [str(t).strip().lower() for t in data.get("exclude_terms") or []][: cfg["max_excludes"]],
            "new_queries": new_q, "reason": str(data.get("reason") or "")[:200], "tier": res.get("tier")}


def run_cycle(gd=None, icps: Optional[List[Dict[str, Any]]] = None, apply: bool = False, ladder=None,
              now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One feedback pass over every active ICP. Dry run unless apply."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    cfg = settings(gd)
    if not cfg["enabled"]:
        return [{"skipped": "query_feedback disabled"}]
    if icps is None:
        from leads.icp_config import get_active_icps
        icps = get_active_icps()
    ea = gd("email_automation")
    report = []
    for icp in icps:
        slug = icp.get("slug")
        prev = ea["icp_search_hints"].find_one({"_id": slug}) or {}
        if prev.get("at") and now - prev["at"] < timedelta(hours=int(cfg["cycle_hours"])) and apply:
            report.append({"icp": slug, "skipped": "ran in the last %sh" % cfg["cycle_hours"]})
            continue
        runs = list(ea["search_query_leads"].find({"icp": slug}))
        verdicts = verdicts_for(gd, [u for r in runs for u in r.get("urls", [])])
        scored = score_queries(runs, verdicts)
        judged_total = sum(s["judged"] for s in scored.values())
        row = {"icp": slug, "queries": len(scored), "judged": judged_total}
        if judged_total < int(cfg["min_judged"]):
            row["skipped"] = f"only {judged_total} judged leads, need {cfg['min_judged']}"
            report.append(row)
            continue
        retire = [s["query"] for s in scored.values() if s["judged"] >= int(cfg["min_per_query"])
                  and s["good_rate"] < cfg["retire_below"]]
        winners = [s["query"] for s in sorted((s for s in scored.values() if s["judged"] >= int(cfg["min_per_query"])
                                               and s["good_rate"] >= cfg["good_above"]), key=lambda s: -s["good_rate"])]
        junk = junk_examples(gd, scored, verdicts)
        ai = None
        try:
            ai = refine(icp, scored, junk, cfg, ladder=ladder, used=[s["query"] for s in scored.values()])
        except Exception:
            logger.exception("query feedback: refinement failed for %s", slug)
        retired_all = list(dict.fromkeys(list(prev.get("retired", [])) + retire))[-int(cfg["max_retired"]):]
        seeds = list(dict.fromkeys((ai or {}).get("new_queries", []) + winners))[: int(cfg["max_seeds"])]
        excl = (ai or {}).get("exclude_terms") or prev.get("exclude_terms", [])
        row.update(retire=len(retire), winners=len(winners), exclude_terms=excl, seeds=len(seeds),
                   ai=bool(ai), reason=(ai or {}).get("reason"))
        if apply:
            hist = (prev.get("history") or [])[-29:] + [{"at": now, "version": int(prev.get("version", 0)) + 1,
                                                        "exclude_terms": excl, "retired_added": retire,
                                                        "seed_queries": seeds, "judged": judged_total,
                                                        "reason": (ai or {}).get("reason"), "tier": (ai or {}).get("tier")}]
            ea["icp_search_hints"].update_one({"_id": slug}, {"$set": {
                "enabled": prev.get("enabled", True), "exclude_terms": excl, "seed_queries": seeds,
                "retired": retired_all, "version": int(prev.get("version", 0)) + 1, "at": now, "history": hist}},
                upsert=True)
        report.append(row)
    return report
