"""Deliverability rules for cold outreach (CRM plan 3.11, 3.2.5).

Pure functions plus thin DB helpers, so every rule that decides whether / how
a mail goes out is unit-tested. Tunables live in torpedo_settings.config
(_id "deliverability"); DEFAULTS is the fallback and the documented contract.

  warm-up cap      start 20/day per mailbox, +20% per week, ceiling 80
  bounce pause     a mailbox whose 7-day bounce rate > 3% (min 20 sends) is
                   paused for outreach until a person clears it
  first mail       plain text, no images / pixel / attachments, <= 1 link,
                   visible unsubscribe line (+ List-Unsubscribe https header)
  send window      09:00-17:00 Mon-Fri in the recipient's time zone
  verified only    first touch needs reverify.outcome == "pass"
  per-BU switch    torpedo.outreach_kill_switch {_id: "bu:<business>"};
                   missing = paused (fail safe), so a BU starts only when the
                   owner opens it
  reference ID     "[L-xxxxxx]" appended to the first subject; replies on the
                   thread keep it
"""
import html as _html
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    "warmup_start_per_day": 20,
    "warmup_weekly_growth": 0.20,
    "daily_cap_per_mailbox": 80,
    "bounce_pause_rate": 0.03,
    "bounce_min_sends": 20,
    "bounce_window_days": 7,
    "complaint_stop_rate": 0.003,
    "send_window_start_hour": 9,
    "send_window_end_hour": 17,
    "send_weekdays": [0, 1, 2, 3, 4],          # Mon-Fri
    "default_timezone": "Asia/Kolkata",
    "require_verified_first_touch": True,
    "subject_ref_tag": True,
    "first_mail_max_links": 1,
    "sequence_day_offsets": [0, 3, 7, 12, 18, 25],
}

COUNTRY_TZ = {
    "IN": "Asia/Kolkata", "US": "America/New_York", "CA": "America/Toronto", "GB": "Europe/London",
    "UK": "Europe/London", "IE": "Europe/Dublin", "DE": "Europe/Berlin", "FR": "Europe/Paris",
    "NL": "Europe/Amsterdam", "ES": "Europe/Madrid", "IT": "Europe/Rome", "CH": "Europe/Zurich",
    "SE": "Europe/Stockholm", "AU": "Australia/Sydney", "NZ": "Pacific/Auckland", "SG": "Asia/Singapore",
    "MY": "Asia/Kuala_Lumpur", "HK": "Asia/Hong_Kong", "JP": "Asia/Tokyo", "KR": "Asia/Seoul",
    "CN": "Asia/Shanghai", "AE": "Asia/Dubai", "SA": "Asia/Riyadh", "ZA": "Africa/Johannesburg",
    "BR": "America/Sao_Paulo", "MX": "America/Mexico_City", "ID": "Asia/Jakarta", "PH": "Asia/Manila",
    "TH": "Asia/Bangkok", "VN": "Asia/Ho_Chi_Minh",
}
COUNTRY_NAME_TO_CODE = {"india": "IN", "united states": "US", "usa": "US", "united kingdom": "GB",
                        "uk": "GB", "germany": "DE", "france": "FR", "australia": "AU",
                        "singapore": "SG", "canada": "CA", "united arab emirates": "AE", "uae": "AE"}


# ------------------------------------------------------------------ config
def load_config(db=None) -> Dict[str, Any]:
    """DEFAULTS overlaid with torpedo_settings.config {_id: 'deliverability'}."""
    cfg = dict(DEFAULTS)
    try:
        if db is None:
            try:
                from database import get_database
            except ImportError:
                from ..database import get_database
            db = get_database("torpedo_settings")
        doc = db["config"].find_one({"_id": "deliverability"}) or {}
        cfg.update({k: v for k, v in doc.items() if k in DEFAULTS})
    except Exception:
        logger.warning("deliverability config unreadable; using defaults", exc_info=True)
    return cfg


