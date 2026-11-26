"""Marketing > Newsletter: design once, send per business unit from that BU's Workspace mailboxes.

A newsletter is a list of content blocks (heading, text, image, button, divider, spacer). For each
selected BU it is wrapped in that BU's branding (name, colour, website, footer) and sent from the
Workspace mailboxes chosen for that BU, via the Gmail API (GmailWorkspaceService.send_email).

Audience, per BU, from any of:
  crm_leads / crm_accounts / crm_contacts   crm_db (the client side: leads, accounts, contacts)
  ops_vendors / billing_vendors              email_automation.vendors / finance_db.vendors
  mailbox_contacts                           external addresses seen in the attached mailboxes
                                             (harvest() keeps newsletter_contacts up to date)
  extra_emails                               pasted by hand
Never included: the Panel module (campaign_platform.panelists), anyone on the suppression list,
our own domains, role / no-reply addresses, disqualified leads, DND accounts and contacts.

Flow: draft -> test send (to yourself) -> approve (now or scheduled; needs the approve capability)
-> sending -> sent. Approval is refused until a test was sent of exactly the current design.
tick() runs every minute: it starts due newsletters (the recipient list is built then, so it is
fresh) and sends a few mails per mailbox, within a daily cap per mailbox. Every mail carries a
visible unsubscribe link and a one-click List-Unsubscribe header; an unsubscribe suppresses the
address everywhere (services.outreach_unsubscribe.record_optout).

Functions take gd (database name -> db), like the rest of marketing/, so tests run on FakeDB.
"""
import hashlib
import html as _html
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from marketing import schema
from marketing.schema import utcnow

DB = schema.DB                                   # email_automation: newsletters, newsletter_recipients, newsletter_contacts
NEWSLETTERS, RECIPIENTS, CONTACTS, META = "newsletters", "newsletter_recipients", "newsletter_contacts", "newsletter_meta"

BRANDS: Dict[str, Dict[str, str]] = {
    "SFW": {"name": "Survey Fieldwork", "domain": "surveyfieldwork.com", "website": "https://surveyfieldwork.com",
            "color": "#c2410c", "logo_url": ""},
    "COGENTIX": {"name": "Cogentix Research", "domain": "cogentixresearch.com", "website": "https://cogentixresearch.com",
                 "color": "#a15f06", "logo_url": ""},
    "BIM": {"name": "BIMwave Solutions", "domain": "bimwavesolutions.com", "website": "https://bimwavesolutions.com",
            "color": "#0a66c2", "logo_url": ""},
}

BLOCK_TYPES = ("heading", "text", "image", "button", "divider", "spacer")
SOURCES = {
    "crm_leads": "Clients: leads",
    "crm_accounts": "Clients: accounts",
    "crm_contacts": "Clients: contacts",
    "ops_vendors": "Vendors: operations (sample suppliers)",
    "billing_vendors": "Vendors: billing",
    "mailbox_contacts": "Attached mailboxes: external contacts",
}
STATUSES = ("draft", "scheduled", "sending", "paused", "sent", "cancelled")
EDITABLE = ("draft", "scheduled")                # editing a scheduled newsletter sends it back to draft; once sending starts it is fixed
STUCK_AFTER = timedelta(minutes=15)              # a row claimed but never finished (worker died mid-send)

EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}$")
ROLE_RE = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounces?|notifications?|alerts?|"
                     r"calendar-notification|invitations?|support-noreply|automated|system)([+._-].*)?@")
AUTOMATED_DOMAIN_RE = re.compile(r"(^|\.)(google\.com|googlemail\.com|linkedin\.com|facebookmail\.com|amazonses\.com|"
                                 r"sendgrid\.net|mailchimp\.com|mcsv\.net|zoom\.us|calendly\.com|github\.com)$")
TOKENS = ("first_name", "name", "company", "company_name")


# ----------------------------------------------------------------------------- helpers
def _gd_default(name):
    from database import get_database
    return get_database(name)


def _cfg() -> Dict[str, Any]:
    try:
        from platform_core import config_store
        return config_store.get("marketing").get("newsletter") or {}
    except Exception:
        from marketing.config import DEFAULTS
        return DEFAULTS["newsletter"]


