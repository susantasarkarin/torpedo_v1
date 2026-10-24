"""Landing-page visits (CRM plan 3.12). Pure.

Visitor = first-party cookie id. A mail link carries ?r=<token> (HMAC of the
contact id), which ties the cookie to that contact; a form fill ties it to a
lead. IPs are stored truncated (/24) for company lookup, never in full
(DPDP / GDPR minimisation).
"""
import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "mode": "shadow",
    "allowed_redirect_hosts": ["surveyfieldwork.com", "www.surveyfieldwork.com", "business.surveyfieldwork.com", "cogentixresearch.com",
                               "www.cogentixresearch.com", "bimwavesolutions.com", "www.bimwavesolutions.com",
                               "torpedo.cogentixresearch.com"],
    "site_bu": {"surveyfieldwork.com": "SFW", "cogentixresearch.com": "COGENTIX", "bimwavesolutions.com": "BIM"},
    # the company websites (Hostinger / Cloudflare), each with its first-party tracker host t.<domain>
    "sites": [
        {"domain": "business.surveyfieldwork.com", "bu": "SFW", "aliases": ["www.business.surveyfieldwork.com"], "tags": {}},
        {"domain": "cogentixresearch.com", "bu": "COGENTIX", "aliases": ["www.cogentixresearch.com"], "tags": {}},
        {"domain": "bimwavesolutions.com", "bu": "BIM", "aliases": ["www.bimwavesolutions.com"], "tags": {}},
    ],
    "staging_hosts": {},               # e.g. {"staging-sfw.torpedo.cogentixresearch.com": "business.surveyfieldwork.com"}
    "site_silence_alert_hours": 24,
    "high_intent_paths": ["/pricing", "/panel-book", "/panel", "/rate", "/contact"],
    "weights": {"high_intent_page": 50, "repeat_visit_7d": 40, "time_over_60s": 20, "bounce": -10},
    "high_score": 50,
    "form_reminder_after_hours": 2,
    "reverse_ip_provider": None,       # owner: none in the codebase (AUDIT 3.12) -- proposal in PROGRESS
    "tags": {"google_ads_id": "", "linkedin_partner_id": "", "meta_pixel_id": ""},   # owner supplies IDs
    "audience_window_days": 30,
}


def site_for_host(host: str, cfg=DEFAULTS) -> Optional[Dict[str, Any]]:
    """The configured company site for a hostname (domain, www/aliases, staging copy)."""
    h = (host or "").lower().strip(".")
    h = (cfg.get("staging_hosts") or {}).get(h, h)
    for s in cfg.get("sites") or []:
        if h == s["domain"] or h in (s.get("aliases") or []):
            return s
    return None


def _key(secret: str) -> bytes:
    return hashlib.sha256(("web-link:" + secret).encode()).digest()


def make_token(contact_id: str, secret: str) -> str:
    sig = hmac.new(_key(secret), contact_id.encode(), hashlib.sha256).digest()[:9]
    return base64.urlsafe_b64encode(contact_id.encode()).decode().rstrip("=") + "." + \
        base64.urlsafe_b64encode(sig).decode().rstrip("=")


def read_token(token: str, secret: str) -> Optional[str]:
    try:
        a, b = token.split(".", 1)
        cid = base64.urlsafe_b64decode(a + "=" * (-len(a) % 4)).decode()
        want = base64.urlsafe_b64encode(hmac.new(_key(secret), cid.encode(), hashlib.sha256).digest()[:9]).decode().rstrip("=")
        return cid if hmac.compare_digest(want, b) else None
    except Exception:
        return None


def ip_prefix(ip: str) -> Optional[str]:
    parts = (ip or "").split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    if ":" in (ip or ""):
        return ":".join(ip.split(":")[:3]) + "::/48"
    return None


def safe_redirect(url: str, cfg=DEFAULTS) -> Optional[str]:
    from urllib.parse import urlparse
    u = urlparse(url or "")
    if u.scheme in ("http", "https") and (u.hostname or "").lower() in cfg["allowed_redirect_hosts"]:
        return url
    return None


EVENT_TYPES = {"page_view", "time_on_page", "scroll", "cta_click", "form_start", "form_submit"}