# ----------------------------------------------------------------- warm-up
def warmup_limit(warmup_started_at: Optional[datetime], now: datetime, cfg=DEFAULTS) -> int:
    """Daily cap for a mailbox in warm-up: start * (1 + growth) ** full_weeks, capped."""
    if not warmup_started_at:
        return int(cfg["warmup_start_per_day"])
    weeks = max(0, (now - warmup_started_at).days // 7)
    limit = int(cfg["warmup_start_per_day"] * (1 + cfg["warmup_weekly_growth"]) ** weeks)
    return min(limit, int(cfg["daily_cap_per_mailbox"]))


def effective_daily_cap(env_cap: int, warmup_started_at, now, cfg=DEFAULTS) -> int:
    """The tighter of the existing env/safety cap and the warm-up cap."""
    return min(int(env_cap), warmup_limit(warmup_started_at, now, cfg))


# ------------------------------------------------------------ bounce pause
def bounce_breach(sent: int, bounced: int, cfg=DEFAULTS) -> Optional[str]:
    """Reason string if the mailbox must be paused, else None."""
    total = sent + bounced
    if total < cfg["bounce_min_sends"]:
        return None
    rate = bounced / total
    if rate > cfg["bounce_pause_rate"]:
        return (f"bounce rate {rate:.1%} over the last {cfg['bounce_window_days']} days "
                f"({bounced}/{total}) > {cfg['bounce_pause_rate']:.0%}")
    return None


def mailbox_bounce_stats(db, from_email: str, now: datetime, cfg=DEFAULTS) -> Tuple[int, int]:
    since = now - timedelta(days=cfg["bounce_window_days"])
    q = {"from_email": from_email, "sent_at": {"$gte": since}}
    sends = db["outreach_sends_v2"]
    return (sends.count_documents({**q, "status": {"$ne": "bounced"}}),
            sends.count_documents({**q, "status": "bounced"}))


def mailbox_outreach_pause(gmail_db, from_email: str) -> Optional[Dict[str, Any]]:
    doc = gmail_db["workspace_mailboxes"].find_one({"email": from_email}, {"outreach_paused": 1}) or {}
    return doc.get("outreach_paused") or None


def pause_mailbox(gmail_db, crm_db, from_email: str, reason: str, now: datetime) -> None:
    """Pause outreach on one mailbox, audit it and raise a notification. Client
    and finance mail from the same mailbox are unaffected (other channels)."""
    gmail_db["workspace_mailboxes"].update_one(
        {"email": from_email},
        {"$set": {"outreach_paused": {"reason": reason, "at": now, "by": "system:deliverability"}}})
    try:
        crm_db["audit_log"].insert_one({
            "timestamp": now, "user_id": "system", "action": "update", "entity_type": "mailbox",
            "entity_id": from_email, "changes": {"outreach_paused": {"before": None, "after": True}},
            "metadata": {"reason": reason, "source": "messaging.deliverability"}})
        crm_db["notifications"].insert_one({
            "created_at": now, "type": "deliverability_pause", "severity": "red", "read": False,
            "title": f"Outreach paused on {from_email}", "body": reason,
            "link_object_id": from_email})
    except Exception:
        logger.exception("could not record mailbox pause for %s", from_email)


# ------------------------------------------------------------- per-BU switch
def bu_outreach_open(torpedo_db, business: str) -> bool:
    """True only when the owner has opened this BU. Missing/unreadable = closed."""
    try:
        doc = torpedo_db["outreach_kill_switch"].find_one({"_id": f"bu:{(business or '').lower()}"})
    except Exception:
        return False
    return bool(doc) and doc.get("paused", True) is False


# ------------------------------------------------------------- send window
def recipient_tz(country: Optional[str], cfg=DEFAULTS) -> ZoneInfo:
    c = (country or "").strip()
    code = c.upper() if len(c) == 2 else COUNTRY_NAME_TO_CODE.get(c.lower(), "")
    return ZoneInfo(COUNTRY_TZ.get(code, cfg["default_timezone"]))


def next_send_time(now_utc: datetime, country: Optional[str], cfg=DEFAULTS) -> Optional[datetime]:
    """None if now is inside the recipient's window; else the next window start (naive UTC)."""
    tz = recipient_tz(country, cfg)
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    start, end = cfg["send_window_start_hour"], cfg["send_window_end_hour"]
    if local.weekday() in cfg["send_weekdays"] and start <= local.hour < end:
        return None
    cand = local.replace(hour=start, minute=0, second=0, microsecond=0)
    if local.hour >= start:
        cand += timedelta(days=1)
    while cand.weekday() not in cfg["send_weekdays"]:
        cand += timedelta(days=1)
    return cand.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


# ---------------------------------------------------- verified-before-send
def verified_for_first_touch(lead: Dict[str, Any], step_number: int, cfg=DEFAULTS) -> Tuple[bool, str]:
    if step_number > 1 or not cfg["require_verified_first_touch"]:
        return True, ""
    rv = (lead.get("reverify") or {})
    if rv.get("outcome") == "pass":
        return True, ""
    return False, f"not verified for first send (reverify={rv.get('outcome') or 'none'})"


# ------------------------------------------------------------- reference ID
def ref_id(lead: Dict[str, Any]) -> str:
    """Short, stable reference for a lead: L- + last 6 hex chars of its id."""
    raw = str(lead.get("lead_id") or lead.get("_id") or "")
    tail = re.sub(r"[^0-9a-fA-F]", "", raw)[-6:].upper() or "000000"
    return f"L-{tail}"


def subject_with_ref(subject: str, ref: str, cfg=DEFAULTS) -> str:
    if not cfg["subject_ref_tag"] or f"[{ref}]" in (subject or ""):
        return subject
    return f"{subject} [{ref}]".strip()


# --------------------------------------------------------- first-mail body
_A_TAG = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def html_to_plain(body_html: str, max_links: int = 1) -> Tuple[str, int]:
    """Plain text from a template body. Keeps the first `max_links` links as
    bare URLs, turns the rest into their link text. Returns (text, links_kept)."""
    kept = 0

    def _link(m):
        nonlocal kept
        url, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if kept < max_links and url.startswith("http"):
            kept += 1
            return f"{text} ({url})" if text and text != url else url
        return text
    s = _A_TAG.sub(_link, body_html or "")
    s = re.sub(r"<img\b[^>]*>", "", s, flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<li\b[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip(), kept


def first_mail_plain(body_html: str, sender_name: str, business_label: str,
                     unsubscribe_url: str, postal_address: str = "", cfg=DEFAULTS) -> str:
    """The whole first cold mail as plain text: body, a text signature, and a
    visible unsubscribe line. The unsubscribe link is not counted against the
    one-link limit (it is required by law and by Gmail/Yahoo)."""
    text, _ = html_to_plain(body_html, cfg["first_mail_max_links"])
    sig = "\n".join(x for x in (sender_name, business_label) if x)
    footer = f"\n\n--\nIf you'd rather not hear from me again: {unsubscribe_url}"
    if postal_address:
        footer += f"\n{postal_address}"
    return f"{text}\n\n{sig}{footer}".strip()


def count_links(text: str) -> int:
    return len(re.findall(r"https?://", text or ""))