def brand(bu: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    cfg = _cfg() if cfg is None else cfg
    return {**BRANDS[bu], **((cfg.get("brands") or {}).get(bu) or {})}


def normalize(email: Any) -> str:
    return str(email or "").strip().strip("<>").lower()


def domain(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def own_domains(gd) -> set:
    doms = {b["domain"] for b in BRANDS.values()}
    try:
        for m in gd("torpedo_gmail")["workspace_mailboxes"].find({}, {"email": 1}):
            d = domain(normalize(m.get("email")))
            if d:
                doms.add(d)
    except Exception:
        pass
    return doms


def mailable(email: str, own: Iterable[str] = ()) -> bool:
    """A real external person/company address: valid, not ours, not a role / no-reply / platform address."""
    if not EMAIL_RE.match(email):
        return False
    d = domain(email)
    return d not in set(own) and not ROLE_RE.match(email) and not AUTOMATED_DOMAIN_RE.search(d)


def public_base() -> str:
    try:
        from services.outreach_unsubscribe import PUBLIC_BASE_URL
    except ImportError:  # pragma: no cover - imported as backend.*
        from backend.services.outreach_unsubscribe import PUBLIC_BASE_URL
    return PUBLIC_BASE_URL


def send_blocker() -> Optional[str]:
    """Why nothing can be sent yet, or None. The unsubscribe link and images need a public URL."""
    if not public_base():
        return "Set OUTREACH_PUBLIC_BASE_URL (the public https address of this server) so the unsubscribe link and images work."
    return None


def unsubscribe_urls(email: str) -> Tuple[str, str]:
    try:
        from services.outreach_unsubscribe import make_token
    except ImportError:  # pragma: no cover
        from backend.services.outreach_unsubscribe import make_token
    base = f"{public_base()}/api/marketing/newsletter/unsubscribe/{quote(make_token(email))}"
    return base, f"{base}/one-click"


def design_hash(nl: Dict[str, Any]) -> str:
    """What a test send proves: subject, preheader, blocks, BUs and senders. Any change needs a new test."""
    part = {k: nl.get(k) for k in ("subject", "preheader", "blocks", "bus", "senders")}
    return hashlib.sha256(json.dumps(part, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ----------------------------------------------------------------------------- validation
def clean_blocks(blocks: Any) -> List[Dict[str, Any]]:
    out = []
    for b in blocks or []:
        if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
            raise ValueError(f"unknown block {b!r:.60}")
        t = b["type"]
        keep = {"heading": ("text", "level", "align"), "text": ("text", "align"),
                "image": ("src", "alt", "link", "width"), "button": ("label", "url", "align"),
                "divider": (), "spacer": ("height",)}[t]
        c = {"type": t, **{k: b.get(k) for k in keep if b.get(k) not in (None, "")}}
        for k in ("url", "link"):
            if c.get(k) and not re.match(r"^(https?://|mailto:)", str(c[k]), re.I):
                raise ValueError(f"{t} link must start with https://, http:// or mailto:")
        if t == "image" and c.get("src") and not re.match(r"^(https?://|media:)", str(c["src"]), re.I):
            raise ValueError("image must be a media-library image or an https:// URL")
        if t == "heading":
            c["level"] = int(c.get("level") or 2) if str(c.get("level") or 2) in ("1", "2", "3") else 2
        for k, lo, hi in (("width", 80, 536), ("height", 8, 80)):
            if k in c:
                try:
                    c[k] = max(lo, min(hi, int(c[k])))
                except (TypeError, ValueError):
                    c.pop(k)
        out.append(c)
    if len(out) > 60:
        raise ValueError("at most 60 blocks")
    return out


def clean(body: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """Validated subset of a create / edit body."""
    out: Dict[str, Any] = {}
    for k in ("name", "subject", "preheader"):
        if k in body:
            out[k] = str(body[k] or "").strip()[:300]
    if "blocks" in body:
        out["blocks"] = clean_blocks(body["blocks"])
    if "bus" in body:
        bus = [b for b in (body["bus"] or []) if b in BRANDS]
        out["bus"] = list(dict.fromkeys(bus))
    if "senders" in body:
        out["senders"] = {bu: list(dict.fromkeys(normalize(m) for m in (ms or []) if normalize(m)))
                          for bu, ms in (body["senders"] or {}).items() if bu in BRANDS}
    if "audience" in body:
        aud = {}
        for bu, a in (body["audience"] or {}).items():
            if bu not in BRANDS or not isinstance(a, dict):
                continue
            aud[bu] = {
                "sources": [s for s in (a.get("sources") or []) if s in SOURCES],
                "mailbox_scope": "all" if a.get("mailbox_scope") == "all" else "bu",
                "extra_emails": _email_list(a.get("extra_emails")),
                "exclude_emails": _email_list(a.get("exclude_emails")),
            }
        out["audience"] = aud
    if not partial and not out.get("name"):
        out["name"] = out.get("subject") or "Untitled newsletter"
    return out


def _email_list(v: Any) -> List[str]:
    items = re.split(r"[\s,;]+", v) if isinstance(v, str) else (v or [])
    return sorted({normalize(e) for e in items if EMAIL_RE.match(normalize(e))})


# ----------------------------------------------------------------------------- rendering
def _inline(text: str) -> str:
    """Escape, then allow **bold** and [label](https://link). Nothing else becomes markup."""
    s = _html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(((?:https?://|mailto:)[^)\s]+)\)",
               lambda m: f'<a href="{m.group(2)}" style="color:inherit;text-decoration:underline">{m.group(1)}</a>', s)
    return s


def personalise(text: str, fields: Dict[str, str]) -> str:
    def sub(m):
        return fields.get(m.group(1).lower()) or {"first_name": "there", "name": "there"}.get(m.group(1).lower(), "")
    return re.sub(r"\{\{\s*(" + "|".join(TOKENS) + r")\s*\}\}", sub, text or "", flags=re.I)


def _img_src(src: str) -> str:
    if src.startswith("media:"):
        return f"{public_base()}/api/marketing/newsletter/img/{quote(src[6:])}"
    return src


def render(nl: Dict[str, Any], bu: str, fields: Optional[Dict[str, str]] = None, *,
           unsubscribe_url: str = "#", cfg: Optional[Dict[str, Any]] = None) -> Tuple[str, str, str]:
    """(subject, html, plain) of one newsletter for one BU and one recipient."""
    b = brand(bu, cfg)
    f = {"company_name": b["name"], **(fields or {})}
    color = _html.escape(b["color"])
    rows: List[str] = []
    plain: List[str] = []
    for blk in nl.get("blocks") or []:
        t, align = blk["type"], blk.get("align") if blk.get("align") in ("left", "center", "right") else "left"
        if t == "heading":
            size = {"1": 26, "2": 21, "3": 17}.get(str(blk.get("level") or 2), 21)
            txt = personalise(blk.get("text", ""), f)
            rows.append(f'<tr><td style="padding:16px 32px 4px;text-align:{align}"><h{blk.get("level") or 2} style="margin:0;'
                        f'font:bold {size}px/1.3 Arial,sans-serif;color:#111">{_inline(txt)}</h{blk.get("level") or 2}></td></tr>')
            plain.append(txt.upper() if size > 20 else txt)
        elif t == "text":
            txt = personalise(blk.get("text", ""), f)
            paras = "".join(f'<p style="margin:0 0 12px">{_inline(p).replace(chr(10), "<br>")}</p>'
                            for p in re.split(r"\n\s*\n", txt.strip()) if p.strip())
            rows.append(f'<tr><td style="padding:8px 32px;text-align:{align};font:15px/1.6 Arial,sans-serif;color:#333">{paras}</td></tr>')
            plain.append(re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", txt.replace("**", "")))
        elif t == "image" and blk.get("src"):
            w = max(80, min(536, int(blk.get("width") or 536)))
            img = (f'<img src="{_html.escape(_img_src(blk["src"]))}" width="{w}" alt="{_html.escape(blk.get("alt") or "")}" '
                   f'style="display:block;margin:0 auto;max-width:100%;height:auto;border:0">')
            if blk.get("link"):
                img = f'<a href="{_html.escape(blk["link"])}">{img}</a>'
                plain.append(f'{blk.get("alt") or "Image"}: {blk["link"]}')
            rows.append(f'<tr><td style="padding:12px 32px;text-align:center">{img}</td></tr>')
        elif t == "button" and blk.get("label") and blk.get("url"):
            label = personalise(blk["label"], f)
            rows.append(f'<tr><td style="padding:12px 32px;text-align:{align}"><a href="{_html.escape(blk["url"])}" '
                        f'style="display:inline-block;padding:12px 24px;background:{color};color:#fff;border-radius:6px;'
                        f'font:bold 15px Arial,sans-serif;text-decoration:none">{_html.escape(label)}</a></td></tr>')
            plain.append(f"{label}: {blk['url']}")
        elif t == "divider":
            rows.append('<tr><td style="padding:12px 32px"><hr style="border:0;border-top:1px solid #e5e5e5;margin:0"></td></tr>')
            plain.append("-" * 40)
        elif t == "spacer":
            rows.append(f'<tr><td style="height:{max(8, min(80, int(blk.get("height") or 24)))}px;line-height:0">&nbsp;</td></tr>')

    try:
        from services.outreach_unsubscribe import SENDER_POSTAL_ADDRESS as postal
    except ImportError:  # pragma: no cover
        postal = ""
    name, site = _html.escape(b["name"]), _html.escape(b["website"])
    logo = (f'<img src="{_html.escape(_img_src(b["logo_url"]))}" alt="{name}" height="36" style="display:block;border:0">'
            if b.get("logo_url") else f'<span style="font:bold 20px Arial,sans-serif;color:#fff">{name}</span>')
    pre = _html.escape(personalise(nl.get("preheader") or "", f))
    unsub = _html.escape(unsubscribe_url)
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_html.escape(personalise(nl.get("subject") or "", f))}</title></head>'
        '<body style="margin:0;padding:0;background:#f3f4f6">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{pre}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6"><tr><td align="center" style="padding:24px 8px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:8px;overflow:hidden">'
        f'<tr><td style="background:{color};padding:18px 32px"><a href="{site}" style="text-decoration:none">{logo}</a></td></tr>'
        f'<tr><td style="height:12px"></td></tr>{"".join(rows)}<tr><td style="height:20px"></td></tr>'
        '<tr><td style="padding:16px 32px 24px;border-top:1px solid #eee;font:12px/1.6 Arial,sans-serif;color:#777">'
        f'You are receiving this because you have been in touch with {name}. '
        f'<a href="{unsub}" style="color:#777;text-decoration:underline">Unsubscribe</a> and we will not email you again.<br>'
        f'<a href="{site}" style="color:#777">{site.replace("https://", "")}</a>'
        f'{"<br>" + _html.escape(postal) if postal else ""}</td></tr>'
        '</table></td></tr></table></body></html>'
    )
    text = "\n\n".join(p for p in plain if p) + (f"\n\n--\n{b['name']} · {b['website']}\nUnsubscribe: {unsubscribe_url}"
                                                 + (f"\n{postal}" if postal else ""))
    subject = re.sub(r"\s+", " ", personalise(nl.get("subject") or "", f)).strip()      # one line: a name must not add headers
    return subject, html, text


# ----------------------------------------------------------------------------- mailboxes
def mailboxes(gd) -> List[Dict[str, Any]]:
    """Active Workspace mailboxes, each tagged with the BU its domain belongs to (None if no BU matches)."""
    by_domain = {b["domain"]: bu for bu, b in BRANDS.items()}
    out = []
    for m in gd("torpedo_gmail")["workspace_mailboxes"].find({"is_active": True}, {"email": 1, "display_name": 1}):
        e = normalize(m.get("email"))
        out.append({"email": e, "display_name": m.get("display_name") or "", "bu": by_domain.get(domain(e))})
    return sorted(out, key=lambda m: (m["bu"] or "~", m["email"]))


def _bulk_senders() -> frozenset:
    from messaging import deliverability
    return deliverability.bulk_senders()


def _sender_problem(mailbox: str, allowed: frozenset) -> Optional[str]:
    from messaging import deliverability
    return deliverability.bulk_sender_problem(mailbox, allowed)


def sender_mailboxes(gd) -> List[Dict[str, Any]]:
    """The mailboxes a newsletter may be sent from: active and an approved bulk sender."""
    allowed = _bulk_senders()
    return [m for m in mailboxes(gd) if not _sender_problem(m["email"], allowed)]


def sent_today(gd, mailbox: str, now: datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return gd(DB)[RECIPIENTS].count_documents({"mailbox": mailbox, "status": "sent", "sent_at": {"$gte": start}})


# ----------------------------------------------------------------------------- mailbox contacts
def harvest(gd=None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Fold new mail from the attached mailboxes into newsletter_contacts: inbound senders and the
    people we wrote to. Incremental on email_metadata.synced_at."""
    gd = gd or _gd_default
    now = now or utcnow()
    ea, mail = gd(DB), gd("torpedo_gmail")
    meta = ea[META].find_one({"_id": "harvest"}) or {}
    since = meta.get("watermark") or datetime(2000, 1, 1)
    box_of = {str(m["_id"]): normalize(m.get("email")) for m in mail["workspace_mailboxes"].find({}, {"email": 1})}
    by_domain = {b["domain"]: bu for bu, b in BRANDS.items()}
    own = own_domains(gd)
    found: Dict[str, Dict[str, Any]] = {}
    newest, scanned = since, 0
    cur = mail["email_metadata"].find({"synced_at": {"$gt": since}},
                                      {"from_email": 1, "from_name": 1, "to_emails": 1, "cc_emails": 1, "direction": 1,
                                       "mailbox_id": 1, "timestamp": 1, "synced_at": 1})
    for m in cur:
        scanned += 1
        if m.get("synced_at") and m["synced_at"] > newest:
            newest = m["synced_at"]
        box = box_of.get(str(m.get("mailbox_id")), "")
        pairs = ([(m.get("from_email"), m.get("from_name"))] if m.get("direction") != "outbound"
                 else [(e, None) for e in (m.get("to_emails") or []) + (m.get("cc_emails") or [])])
        for e, name in pairs:
            e = normalize(e)
            if not mailable(e, own):
                continue
            c = found.setdefault(e, {"names": set(), "mailboxes": set(), "first": None, "last": None, "n": 0})
            if name and normalize(name) != e:
                c["names"].add(str(name).strip()[:120])
            if box:
                c["mailboxes"].add(box)
            ts = m.get("timestamp") or m.get("synced_at")
            if isinstance(ts, datetime):
                if ts.tzinfo is not None:
                    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                c["first"] = ts if c["first"] is None or ts < c["first"] else c["first"]
                c["last"] = ts if c["last"] is None or ts > c["last"] else c["last"]
            c["n"] += 1
    panel = panel_emails(gd, list(found))
    col, added = ea[CONTACTS], 0
    for e, c in found.items():
        if e in panel:
            continue
        old = col.find_one({"email": e}) or {}
        boxes = sorted(set(old.get("mailboxes") or []) | c["mailboxes"])
        upd = {"email": e, "domain": domain(e), "mailboxes": boxes,
               "bus": sorted({by_domain[domain(b)] for b in boxes if domain(b) in by_domain}),
               "name": old.get("name") or (sorted(c["names"])[0] if c["names"] else None),
               "messages": int(old.get("messages") or 0) + c["n"],
               "first_seen": min(x for x in (old.get("first_seen"), c["first"], now) if x),
               "last_seen": max(x for x in (old.get("last_seen"), c["last"]) if x) if (old.get("last_seen") or c["last"]) else None,
               "updated_at": now}
        if not old:
            upd["created_at"] = now
            added += 1
        col.update_one({"email": e}, {"$set": upd}, upsert=True)
    ea[META].update_one({"_id": "harvest"}, {"$set": {"watermark": newest, "ran_at": now, "scanned": scanned}}, upsert=True)
    return {"scanned": scanned, "contacts_seen": len(found), "new_contacts": added, "watermark": newest}


def panel_emails(gd, emails: List[str]) -> set:
    """Addresses that belong to the Panel module: never newsletter recipients."""
    out: set = set()
    try:
        col = gd("campaign_platform")["panelists"]
        for i in range(0, len(emails), 500):
            for p in col.find({"email": {"$in": emails[i:i + 500]}}, {"email": 1}):
                out.add(normalize(p.get("email")))
    except Exception:
        pass
    return out


# ----------------------------------------------------------------------------- audience
def _first(*vals) -> str:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _source_rows(gd, source: str, bu: str, scope: str) -> Iterable[Dict[str, str]]:
    """(email, name, first_name, company) rows of one source."""
    if source == "crm_leads":
        for d in gd("crm_db")["leads"].find({"status": {"$ne": "disqualified"}},
                                            {"email": 1, "name": 1, "firstName": 1, "lastName": 1, "company": 1, "dnd": 1}):
            if not d.get("dnd"):
                yield _row(d)
    elif source == "crm_accounts":
        for d in gd("crm_db")["accounts"].find({}, {"email": 1, "name": 1, "dnd": 1, "status": 1}):
            if not d.get("dnd") and d.get("status") not in ("inactive", "closed", "deleted"):
                yield {"email": normalize(d.get("email")), "name": "", "first_name": "", "company": _first(d.get("name"))}
    elif source == "crm_contacts":
        for d in gd("crm_db")["contacts"].find({}, {"email": 1, "name": 1, "firstName": 1, "lastName": 1, "company": 1, "dnd": 1}):
            if not d.get("dnd"):
                yield _row(d)
    elif source in ("ops_vendors", "billing_vendors"):
        db = gd("email_automation" if source == "ops_vendors" else "finance_db")
        for d in db["vendors"].find({}, {"email": 1, "contact_email": 1, "vendor_name": 1, "name": 1, "contact_name": 1,
                                         "status": 1, "is_deleted": 1}):
            if d.get("is_deleted") or str(d.get("status") or "").lower() in ("inactive", "blocked", "deleted"):
                continue
            contact = _first(d.get("contact_name"))
            for e in {normalize(d.get("email")), normalize(d.get("contact_email"))} - {""}:
                yield {"email": e, "name": contact, "first_name": contact.split(" ")[0] if contact else "",
                       "company": _first(d.get("vendor_name"), d.get("name"))}
    elif source == "mailbox_contacts":
        q = {"bus": bu} if scope == "bu" else {}
        for d in gd(DB)[CONTACTS].find(q, {"email": 1, "name": 1, "bus": 1}):
            nm = _first(d.get("name"))
            yield {"email": normalize(d.get("email")), "name": nm, "first_name": nm.split(" ")[0] if nm else "", "company": ""}


def _row(d: Dict[str, Any]) -> Dict[str, str]:
    first = _first(d.get("firstName"), (d.get("name") or "").split(" ")[0])
    name = _first(d.get("name"), " ".join(x for x in (d.get("firstName"), d.get("lastName")) if x))
    return {"email": normalize(d.get("email")), "name": name, "first_name": first, "company": _first(d.get("company"))}


def audience(gd, nl: Dict[str, Any], bu: str, *, is_suppressed: Optional[Callable[[str], bool]] = None
             ) -> Dict[str, Any]:
    """The recipients of one BU's edition: deduplicated, with what was excluded and why."""
    a = (nl.get("audience") or {}).get(bu) or {}
    own = own_domains(gd)
    if is_suppressed is None:
        from messaging import suppression
        is_suppressed = suppression.is_suppressed
    rows: Dict[str, Dict[str, Any]] = {}
    by_source: Dict[str, int] = {}
    excluded = {"invalid_or_role": 0, "suppressed": 0, "panel": 0, "excluded_by_hand": 0}
    exclude = set(a.get("exclude_emails") or [])
    feeds = [(s, _source_rows(gd, s, bu, a.get("mailbox_scope") or "bu")) for s in a.get("sources") or []]
    feeds.append(("extra_emails", ({"email": e, "name": "", "first_name": "", "company": ""} for e in a.get("extra_emails") or [])))
    for source, it in feeds:
        n = 0
        for r in it:
            e = r["email"]
            if not e:
                continue
            n += 1
            if e in rows:
                for k in ("name", "first_name", "company"):          # fill gaps from later sources
                    rows[e][k] = rows[e][k] or r[k]
                rows[e]["sources"].append(source)
                continue
            if not mailable(e, own):
                excluded["invalid_or_role"] += 1
                continue
            if e in exclude:
                excluded["excluded_by_hand"] += 1
                continue
            rows[e] = {**r, "sources": [source]}
        by_source[source] = n
    for e in panel_emails(gd, list(rows)):
        rows.pop(e, None)
        excluded["panel"] += 1
    for e in list(rows):
        if is_suppressed(e):
            rows.pop(e)
            excluded["suppressed"] += 1
    return {"bu": bu, "recipients": list(rows.values()), "count": len(rows), "by_source": by_source, "excluded": excluded}


# ----------------------------------------------------------------------------- lifecycle
def problems(nl: Dict[str, Any], gd=None) -> List[str]:
    """What stops a test send / approval."""
    p = []
    if not (nl.get("subject") or "").strip():
        p.append("add a subject")
    if not nl.get("blocks"):
        p.append("add some content")
    if not nl.get("bus"):
        p.append("pick at least one business unit")
    for bu in nl.get("bus") or []:
        if not (nl.get("senders") or {}).get(bu):
            p.append(f"pick the sending mailbox(es) for {BRANDS[bu]['name']}")
        a = (nl.get("audience") or {}).get(bu) or {}
        if not a.get("sources") and not a.get("extra_emails"):
            p.append(f"pick who receives the {BRANDS[bu]['name']} edition")
    if gd is not None:
        active = {m["email"] for m in mailboxes(gd)}
        allowed = _bulk_senders()
        for bu, ms in (nl.get("senders") or {}).items():
            for m in ms:
                if bu in (nl.get("bus") or []) and m not in active:
                    p.append(f"{m} is not an active attached mailbox")
                elif bu in (nl.get("bus") or []) and _sender_problem(m, allowed):
                    p.append(f"{m} is not an approved bulk sender")
    b = send_blocker()
    if b:
        p.append(b)
    return p


def send_test(gd, nl: Dict[str, Any], to: List[str], *, actor: str, sender: Callable[..., Dict[str, Any]],
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """Send every selected BU's edition to the given addresses (subject prefixed [TEST]); records the design
    hash so approval can check the test matches what will go out."""
    now = now or utcnow()
    to = _email_list(to)
    if not to:
        raise ValueError("give at least one test address")
    p = problems(nl, gd)
    if p:
        raise ValueError("; ".join(p))
    results = []
    for bu in nl["bus"]:
        frm = nl["senders"][bu][0]
        for e in to:
            unsub, one_click = unsubscribe_urls(e)
            subject, html, text = render(nl, bu, {"first_name": "Test", "name": "Test Recipient", "company": "Test Company"},
                                         unsubscribe_url=unsub)
            r = sender(from_email=frm, to=[e], subject=f"[TEST] {subject}", body_html=html, body_plain=text,
                       list_unsubscribe_url=one_click)
            results.append({"bu": bu, "from": frm, "to": e, "ok": bool(r.get("success")), "error": r.get("error")})
    ok = all(r["ok"] for r in results)
    upd = {"test": {"at": now, "by": actor, "to": to, "ok": ok, "hash": design_hash(nl) if ok else None,
                    "results": results}, "updated_at": now}
    gd(DB)[NEWSLETTERS].update_one({"_id": nl["_id"]}, {"$set": upd})
    return {"ok": ok, "results": results}


def approve(gd, nl: Dict[str, Any], *, actor: str, when: Optional[datetime] = None,
            now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or utcnow()
    if nl.get("status") != "draft":
        raise ValueError(f"a {nl.get('status')} newsletter cannot be approved")
    p = problems(nl, gd)
    if p:
        raise ValueError("; ".join(p))
    t = nl.get("test") or {}
    if not t.get("ok") or t.get("hash") != design_hash(nl):
        raise ValueError("send a test of the current version first (anything changed since the last test needs a new one)")
    when = when or now
    if when < now - timedelta(minutes=5):
        raise ValueError("the send time is in the past")
    upd = {"status": "scheduled", "scheduled_for": when, "approved_by": actor, "approved_at": now, "updated_at": now}
    gd(DB)[NEWSLETTERS].update_one({"_id": nl["_id"]}, {"$set": upd, "$push": {
        "history": {"at": now, "by": actor, "action": f"approved for {when:%Y-%m-%d %H:%M} UTC"}}})
    return upd


def start(gd, nl: Dict[str, Any], *, now: Optional[datetime] = None,
          is_suppressed: Optional[Callable[[str], bool]] = None) -> Dict[str, int]:
    """Build the recipient rows (one per BU x address) and move the newsletter to sending."""
    now = now or utcnow()
    col = gd(DB)[RECIPIENTS]
    counts, summary = {}, {}
    for bu in nl.get("bus") or []:
        aud = audience(gd, nl, bu, is_suppressed=is_suppressed)
        summary[bu] = {k: aud[k] for k in ("count", "by_source", "excluded")}
        n = 0
        for r in aud["recipients"]:
            key = {"newsletter_id": nl["_id"], "bu": bu, "email": r["email"]}
            if col.find_one(key):
                continue
            col.insert_one({**key, "name": r["name"], "first_name": r["first_name"], "company": r["company"],
                            "sources": r["sources"], "status": "queued", "attempts": 0, "created_at": now})
            n += 1
        counts[bu] = n
    gd(DB)[NEWSLETTERS].update_one({"_id": nl["_id"]}, {"$set": {
        "status": "sending", "started_at": now, "updated_at": now, "audience_summary": summary}})
    return counts


def set_status(gd, nl: Dict[str, Any], action: str, *, actor: str, now: Optional[datetime] = None) -> str:
    """pause / resume / cancel / unschedule. Cancelling skips every row not yet sent."""
    now = now or utcnow()
    st = nl.get("status")
    to = {("pause", "sending"): "paused", ("pause", "scheduled"): "draft", ("unschedule", "scheduled"): "draft",
          ("resume", "paused"): "sending", ("cancel", "scheduled"): "cancelled", ("cancel", "sending"): "cancelled",
          ("cancel", "paused"): "cancelled", ("cancel", "draft"): "cancelled"}.get((action, st))
    if not to:
        raise ValueError(f"cannot {action} a {st} newsletter")
    gd(DB)[NEWSLETTERS].update_one({"_id": nl["_id"]}, {"$set": {"status": to, "updated_at": now},
                                                        "$push": {"history": {"at": now, "by": actor, "action": action}}})
    if to == "cancelled":
        gd(DB)[RECIPIENTS].update_many({"newsletter_id": nl["_id"], "status": "queued"},
                                       {"$set": {"status": "skipped", "reason": "cancelled", "updated_at": now}})
    return to


def stats(gd, nl_id) -> Dict[str, Any]:
    col = gd(DB)[RECIPIENTS]
    out: Dict[str, Any] = {"total": 0}
    for st in ("queued", "sending", "sent", "failed", "skipped"):
        out[st] = col.count_documents({"newsletter_id": nl_id, "status": st})
        out["total"] += out[st]
    return out


def tick(gd=None, *, now: Optional[datetime] = None, sender: Optional[Callable[..., Dict[str, Any]]] = None,
         is_suppressed: Optional[Callable[[str], bool]] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One scheduler pass: start due newsletters, then send a paced batch from every mailbox in use."""
    gd = gd or _gd_default
    now = now or utcnow()
    cfg = _cfg() if cfg is None else cfg
    ea = gd(DB)
    report: Dict[str, Any] = {"started": [], "sent": 0, "failed": 0, "skipped": 0, "finished": []}
    # a worker died between claiming a row and recording the result: the mail may or may not have gone,
    # so it is never retried (a duplicate is worse than a miss)
    ea[RECIPIENTS].update_many({"status": "sending", "claimed_at": {"$lt": now - STUCK_AFTER}},
                               {"$set": {"status": "failed", "error": "interrupted during send; not retried",
                                         "updated_at": now}})
    for nl in ea[NEWSLETTERS].find({"status": "scheduled", "scheduled_for": {"$lte": now}}):
        start(gd, nl, now=now, is_suppressed=is_suppressed)
        report["started"].append(str(nl["_id"]))
    active = list(ea[NEWSLETTERS].find({"status": "sending"}))
    if not active:
        return report
    if send_blocker():
        report["blocked"] = send_blocker()
        return report
    if sender is None:
        sender = workspace_sender()
    if is_suppressed is None:
        from messaging import suppression
        is_suppressed = suppression.is_suppressed
    per_tick = int(cfg.get("per_tick_per_mailbox") or 5)
    cap = int(cfg.get("daily_cap_per_mailbox") or 300)
    max_attempts = int(cfg.get("max_attempts") or 2)
    rc = ea[RECIPIENTS]
    budget: Dict[str, int] = {}
    allowed = _bulk_senders()
    for nl in active:
        for bu in nl.get("bus") or []:
            for box in (nl.get("senders") or {}).get(bu) or []:
                if box not in budget:
                    if _sender_problem(box, allowed):          # not an approved bulk sender: never sends
                        budget[box] = 0
                        report.setdefault("sender_blocked", []).append(box)
                    else:
                        budget[box] = max(0, min(per_tick, cap - sent_today(gd, box, now)))
                while budget[box] > 0:
                    r = rc.find_one({"newsletter_id": nl["_id"], "bu": bu, "status": "queued"})
                    if not r:
                        break
                    res = rc.update_one({"_id": r["_id"], "status": "queued"}, {"$set": {"status": "sending", "mailbox": box,
                                                                                         "claimed_at": now}})
                    if getattr(res, "modified_count", 1) == 0:          # another worker took it
                        continue
                    budget[box] -= 1
                    _send_one(gd, nl, bu, box, r, sender, is_suppressed, now, max_attempts, report, cfg)
        if rc.count_documents({"newsletter_id": nl["_id"], "status": {"$in": ["queued", "sending"]}}) == 0:
            ea[NEWSLETTERS].update_one({"_id": nl["_id"]}, {"$set": {"status": "sent", "finished_at": now,
                                                                     "stats": stats(gd, nl["_id"]), "updated_at": now}})
            report["finished"].append(str(nl["_id"]))
    return report


def _send_one(gd, nl, bu, box, r, sender, is_suppressed, now, max_attempts, report, cfg) -> None:
    rc = gd(DB)[RECIPIENTS]
    if is_suppressed(r["email"]):
        rc.update_one({"_id": r["_id"]}, {"$set": {"status": "skipped", "reason": "suppressed", "updated_at": now}})
        report["skipped"] += 1
        return
    unsub, one_click = unsubscribe_urls(r["email"])
    subject, html, text = render(nl, bu, {k: r.get(k) or "" for k in ("name", "first_name", "company")},
                                 unsubscribe_url=unsub, cfg=cfg)
    try:
        res = sender(from_email=box, to=[r["email"]], subject=subject, body_html=html, body_plain=text,
                     list_unsubscribe_url=one_click)
    except Exception as e:                                   # a crash must not lose the row
        res = {"success": False, "error": str(e)[:300]}
    attempts = int(r.get("attempts") or 0) + 1
    if res.get("success"):
        rc.update_one({"_id": r["_id"]}, {"$set": {"status": "sent", "sent_at": now, "attempts": attempts,
                                                   "message_id": res.get("message_id"), "updated_at": now}})
        report["sent"] += 1
    else:
        final = attempts >= max_attempts
        rc.update_one({"_id": r["_id"]}, {"$set": {"status": "failed" if final else "queued", "attempts": attempts,
                                                   "error": str(res.get("error") or "send failed")[:300], "updated_at": now}})
        report["failed"] += 1


def workspace_sender() -> Callable[..., Dict[str, Any]]:
    from app.services.gmail_workspace_service import GmailWorkspaceService
    svc = GmailWorkspaceService(db_name="torpedo_gmail")
    svc.load_service_account()
    return svc.send_email
