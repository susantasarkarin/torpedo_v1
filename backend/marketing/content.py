"""Content engine (MARKETING_PLAN 3.6, 3.5.4).

content_items: one piece per BU x channel (linkedin, facebook, instagram, blog,
newsletter, quora) moving idea -> draft -> in_review -> approved -> scheduled ->
published (transitions checked; every move logged on the item).

Drafts: Qwen writes in the BU's voice (brand_voice, owner-approved) from code-picked
sources (anonymised won projects, services, content gaps, client questions).
check_claims() runs in code BEFORE review: guaranteed incidence / response, panel
sizes that are not in the approved stats, client names without "OK to reference",
the global and per-BU banned phrases. Nothing is published without approval unless
the owner sets that content type to auto (config marketing.content_auto).

Publishing: due, approved, scheduled items go to a publisher registered by the
platform integration (LinkedIn / Meta, M3). Without one -- or in shadow -- the item
is marked "would publish" and stays scheduled. Blog posts ship in the site zip.
"""
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from marketing import schema

CHANNELS = ("linkedin", "facebook", "instagram", "blog", "newsletter", "quora")
FLOW = {"idea": {"draft"}, "draft": {"in_review", "idea"}, "in_review": {"approved", "draft"},
        "approved": {"scheduled", "draft"}, "scheduled": {"published", "approved"}, "published": set()}
CHANNEL_LIMITS = {"linkedin": 3000, "facebook": 5000, "instagram": 2200, "quora": 6000, "blog": 20000, "newsletter": 15000}
_PUBLISHERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

# Brand voice sheets DRAFTED by Claude from the BU descriptions; status "proposed" until the owner approves.
BRAND_VOICE_DRAFTS = {
    "SFW": {"voice": "Practical fieldwork partner: fast, exact, numbers-first.",
            "tone": ["plain English", "confident, never boastful", "short sentences", "speak to agency project managers"],
            "do": ["state turnaround and coverage concretely", "explain the method in one line",
                   "end with one clear next step (share specs for a feasibility check)"],
            "dont": ["guarantee incidence, response or completes", "quote panel sizes not in the approved panel book",
                     "name clients without permission", "use hype words (revolutionary, best-in-class, world's leading)"],
            "banned_claims": ["guaranteed ir", "guaranteed incidence", "guaranteed completes", "100% response", "largest panel"]},
    "COGENTIX": {"voice": "Insight consultancy: curious, rigorous, human.",
                 "tone": ["thoughtful", "evidence-led", "warm", "speak to brand and insight managers"],
                 "do": ["lead with the business question", "cite method and sample in a sentence", "show one finding pattern"],
                 "dont": ["invent statistics", "name clients without permission", "promise outcomes"],
                 "banned_claims": ["guaranteed results", "guaranteed insights", "100% accurate"]},
    "BIM": {"voice": "Engineering-grade BIM services: precise, standards-aware, dependable.",
            "tone": ["technical but clear", "calm", "speak to architects, contractors and developers"],
            "do": ["name the standard / LOD / software", "state deliverables and timelines", "invite drawings for an estimate"],
            "dont": ["promise zero clashes", "name projects or clients without permission", "quote prices in posts"],
            "banned_claims": ["zero clashes guaranteed", "100% accurate model", "cheapest"]},
}
UNIVERSAL_BANNED = [r"\bguarantee[ds]?\b.{0,30}\b(ir|incidence|response|completes?|results?)\b", r"\bworld'?s (leading|largest|best)\b",
                    r"\bnumber one\b|\b#1\b"]
PANEL_SIZE = re.compile(r"\b(\d[\d,.]*\s*(?:k|m|lakh|lac|million|thousand)?\+?)\s*(?:panel(?:ists)?|respondents|members|panel members)\b", re.I)


