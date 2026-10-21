"""
Email addresses for generated leads, from structures we can trust (owner,
2026-09-30: "for the leads generated why dont we try to make the email id's.
If you dont get it then we would use hunter.io to get the email structure.
You need to use email structure of those mails which has no bounce. After you
make the email pass it through AI and see its correctness").

For a lead with a name and a company domain:

  1. structure -- in this order, and nothing weaker:
       mail_pool   our own mail: addresses at that domain that never bounced
                   (app/services/email_structure.py; one that wrote to us
                   counts double). Two or more agreeing, or one that wrote to us.
       proven      a pattern-store entry that has been sent to without bouncing
     Neither -> Skrapp (leads/skrapp_client.py) is asked for this person's
     verified address; only a "valid" answer is used, and it needs no model
     check. Hunter was removed 2026-10-15 (owner: Skrapp in its place).
     Nothing -> no address. Guessed patterns bounced heavily (45% in
     August), so a lead is left without one and retried later.
  2. the address is built from the lead's name;
  3. the local model checks it against real addresses of the same company:
     is the name rendered right, is the domain the company's? A correction is
     taken only if it stays on the domain, fits a known structure and never
     bounced. An address the model doubts is kept aside for a person
     (email_build.status "ai_doubt"), not put on the lead. A model outage
     is retried, never recorded as a verdict.

State on the lead: email_build {status, structure, source, candidate, ai, ...}.
"""
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)

RETRY_DAYS = {"no_structure": 30, "skrapp_unverified": 90, "no_name": 3650, "ai_doubt": 3650, "bounced_before": 3650,
              "model_unavailable": 0}
WEAK_SOURCES = ("guess",)


def _client():
    from pymongo import MongoClient
    return MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------
def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


_TITLE_WORDS = re.compile(
    r"\b(manager|director|head|officer|engineer|designer|architect|lead|consultant|analyst|founder|"
    r"president|executive|specialist|coordinator|associate|intern|team|department|hr|sales|marketing|"
    r"research|insights|ceo|cfo|cto|coo|cmo|vp|partner|owner|admin|support|recruiter|hiring)\b", re.I)


def is_person_name(lead: Dict[str, Any]) -> bool:
    """'Creative Design Manager' is a job title the search picked up as a
    name; building 'creative.manager@capgemini.com' from it is nonsense."""
    name = (lead.get("name") or "").strip()
    title = (lead.get("title") or "").strip().lower()
    if not name or (title and name.lower() == title):
        return False
    return not _TITLE_WORDS.search(re.sub(r"\(.*?\)", " ", name))


