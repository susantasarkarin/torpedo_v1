"""
Search terms written by the local SLM (owner, 2026-09-29: "if rejections are
happening due to search results being already present, then you need to
modify the search terms ... the SLM should be used and new variations of
search terms needs to be found out").

A query is tapped out when Google keeps returning people we already have
(the cse_query_ledger's dupe_streak) or its ~100-result window is used up.
Qwen then writes new variations of it -- other title synonyms, adjacent
roles, sub-sectors, cities -- and, when a job has nothing left to search, a
fresh batch for the ICP.

The model can wander, so every query it writes is checked: it must carry a
term from the ICP (a title word, an industry, a country or city), must not be
one we have already run, and is cleaned of site: filters (the pipeline adds
its own). None means the model was unavailable -- callers must not record
that as "no variations exist".
"""
import logging
import re
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 200
MAX_QUERY_WORDS = 9  # longer is the small model pasting every title into one line
QUEUE_WAIT_SECONDS = 60

_GENERIC = {"the", "and", "for", "with", "head", "lead", "senior", "manager", "director", "vice", "president",
            "chief", "officer", "global", "regional", "associate", "assistant", "executive", "services",
            "development", "solutions", "group", "team", "general", "principal"}
_SITE = re.compile(r"\s*-?(site|inurl|intitle):\S+", re.I)

def _schema(n: int) -> Dict[str, Any]:
    # the length caps stop the small model running one string on until the
    # token limit (it did, and the JSON never closed)
    return {"type": "object", "additionalProperties": False,
            "properties": {"queries": {"type": "array", "minItems": 1, "maxItems": n,
                                       "items": {"type": "string", "minLength": 5, "maxLength": 120}}},
            "required": ["queries"]}

_SYSTEM = ("You write Google search queries that find LinkedIn profiles of specific professionals. "
           "Reply only with JSON.")

_VARIATIONS = """This search now only returns people we already have:
{query}

Target people: {designations}
Industries: {industries}
Countries: {countries}

Example: for "Marketing Manager" London, new searches could be "Brand Manager" London FMCG, "Marketing Manager" Manchester retail, "Category Marketing Lead" London beverages.

Write {count} NEW searches for the same kind of people that Google would answer with DIFFERENT profiles. Each one pairs a job title with one extra word that changes the results. Change the angle: other job-title synonyms or adjacent roles, a sub-sector or specialism, a specific city, a skill or tool they list, a type of employer. Keep each under 150 characters. No site: filters. Do not repeat the search above.

JSON: {{"queries": ["...", "..."]}}"""

_FRESH = """Write {count} Google searches that find LinkedIn profiles of these people.

Target people: {designations}
Industries: {industries}
Countries: {countries}

These searches are used up, do not repeat them or make small changes to them:
{avoid}

Mix the angles: title synonyms, adjacent roles, sub-sectors, specific cities, skills they list, employer types. Each under 150 characters. No site: filters.

JSON: {{"queries": ["...", "..."]}}"""


def _fmt(values: Optional[Iterable[str]], limit: int = 12) -> str:
    vals = [str(v) for v in (values or []) if v]
    return ", ".join(vals[:limit]) or "any"


def on_topic_terms(icp: Dict[str, Any]) -> set:
    """Words that tie a query to this ICP: title words, industries, countries,
    and the cities the job deepens into."""
    from leads.geo import CITY_EXPANSIONS
    terms = set()
    for phrase in list(icp.get("designations") or []) + list(icp.get("industries") or []):
        for w in re.findall(r"[a-z0-9]+", str(phrase).lower()):
            if len(w) >= 3 and w not in _GENERIC:
                terms.add(w)
    for c in icp.get("countries") or []:
        terms.add(str(c).lower())
        terms.update(city.lower() for city in CITY_EXPANSIONS.get(c, []))
    return terms


def _key(q: str) -> frozenset:
    """'"Head of Insights" Singapore' and 'Head of Insights, Singapore' are one search."""
    return frozenset(re.findall(r"[a-z0-9]+", q.lower()))


def clean(raw: Iterable[Any], icp: Dict[str, Any], already: Iterable[str], count: int) -> List[str]:
    """Keep only queries that are on-topic, new, and well-formed."""
    terms = on_topic_terms(icp)
    seen = {_key(str(q)) for q in already}
    out: List[str] = []
    for q in raw or []:
        if not isinstance(q, str):
            continue
        q = " ".join(_SITE.sub(" ", q).replace(",", " ").split()).strip(" ;")
        if q.count('"') % 2:
            q = q.replace('"', "")
        if not q or len(q) > MAX_QUERY_CHARS or not 2 <= len(q.split()) <= MAX_QUERY_WORDS:
            continue
        low, key = q.lower(), _key(q)
        if key in seen:
            continue
        if not any(re.search(rf"\b{re.escape(t)}\b", low) for t in terms):
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= count:
            break
    return out


def _ask(prompt: str, count: int) -> Optional[List[Any]]:
    """The model's queries; None when it is unavailable. Output it garbles
    (truncated JSON) is retried once for a shorter list, then counts as
    "nothing usable" -- a garbled answer is not an outage."""
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, LocalSLMMalformedResponse, chat_json
    for attempt, n in enumerate((count, max(3, count // 2))):
        try:
            with queue_wait(QUEUE_WAIT_SECONDS):
                got = chat_json(system=_SYSTEM, user=prompt.replace(f"Write {count} ", f"Write {n} "),
                                max_tokens=120 + 60 * n, json_schema=_schema(n), timeout=120)
        except LocalSLMMalformedResponse as e:
            logger.info("query_variants_ai: garbled answer (attempt %d): %s", attempt + 1, e)
            continue
        except LocalSLMError as e:
            logger.warning("query_variants_ai: model unavailable: %s", e)
            return None
        except Exception as e:  # the gate's queue timeout, redis down, ...
            logger.warning("query_variants_ai: model call failed: %s", e)
            return None
        q = got.get("queries")
        return q if isinstance(q, list) else []
    return []


def _profile(icp: Dict[str, Any]) -> Dict[str, str]:
    return {"designations": _fmt(icp.get("designations")), "industries": _fmt(icp.get("industries")),
            "countries": _fmt(icp.get("countries"))}


def variations(query: str, icp: Dict[str, Any], already: Iterable[str] = (), count: int = 6) -> Optional[List[str]]:
    """New searches for the same people as a tapped-out query. None = model down."""
    raw = _ask(_VARIATIONS.format(query=query, count=count, **_profile(icp)), count)
    if raw is None:
        return None
    return clean(raw, icp, list(already) + [query], count)


def fresh_batch(icp: Dict[str, Any], used: Iterable[str] = (), count: int = 8) -> Optional[List[str]]:
    """A new batch for an ICP whose searches are all used up. None = model down."""
    used = list(used)
    avoid = "\n".join(f"- {q}" for q in used[-12:]) or "- (none yet)"
    raw = _ask(_FRESH.format(count=count, avoid=avoid, **_profile(icp)), count)
    if raw is None:
        return None
    return clean(raw, icp, used, count)