def transition(item: Dict[str, Any], to: str, actor: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    cur = item.get("status", "idea")
    if to not in FLOW.get(cur, set()):
        raise ValueError(f"cannot move {cur} -> {to}")
    if to == "scheduled" and not item.get("scheduled_for"):
        raise ValueError("set scheduled_for before scheduling")
    if to in ("in_review", "approved") and (item.get("claim_problems") or []):
        raise ValueError("fix the flagged claims first: " + "; ".join(item["claim_problems"][:3]))
    now = now or datetime.utcnow()
    hist = list(item.get("history") or []) + [{"from": cur, "to": to, "by": actor, "at": now}]
    return {"status": to, "history": hist, "updated_at": now, **({"approved_by": actor, "approved_at": now} if to == "approved" else {})}


def check_claims(text: str, bu: str, *, voice: Optional[Dict[str, Any]] = None, approved_stats: Optional[List[str]] = None,
                 clients: Optional[List[Tuple[str, bool]]] = None, global_banned: Optional[List[str]] = None,
                 channel: Optional[str] = None) -> List[str]:
    """Code check before review (4.3 Content). clients: [(name, ok_to_reference)]."""
    t, low, out = text or "", (text or "").lower(), []
    for pat in UNIVERSAL_BANNED:
        m = re.search(pat, low)
        if m:
            out.append(f"banned claim: '{t[m.start():m.end()]}'")
    for phrase in list((voice or {}).get("banned_claims") or []) + list(global_banned or []):
        if phrase and phrase.lower() in low:
            out.append(f"banned phrase for {bu}: '{phrase}'")
    ok_stats = {re.sub(r"[\s,]", "", s.lower()) for s in (approved_stats or [])}
    for m in PANEL_SIZE.finditer(t):
        if re.sub(r"[\s,]", "", m.group(1).lower()) not in ok_stats:
            out.append(f"panel size '{m.group(0)}' is not in the approved panel stats")
    for name, ok in clients or []:
        if name and len(name) > 2 and not ok and re.search(rf"\b{re.escape(name)}\b", t, re.I):
            out.append(f"names client '{name}' without OK to reference")
    if channel and len(t) > CHANNEL_LIMITS.get(channel, 10 ** 6):
        out.append(f"{len(t)} characters > {channel} limit {CHANNEL_LIMITS[channel]}")
    return sorted(set(out))


def utm_link(url: str, *, bu: str, channel: str, campaign: str, content: Optional[str] = None) -> str:
    """3.5.4: tagged links for posts and the team's Quora answers."""
    p = urlparse(url)
    q = dict(parse_qsl(p.query))
    q.update({"utm_source": channel, "utm_medium": "social" if channel != "newsletter" else "email",
              "utm_campaign": re.sub(r"[^a-z0-9_-]+", "-", f"{bu}-{campaign}".lower()).strip("-")})
    if content:
        q["utm_content"] = re.sub(r"[^a-z0-9_-]+", "-", content.lower()).strip("-")
    return urlunparse(p._replace(query=urlencode(q)))


# ------------------------------------------------------------------ sources for Qwen (code-picked, anonymised)
def sources(gd: Callable, bu: str, limit: int = 5) -> Dict[str, Any]:
    ea, crm = gd(schema.DB), gd("crm_db")
    won = []
    for o in crm["opportunities"].find({"status": "won", "bu": bu}).sort("won_at", -1).limit(30):
        r = (o.get("metadata") or {}).get("rfq") or {}
        acc = crm["accounts"].find_one({"_id": o.get("account_id")}, {"name": 1, "ok_to_reference": 1}) if o.get("account_id") else None
        won.append({"countries": r.get("countries") or r.get("country"), "n": r.get("n"), "loi": r.get("loi_minutes"),
                    "method": r.get("methodology"),
                    "client": (acc or {}).get("name") if (acc or {}).get("ok_to_reference") else "a client"})
    gaps = [g.get("topic") or g.get("query") for g in ea["content_gaps"].find({"bu": bu, "status": {"$in": ["open", None]}}).limit(limit)]
    return {"won_projects": [w for w in won if w["countries"] or w["n"]][:limit], "gaps": gaps}


def draft(item: Dict[str, Any], gd: Callable, *, qwen: Optional[Callable] = None) -> Dict[str, Any]:
    """Qwen draft (P3, night lane) -> claims checked -> in_review. Returns the fields to set."""
    import json
    voice = (gd(schema.DB)["brand_voice"].find_one({"bu": item["bu"], "status": "approved"}) or
             dict(BRAND_VOICE_DRAFTS.get(item["bu"], {}), status="proposed"))
    src = sources(gd, item["bu"])
    brief = {"bu": item["bu"], "channel": item["channel"], "topic": item.get("title") or item.get("topic"),
             "voice": {k: voice.get(k) for k in ("voice", "tone", "do", "dont")}, "facts": src,
             "max_chars": min(CHANNEL_LIMITS.get(item["channel"], 3000), 1800), "link": item.get("link")}
    system = ("Write one social post / article draft for a B2B research company in the given voice. Use only the facts "
              "given; never invent numbers, client names or panel sizes. Reply JSON only: {\"title\", \"body\", \"hashtags\": [..]}.")
    if qwen is None:
        from platform_core import qwen_gateway
        from marketing import config as mcfg
        mcfg.register_qwen_tasks()
        qwen = lambda: qwen_gateway.run(task="marketing_decision_p3", system=system, body=json.dumps(brief, default=str),
                                        schema={"type": "object", "required": ["body"]}, bu=item["bu"],
                                        ref={"collection": "email_automation.content_items", "id": str(item.get("_id"))})
    res = qwen()
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict) or not data.get("body"):
        return {"draft_error": f"no draft ({(res or {}).get('status')})", "updated_at": datetime.utcnow()}
    body = data["body"].strip()
    tags = [h for h in (data.get("hashtags") or []) if isinstance(h, str)][:5]
    return {"body": body, "title": data.get("title") or item.get("title"), "hashtags": tags, "drafted_by": "qwen",
            "voice_status": voice.get("status"), "updated_at": datetime.utcnow()}