def company_domain_for(client, lead: Dict[str, Any]) -> str:
    """The lead's company email domain. Some leads carry the LinkedIn host
    ('in.linkedin.com') instead; then the company's name is looked up among the
    domains our own mail knows ('Ipsos' -> ipsos.com)."""
    from leads.email_pattern_system import company_email_domain
    d = company_email_domain(lead.get("company_domain") or "")
    if d:
        return d
    name = (lead.get("company_name") or "").strip()
    if len(name) < 3:
        return ""
    hits = list(client["email_automation"]["email_domain_structures"].find(
        {"company_name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}, {"people": 1}).limit(5))
    if hits:
        return company_email_domain(max(hits, key=lambda h: h.get("people") or 0)["_id"])
    return ai_company_domain(client, name)


_DOMAIN_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": {"email_domain": {"type": "string", "maxLength": 60}},
                  "required": ["email_domain"]}


def _has_mx(domain: str) -> bool:
    try:
        import dns.resolver
        return bool(dns.resolver.resolve(domain, "MX", lifetime=8))
    except Exception:
        return False


def domain_matches_name(domain: str, company: str) -> bool:
    """'nike.com' for 'Nike'; 'barclays.co.uk' for 'Barclays UK' -- the model
    may not hand a company someone else's domain."""
    from app.services.rfq_from_mail import registrable_root
    root = re.sub(r"[^a-z0-9]", "", registrable_root(domain))
    squashed = re.sub(r"[^a-z0-9]", "", _ascii(company).lower())
    first = re.sub(r"[^a-z0-9]", "", _ascii(company).lower().split()[0]) if company.split() else ""
    return len(root) >= 3 and (root in squashed or squashed in root or (len(first) >= 4 and first in root))


def ai_company_domain(client, company: str) -> str:
    """The company's email domain from the local model, kept only if it matches
    the name and actually receives mail (MX). Cached per company name."""
    from leads.email_pattern_system import company_email_domain
    key = " ".join(company.lower().split())
    cache = client["email_automation"]["company_domains"]
    hit = cache.find_one({"_id": key})
    if hit:
        return hit.get("domain") or ""
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    try:
        with queue_wait(120, priority="bulk"):
            got = chat_json(system="You know companies' email domains. Reply only with JSON.",
                            user=f"Company: {company}\nWhat domain do this company's employees use for email? "
                                 f"If it is not one specific company (a description, a list of employers, "
                                 f"an alumni group), answer an empty email_domain.",
                            max_tokens=60, json_schema=_DOMAIN_SCHEMA, timeout=60)
    except (LocalSLMError, Exception):
        return ""  # an outage is not an answer; asked again next time
    domain = company_email_domain(str(got.get("email_domain") or ""))
    # the model's own yes/no contradicted its answer (known_company false,
    # domain canva.com); the name match and a live mail server decide
    ok = bool(domain) and domain_matches_name(domain, company) and _has_mx(domain)
    cache.update_one({"_id": key}, {"$set": {"domain": domain if ok else "", "proposed": domain,
                                             "source": "ai+mx" if ok else "rejected",
                                             "at": datetime.utcnow()}}, upsert=True)
    return domain if ok else ""


def lead_names(lead: Dict[str, Any]) -> Tuple[str, str]:
    """('jyoti', 'halder') from the lead. Initials and bracketed nicknames are
    dropped: 'A L Jagannath (Jaggi)' -> ('jagannath', '')."""
    from app.services.email_structure import split_name
    name = re.sub(r"\b(dr|mr|mrs|ms|miss|prof|er|ca|phd|mba|cfa|pmp|jr|sr|ii|iii)\b\.?", " ",
                  _ascii(lead.get("name") or ""), flags=re.I)
    first, last = split_name(name)
    if not first:
        f = re.sub(r"[^a-z]", "", _ascii(lead.get("first_name") or "").lower())
        l = re.sub(r"[^a-z]", "", _ascii(lead.get("last_name") or "").lower())
        first, last = (f, l) if len(f) > 1 else ("", "")
    return first, last


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------
def mail_pool_structure(client, domain: str) -> Optional[Dict[str, Any]]:
    """The bounce-free structure our own mail shows for this domain."""
    from app.services.email_structure import domain_evidence
    col = client["email_automation"]["email_address_structures"]
    counts = domain_evidence(col, [domain]).get(domain)
    if not counts:
        return None
    form, n = counts.most_common(1)[0]
    total = sum(counts.values())
    if n < 2 or n / total < 0.6:  # n counts double for someone who wrote to us
        return None
    examples = [{"email": d["_id"], "name": d.get("name") or ""}
                for d in col.find({"domain": domain, "bounced": {"$ne": True}, "pattern_form": form},
                                  {"name": 1}).sort("wrote_to_us", -1).limit(3)]
    return {"form": form, "source": "mail_pool", "confidence": round(min(0.9, 0.5 + 0.1 * n) * n / total, 2),
            "examples": examples}


def proven_pattern(client, domain: str) -> Optional[Dict[str, Any]]:
    """A pattern-store entry that mail has actually gone to without bouncing."""
    p = client["email_automation"]["email_patterns"].find_one({"domain": domain})
    # 3,123 of 11,602 entries have send counts but no pattern (the send
    # tracker upserts them); p["pattern"] raised KeyError and killed the whole
    # builder run whenever such a domain came up (2026-10-14).
    if not p or not p.get("pattern") or p.get("pattern_blacklisted") or p.get("high_bounce_risk"):
        return None
    sends, bounces = int(p.get("send_count") or 0), int(p.get("bounce_count") or 0)
    if sends >= 2 and bounces / max(1, sends + bounces) < 0.2:
        return {"form": p["pattern"].split("@")[0], "source": "proven", "confidence": 0.85,
                "examples": [{"email": e, "name": ""} for e in (p.get("examples") or [])[:3]]}
    # A looked-up pattern (Skrapp now; Hunter's stored answers from before
    # 2026-10-15 stay valid data).
    if p.get("source") in ("skrapp", "hunter_io") and p.get("pattern"):
        return {"form": p["pattern"].split("@")[0], "source": p["source"], "confidence": 0.8,
                "examples": [{"email": e, "name": ""} for e in (p.get("examples") or [])[:3]]}
    return None


def skrapp_address(client, first: str, last: str, domain: str, now: datetime,
                   bounced: set) -> Dict[str, Any]:
    """Skrapp's verified address for one person -> {"rec": ..., "set_fields": ...}."""
    from leads import skrapp_client
    r = skrapp_client.find(client, first, last, domain=domain, now=now)
    st = r.get("status")
    if st != "found":
        why = {"not_found": "skrapp_has_none", "not_configured": "skrapp_not_configured",
               "monthly_limit": "skrapp_monthly_limit"}.get(st, "skrapp_error")
        return {"rec": {"status": "no_structure", "why": why}, "set_fields": {}}
    email = r["email"]
    rec = {"source": "skrapp", "candidate": email, "skrapp_quality": r.get("quality")}
    pattern = r.get("pattern")
    if not pattern and r.get("quality") in skrapp_client.USABLE:
        # One verified address teaches the company's structure for everyone
        # else we have there -- the reason leads are worked company by company.
        from app.services.email_structure import structure_of
        pattern = structure_of(email, first, last)[1]
    if pattern:
        form = pattern if "@" in pattern else pattern + "@{domain}"
        rec["structure"] = form.replace("{domain}", domain)
        client["email_automation"]["email_patterns"].update_one({"domain": domain}, {
            "$set": {"domain": domain, "pattern": form, "confidence": 0.8, "source": "skrapp",
                     "last_verified": now},
            "$setOnInsert": {"discovered_at": now}, "$addToSet": {"examples": email}}, upsert=True)
    if email in bounced:
        rec["status"] = "bounced_before"
    elif address_problem(email) or not email.endswith("@" + domain):
        rec["status"] = "ai_doubt"; rec["why"] = address_problem(email) or "skrapp address is off the company domain"
    elif r.get("quality") not in skrapp_client.USABLE:
        rec["status"] = "skrapp_unverified"; rec["why"] = f"skrapp quality: {r.get('quality')}"
    else:
        rec["status"] = "built"; rec["email"] = email
        return {"rec": rec, "set_fields": {"email": email, "email_status": "Valid", "email_source": "skrapp",
                                           "email_pattern_confidence": 0.9}}
    return {"rec": rec, "set_fields": {}}


def find_structure(client, domain: str, now: datetime) -> Tuple[Optional[Dict[str, Any]], str]:
    s = mail_pool_structure(client, domain)
    if s:
        return s, "mail_pool"
    s = proven_pattern(client, domain)
    if s:
        return s, s["source"]
    return None, "no_known_structure"


# ---------------------------------------------------------------------------
# the AI check
# ---------------------------------------------------------------------------
_SCHEMA = {"type": "object", "additionalProperties": False,
           "properties": {"domain_is_company": {"type": "boolean"},
                          "has_special_characters": {"type": "boolean"},
                          "email_correct": {"type": "boolean"},
                          "corrected_email": {"type": "string", "maxLength": 80},
                          "reason": {"type": "string", "maxLength": 160}},
           "required": ["domain_is_company", "has_special_characters", "email_correct", "corrected_email",
                        "reason"]}

_SYSTEM = ("You check business email addresses built from a person's name and their company's email "
           "pattern. Reply only with JSON.")

_ASK = """Person: {name}
Title: {title}
Company: {company}
Company email domain: {domain}
Pattern this company uses: {structure}
Real addresses at this company:
{examples}

Built address: {candidate}

1. Is {domain} really this company's email domain (not a parent, a reseller, or a different company)?
2. Is the built address the right rendering of this person's name in that pattern (first and last name in the right places, no nickname, no initials mistaken for names)?
3. Does the address contain anything that does not belong in an email address: accents, spaces, apostrophes, brackets, commas or other special characters? Before the @ only letters, digits and . _ - are allowed.
If it is wrong, give the corrected address in the same pattern, otherwise repeat the built address."""


_LOCAL_OK = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
_DOMAIN_OK = r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+"


def address_problem(email: str) -> Optional[str]:
    """Why an address is not clean, or None. Before the @: letters, digits and
    . _ - only, none at either end or doubled; plain ASCII throughout."""
    if not email or email.count("@") != 1:
        return "not one @"
    local, domain = email.split("@")
    if not email.isascii():
        return "non-ASCII character"
    if len(local) > 64 or not re.fullmatch(_LOCAL_OK, local):
        return "special character before the @"
    if not re.fullmatch(_DOMAIN_OK, domain):
        return "bad domain"
    return None


def ai_check(lead: Dict[str, Any], domain: str, structure: Dict[str, Any], candidate: str,
             first: str, last: str, bounced: set) -> Dict[str, Any]:
    """{'verdict': ok|corrected|doubt|domain_doubt|unavailable, 'email', 'reason'}."""
    from app.services.email_structure import structure_of
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    examples = "\n".join(f"- {e['email']}" + (f" ({e['name']})" if e.get("name") else "")
                         for e in structure.get("examples") or []) or "- (none on file)"
    try:
        with queue_wait(120, priority="bulk"):
            got = chat_json(system=_SYSTEM, user=_ASK.format(
                name=lead.get("name") or f"{first} {last}", title=(lead.get("title") or "")[:80],
                company=lead.get("company_name") or "", domain=domain, examples=examples,
                structure=structure["form"] + "@" + domain, candidate=candidate),
                max_tokens=160, json_schema=_SCHEMA, timeout=120)
    except LocalSLMError as e:
        return {"verdict": "unavailable", "email": candidate, "reason": str(e)[:160]}
    except Exception as e:  # the gate's queue timeout
        return {"verdict": "unavailable", "email": candidate, "reason": str(e)[:160]}
    reason = str(got.get("reason") or "")[:160]
    if got.get("has_special_characters"):
        return {"verdict": "doubt", "email": candidate, "reason": "model saw special characters: " + reason}
    if got.get("domain_is_company") is False:
        return {"verdict": "domain_doubt", "email": candidate, "reason": reason}
    if got.get("email_correct"):
        return {"verdict": "ok", "email": candidate, "reason": reason}
    fix = str(got.get("corrected_email") or "").strip().lower()
    # a correction must stay on the domain, fit a structure of this person's
    # name, and never have bounced -- the model cannot invent an address
    if fix and fix != candidate and fix.endswith("@" + domain) and fix not in bounced             and not address_problem(fix):
        label, _ = structure_of(fix, first, last)
        if label != "unknown" and not label.startswith("role:"):
            return {"verdict": "corrected", "email": fix, "reason": reason}
    return {"verdict": "doubt", "email": candidate, "reason": reason}


# ---------------------------------------------------------------------------
# the batch
# ---------------------------------------------------------------------------
def pending_query(now: datetime) -> Dict[str, Any]:
    return {
        "company_domain": {"$nin": [None, ""]},
        # a company that fits none of our campaigns is not worth a lookup
        "company_icp_type": {"$ne": "other"},
        "$and": [
            {"$or": [{"email": {"$in": [None, ""]}}, {"email": {"$exists": False}},
                     {"email_source": {"$in": list(WEAK_SOURCES)}, "outreach_campaign_id": {"$exists": False}}]},
            {"$or": [{"email_build.next_try_at": {"$exists": False}}, {"email_build.next_try_at": {"$lte": now}}]},
        ],
    }


def build_for_lead(client, lead: Dict[str, Any], now: datetime, bounced: set) -> Dict[str, Any]:
    """Decide one lead. Returns the email_build record (and writes it)."""
    from leads.email_pattern_system import company_email_domain, render_pattern_email
    le = client["email_automation"]["leads_enriched"]
    domain = company_domain_for(client, lead)
    first, last = lead_names(lead)
    rec: Dict[str, Any] = {"at": now, "domain": domain}
    set_fields: Dict[str, Any] = {}
    if domain and domain != company_email_domain(lead.get("company_domain") or ""):
        set_fields["company_domain"] = domain
        rec["domain_from"] = "company name"
    if not is_person_name(lead):
        rec["status"] = "no_name"; rec["why"] = "the name is a job title, not a person"
    elif not domain:
        rec["status"] = "no_structure"; rec["why"] = "no usable company domain"
    elif not first:
        rec["status"] = "no_name"
    else:
        structure, why = find_structure(client, domain, now)
        if not structure:
            # No structure we trust: ask Skrapp for this person's verified
            # address (owner, 2026-10-15: Skrapp replaces Hunter).
            sk = skrapp_address(client, first, last, domain, now, bounced)
            rec.update(sk["rec"])
            set_fields = {**set_fields, **sk["set_fields"]}
        else:
            form = structure["form"] if "@" in structure["form"] else structure["form"] + "@{domain}"
            candidate = render_pattern_email(form, first, last, domain)
            rec.update({"structure": structure["form"] + "@" + domain, "source": structure["source"],
                        "candidate": candidate})
            if not candidate:
                rec["status"] = "no_name"; rec["why"] = "pattern needs a surname" if not last else "unrenderable"
            elif candidate in bounced:
                rec["status"] = "bounced_before"
            elif address_problem(candidate):
                rec["status"] = "ai_doubt"; rec["why"] = address_problem(candidate)
            else:
                check = ai_check(lead, domain, structure, candidate, first, last, bounced)
                rec["ai"] = {"verdict": check["verdict"], "reason": check["reason"]}
                if check["verdict"] == "unavailable":
                    rec["status"] = "model_unavailable"
                elif check["verdict"] in ("ok", "corrected"):
                    rec["status"] = "built"
                    rec["email"] = check["email"]
                    set_fields = {**set_fields, "email": check["email"], "email_status": "Predicted",
                                  "email_source": structure["source"],
                                  "email_pattern_confidence": structure["confidence"],
                                  "email_ai_checked": True}
                else:
                    rec["status"] = "ai_doubt" if check["verdict"] == "doubt" else "domain_doubt"
    days = RETRY_DAYS.get(rec["status"], 3650 if rec["status"] in ("built", "domain_doubt") else 1)
    if rec.get("why") in ("skrapp_monthly_limit", "skrapp_not_configured", "skrapp_error"):
        days = 1  # waiting on Skrapp's quota or key, not on missing evidence
    rec["next_try_at"] = now + timedelta(days=days) if days else now + timedelta(minutes=30)
    le.update_one({"_id": lead["_id"]}, {"$set": {"email_build": rec, **set_fields, "updated_at": now}})
    return rec


def pending_by_company(le, now: datetime, limit: int) -> List[Dict[str, Any]]:
    """Waiting leads, the companies with the most of them first: the first
    lead at a company finds (or buys) its structure, the rest reuse it at no
    cost. Within a company, newest first."""
    groups = le.aggregate([
        {"$match": pending_query(now)},
        {"$group": {"_id": {"$toLower": {"$ifNull": ["$company_name", "$company_domain"]}},
                    "n": {"$sum": 1}, "newest": {"$max": "$created_at"}}},
        {"$sort": {"n": -1, "newest": -1}},
        {"$limit": limit}], allowDiskUse=True)
    out: List[Dict[str, Any]] = []
    for g in groups:
        if not g["_id"]:
            continue
        rx ={"$regex": f"^{re.escape(g['_id'] or '')}$", "$options": "i"}
        q = {**pending_query(now), "$or": [{"company_name": rx}, {"company_domain": rx}]}
        out += list(le.find(q).sort("created_at", -1).limit(limit - len(out)))
        if len(out) >= limit:
            break
    return out


def run(client=None, limit: int = 15, now: Optional[datetime] = None) -> Dict[str, Any]:
    client = client or _client()
    now = now or datetime.utcnow()
    from app.services.email_structure import bounced_addresses
    bounced = bounced_addresses(client)
    le = client["email_automation"]["leads_enriched"]
    stats: Dict[str, Any] = {}
    unavailable = 0
    for lead in pending_by_company(le, now, limit):
        rec = build_for_lead(client, lead, now, bounced)
        stats[rec["status"]] = stats.get(rec["status"], 0) + 1
        if rec["status"] == "model_unavailable":
            unavailable += 1
            if unavailable >= 3:  # the model is down; stop rather than churn
                break
        else:
            unavailable = 0
    logger.info("[EmailBuilder] %s", stats)
    return stats