def clean_event(e: Dict[str, Any], *, visitor: str, ip: str, ua: str, now: datetime, cfg=DEFAULTS) -> Optional[Dict[str, Any]]:
    if e.get("type") not in EVENT_TYPES or not visitor:
        return None
    from urllib.parse import parse_qs, urlparse
    url = str(e.get("url") or "")[:500]
    u = urlparse(url)
    raw_host = (u.hostname or "").lower()
    site = site_for_host(raw_host, cfg)
    host = site["domain"] if site else raw_host.removeprefix("www.")
    utm = {k: v[0][:100] for k, v in parse_qs(u.query).items() if k.startswith("utm_")}
    return {"visitor_id": visitor[:64], "type": e["type"], "url": url, "host": host, "path": u.path[:200],
            "bu": site["bu"] if site else cfg["site_bu"].get(host), "utm": utm, "referrer": str(e.get("referrer") or "")[:300],
            "value": e.get("value") if isinstance(e.get("value"), (int, float)) else None,
            "form_email": (str(e.get("email"))[:200].lower() if e.get("type") in ("form_start", "form_submit")
                           and "@" in str(e.get("email") or "") else None),
            "consent": bool(e.get("consent")), "ip_prefix": ip_prefix(ip), "ua": ua[:200], "at": now}


def score(events: List[Dict[str, Any]], now: datetime, cfg=DEFAULTS) -> Dict[str, Any]:
    w = cfg["weights"]
    pts, why = 0, []
    if any(any(e.get("path", "").startswith(p) for p in cfg["high_intent_paths"]) for e in events):
        pts += w["high_intent_page"]; why.append("pricing / panel-book page")
    days = {e["at"].date() for e in events if e["type"] == "page_view" and now - e["at"] <= timedelta(days=7)}
    if len(days) >= 2:
        pts += w["repeat_visit_7d"]; why.append(f"{len(days)} visit days in 7")
    if any(e["type"] == "time_on_page" and (e.get("value") or 0) > 60 for e in events):
        pts += w["time_over_60s"]; why.append("time on page > 60 s")
    views = [e for e in events if e["type"] == "page_view"]
    if len(views) == 1 and not any(e["type"] in ("time_on_page", "cta_click", "scroll") for e in events):
        pts += w["bounce"]; why.append("bounce")
    return {"score": pts, "why": why, "level": "high" if pts >= cfg["high_score"] else "medium" if pts >= 20 else "low"}


def follow_up(visitor: Dict[str, Any], events: List[Dict[str, Any]], now: datetime, cfg=DEFAULTS) -> Optional[Dict[str, Any]]:
    """3.12 step 6. visitor: {contact_id, in_active_sequence, dormant, company_match, dnd}."""
    if visitor.get("dnd"):
        return None
    starts = [e for e in events if e["type"] == "form_start" and e.get("form_email")]
    submitted = any(e["type"] == "form_submit" for e in events)
    if starts and not submitted and now - starts[-1]["at"] >= timedelta(hours=cfg["form_reminder_after_hours"]):
        return {"action": "form_reminder", "email": starts[-1]["form_email"]}
    s = score(events, now, cfg)
    pages = sorted({e.get("path") for e in events if e["type"] == "page_view"})
    if visitor.get("contact_id"):
        if visitor.get("in_active_sequence"):
            return {"action": "pull_next_follow_up_forward", "pages": pages, "score": s["score"]}
        if s["level"] != "low":
            return {"action": "reengage_within_24h", "pages": pages, "score": s["score"]}
        return None
    if visitor.get("company_match") and s["level"] == "high":
        return {"action": "create_lead_and_outreach", "company": visitor["company_match"], "score": s["score"]}
    return None


def audiences(visitors: List[Dict[str, Any]], now: datetime, cfg=DEFAULTS) -> Dict[str, Dict[str, List[str]]]:
    """Per BU: all visitors (30 d), high intent, form abandoners; clients and DND excluded."""
    out: Dict[str, Dict[str, List[str]]] = {}
    for v in visitors:
        if v.get("dnd") or v.get("is_client") or not v.get("consent") or now - v["last_seen"] > timedelta(days=cfg["audience_window_days"]):
            continue
        for bu in v.get("bus") or []:
            a = out.setdefault(bu, {"all_30d": [], "high_intent": [], "form_abandoners": []})
            a["all_30d"].append(v["visitor_id"])
            if v.get("high_intent"):
                a["high_intent"].append(v["visitor_id"])
            if v.get("form_abandoned"):
                a["form_abandoners"].append(v["visitor_id"])
    return out