def register_publisher(channel: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    """A platform integration registers fn(item) -> {"post_id", "url"}."""
    _PUBLISHERS[channel] = fn


def publish_due(gd: Optional[Callable] = None, *, now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    now = now or datetime.utcnow()
    col = gd(schema.DB)["content_items"]
    rep = {"published": 0, "would_publish": 0, "errors": []}
    from marketing import config as mcfg
    for it in col.find({"status": "scheduled", "scheduled_for": {"$lte": now}}):
        if mcfg.killed(cfg, it.get("bu")):
            continue
        if it.get("claim_problems"):
            rep["errors"].append(f"{it['_id']}: claims flagged"); continue
        pub = _PUBLISHERS.get(it["channel"])
        live = cfg.get("mode") == "live" and (cfg.get("action_modes") or {}).get(f"content:{it['channel']}") == "live"
        if not (pub and live):
            col.update_one({"_id": it["_id"]}, {"$set": {"would_publish_at": now, "shadow_reason":
                                                         "shadow mode" if not live else f"no publisher for {it['channel']}"}})
            rep["would_publish"] += 1
            continue
        try:
            res = pub(it)
            col.update_one({"_id": it["_id"]}, {"$set": {"status": "published", "published_at": now, "platform_post_id": res.get("post_id"),
                                                         "url": res.get("url"), "updated_at": now},
                                                "$push": {"history": {"from": "scheduled", "to": "published", "by": "publisher", "at": now}}})
            rep["published"] += 1
        except Exception as e:
            rep["errors"].append(f"{it['_id']}: {str(e)[:120]}")
    return rep


def performance(gd: Callable, *, days: int = 90, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """3.6.4 per piece: reach, engagement, clicks (social metrics) + leads / RFQs from touchpoints carrying its utm_content."""
    now = now or datetime.utcnow()
    ea = gd(schema.DB)
    out = []
    for it in ea["content_items"].find({"status": "published", "published_at": {"$gte": now - timedelta(days=days)}}):
        m = {"reach": 0.0, "engagement": 0.0, "clicks": 0.0}
        for r in ea["social_metrics_daily"].find({"entity_id": it.get("platform_post_id")}):
            for k in m:
                m[k] += float(r.get(k) or 0)
        tag = it.get("utm_content")
        leads = {t["lead_id"] for t in ea["touchpoints"].find({"utm.utm_content": tag})} if tag else set()
        rfqs = gd("crm_db")["opportunities"].count_documents({"lead_id": {"$in": sorted(leads)}}) if leads else 0
        out.append({"id": str(it["_id"]), "bu": it.get("bu"), "channel": it["channel"], "title": it.get("title"),
                    "topic": it.get("topic"), **m, "leads": len(leads), "rfqs": rfqs})
    return sorted(out, key=lambda x: (-x["rfqs"], -x["leads"], -x["clicks"]))


def seed_brand_voice(gd: Optional[Callable] = None, now: Optional[datetime] = None) -> int:
    """Claude's drafts as 'proposed' brand_voice rows (owner approves / edits). Never overwrites an existing row."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    col, n = gd(schema.DB)["brand_voice"], 0
    for bu, v in BRAND_VOICE_DRAFTS.items():
        if not col.find_one({"bu": bu}):
            col.insert_one(schema.stamp({**v, "status": "proposed", "drafted_by": "claude"}, bu=bu, source="brand_voice_draft", now=now))
            n += 1
    return n


def claims_for(gd: Callable, item: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    """check_claims with the live voice, approved panel stats and the account list."""
    if cfg is None:
        from platform_core import config_store
        cfg = config_store.get("marketing")
    voice = gd(schema.DB)["brand_voice"].find_one({"bu": item.get("bu")}) or BRAND_VOICE_DRAFTS.get(item.get("bu"), {})
    clients = [(a.get("name"), bool(a.get("ok_to_reference"))) for a in
               gd("crm_db")["accounts"].find({"merged_into": {"$exists": False}}, {"name": 1, "ok_to_reference": 1}) if a.get("name")]
    text = " ".join(str(item.get(k) or "") for k in ("title", "body"))
    return check_claims(text, item.get("bu"), voice=voice, approved_stats=cfg.get("approved_panel_stats") or [],
                        clients=clients, global_banned=cfg.get("banned_claims") or [], channel=item.get("channel"))
