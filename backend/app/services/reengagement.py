"""
Clients and leads that fell through the cracks (owner, 2026-09-29: "there are
lot of cases where leads or clients have fallen through the cracks or we have
totally forgotten. Touching them is also something which we need to look
into").

Once a day this finds:

  quote_no_reply     a quote went out (RFQ at stage proposal, still open) and
                     the client has not written since, 7-180 days
  positive_quiet     a prospect replied positively, no nurture is running,
                     and nobody has written either way for 21+ days
  dormant_client     a client we have won work from, with no mail either way
                     for 120+ days and nothing open with them
  rfq_not_quoted     an RFQ we received 3+ days ago and never quoted -- ours to
                     act on, so a task only, no mail

Each gets a CRM task. The first three also get a short check-in written by
the local model (template if it is unavailable or writes something that fails
the checks), saved as a Gmail DRAFT in the mailbox that last dealt with them
-- never sent. Drafts are capped per day (REENGAGE_DAILY_DRAFTS, default 8),
and a person is not touched again until their cooldown passes. Opted-out
addresses and negative leads are skipped.

State: email_automation.reengagement, one document per kind + person/company.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

QUOTE_SILENT_DAYS = 7
QUOTE_MAX_DAYS = 180
POSITIVE_QUIET_DAYS = 21
DORMANT_DAYS = 120
DORMANT_MAX_YEARS = 5
POSITIVE_MAX_DAYS = 365  # older than this, "picking up our conversation" reads oddly
UNQUOTED_DAYS = 3
COOLDOWN_DAYS = {"quote_no_reply": 30, "positive_quiet": 45, "dormant_client": 90, "rfq_not_quoted": 7}
PRIORITY = ["quote_no_reply", "positive_quiet", "dormant_client", "rfq_not_quoted"]
TASK_TITLES = {
    "quote_no_reply": "Chase quote: {what}",
    "positive_quiet": "Positive lead gone quiet: {who}",
    "dormant_client": "Client gone quiet: {company}",
    "rfq_not_quoted": "RFQ never quoted: {what}",
}


def daily_draft_limit() -> int:
    try:
        return max(0, int(os.getenv("REENGAGE_DAILY_DRAFTS", "8")))
    except ValueError:
        return 8


def _first(name: str) -> str:
    from app.services.email_structure import split_name
    f, _ = split_name(name or "")
    return f.capitalize() if f else ""


# ---------------------------------------------------------------------------
# the decisions (pure; the finders below feed them)
# ---------------------------------------------------------------------------
def quote_is_silent(quoted_at: Optional[datetime], last_client_mail: Optional[datetime], now: datetime) -> bool:
    if not quoted_at:
        return False
    age = now - quoted_at
    if age < timedelta(days=QUOTE_SILENT_DAYS) or age > timedelta(days=QUOTE_MAX_DAYS):
        return False
    return not last_client_mail or last_client_mail <= quoted_at


def is_dormant(last_contact: Optional[datetime], last_won: Optional[datetime], has_open: bool,
               now: datetime) -> bool:
    if has_open or not last_won or last_won < now - timedelta(days=365 * DORMANT_MAX_YEARS):
        return False
    return not last_contact or last_contact < now - timedelta(days=DORMANT_DAYS)


def positive_is_quiet(lead: Dict[str, Any], last_contact: Optional[datetime], now: datetime) -> bool:
    if (lead.get("nurture") or {}).get("status") in ("active", "paused_new_reply"):
        return False
    if lead.get("stage") in ("won", "lost", "converted") or lead.get("lead_status") != "Positive":
        return False
    return bool(last_contact) and         now - timedelta(days=POSITIVE_MAX_DAYS) <= last_contact < now - timedelta(days=POSITIVE_QUIET_DAYS)


def is_own(lead: Dict[str, Any]) -> bool:
    """Our own people (some write from gmail, filed under our company name)."""
    from app.services import mail_categorizer as mc
    from app.services.email_structure import OWN_COMPANIES
    name = (lead.get("company_name") or "").strip().lower()
    email = (lead.get("email") or "").lower()
    return name in {n.lower() for n in OWN_COMPANIES.values()} or mc._domain(email) in mc.OWN_DOMAINS


def due(state: Optional[Dict[str, Any]], now: datetime) -> bool:
    """Not touched yet, or its cooldown has passed."""
    return not state or not state.get("next_eligible_at") or state["next_eligible_at"] <= now


# ---------------------------------------------------------------------------
# the check-in text
# ---------------------------------------------------------------------------
_SCHEMA = {"type": "object", "additionalProperties": False,
           "properties": {"subject": {"type": "string", "maxLength": 80},
                          "body": {"type": "string", "maxLength": 900}},
           "required": ["subject", "body"]}

_SYSTEM = ("You write short, warm, plain-text business emails for a market research and fieldwork company. "
           "Never invent facts, prices, dates or numbers. Reply only with JSON.")

_ASK = {
    "quote_no_reply": "We sent {first} at {company} a quote for \"{what}\" a few weeks ago and have not heard back. "
                      "Write a brief, friendly nudge asking whether they had a chance to review it and if anything "
                      "should change (scope, sample, timing).",
    "positive_quiet": "{first} at {company} replied positively to us a while ago, but the conversation stopped. "
                      "Their reply: \"{context}\". Write a brief, friendly note picking the conversation back up "
                      "and offering a short call.",
    "dormant_client": "{company} is a past client ({first} worked with us, the last project was \"{what}\"), but "
                      "we have not been in touch for months. Write a brief, warm check-in asking about their "
                      "upcoming research plans and offering help with sample or fieldwork.",
}

_TEMPLATES = {
    "quote_no_reply": ("Re: {what}", "Hi {first},\n\nJust checking in on the quote we sent for {what}. Did you "
                       "get a chance to look at it? Happy to adjust the scope, sample or timings if that helps."),
    "positive_quiet": ("{reply_subject}", "Hi {first},\n\nPicking up our earlier conversation - would a short call "
                       "this week or next be useful to see where we can help {company}?"),
    "dormant_client": ("Checking in", "Hi {first},\n\nIt has been a while since we last worked together, so I "
                       "wanted to check in. Do you have any studies coming up where we could help with sample or "
                       "fieldwork?"),
}


def check_text(body: str, first: str, allowed_numbers: str) -> Optional[str]:
    """Why a model-written body is refused, or None when it is fine."""
    words = len(body.split())
    if words < 20 or words > 150:
        return f"{words} words"
    if re.search(r"https?://|www\.|[\[\]{}<>]|your (company|name)|company name", body, re.I):
        return "link or placeholder"
    for num in re.findall(r"\d[\d,.]*", body):
        if num.strip(".,") not in allowed_numbers:
            return f"invented number {num}"
    if first and first.lower() not in body.lower()[:80]:
        return "does not greet them by name"
    return None


_SIGN_OFF = re.compile(r"^\s*(best|best regards|kind regards|warm regards|regards|thanks|thank you|many thanks|"
                       r"sincerely|cheers|looking forward[^.]*)\s*[,!.]?\s*$", re.I)


def _trim_sign_off(body: str) -> str:
    """Cut at the model's own sign-off (and whatever name or placeholder it put
    under it); ours is added after."""
    lines = body.rstrip().splitlines()
    for i, line in enumerate(lines):
        if i >= 1 and _SIGN_OFF.match(line):
            lines = lines[:i]
            break
    return "\n".join(lines).rstrip()


def study_name(title: str) -> str:
    """'RFQ_Fitted Homes Study_HRG_SFW' -> 'Fitted Homes Study' (our RFQ codes
    are not for the client's eyes)."""
    t = re.sub(r"^\s*rfq\s*[_:\-]*\s*", "", title or "", flags=re.I)
    parts = [p for p in re.split(r"_+", t) if p.strip()]
    while len(parts) > 1 and re.fullmatch(r"[A-Z0-9]{2,5}", parts[-1].strip()):
        parts.pop()
    return " ".join(" ".join(parts).split()) or (title or "")


def company_display(name: str) -> str:
    """'hdfclife.com' reads badly in a letter; fall back to 'your team'."""
    n = (name or "").strip()
    if not n or "." in n or (n.islower() and " " not in n):
        return "your team"
    return n


def _reply_subject(original: Optional[str]) -> str:
    base = re.sub(r"^\s*((re|fw|fwd|r|aw)\s*:\s*|\[external\]\s*)+", "", original or "", flags=re.I).strip()
    return f"Re: {base}" if base else "Following up"


def write_check_in(kind: str, ctx: Dict[str, Any]) -> Dict[str, str]:
    """{'subject', 'body', 'source': 'ai'|'template', 'refused'?}."""
    first = ctx.get("first") or "there"
    fill = {"first": first, "company": company_display(ctx.get("company")),
            "what": study_name(ctx.get("what") or "") or "the study",
            "days": ctx.get("days") or "", "context": (ctx.get("context") or "")[:300],
            "reply_subject": _reply_subject(ctx.get("what"))}
    refused = ""
    if kind in _ASK:
        from leads.local_llm_gate import queue_wait
        from leads.local_slm_client import LocalSLMError, chat_json
        try:
            with queue_wait(300):  # a daily job; the one model slot is often busy
                got = chat_json(system=_SYSTEM, user=_ASK[kind].format(**fill) +
                                f" Greet them as \"Hi {first},\". No sign-off, no placeholders, under 90 words.",
                                max_tokens=320, json_schema=_SCHEMA, timeout=120)
            body = _trim_sign_off(str(got.get("body") or ""))
            subject = " ".join(str(got.get("subject") or "").split())[:80]
            allowed = " ".join(str(v) for v in fill.values())
            refused = check_text(body, first if first != "there" else "", allowed) or \
                ("no subject" if not subject else "")
            if not refused:
                # quote and reply stay in their own thread; a model subject can
                # leak our labels ("Positive response from ...")
                if kind == "quote_no_reply":
                    subject = _quote_subject(ctx, fill)
                elif kind == "positive_quiet":
                    subject = _reply_subject(ctx.get("what"))
                elif re.search(r"\b(positive|leads?|rfq|dormant|re-?engage\w*|follow[- ]?up email)\b", subject, re.I):
                    subject = _TEMPLATES[kind][0]
                return {"subject": subject, "body": body, "source": "ai"}
        except LocalSLMError as e:
            refused = f"model unavailable: {e}"
        except Exception as e:  # queue timeout, redis down
            refused = f"model call failed: {e}"
    subj, body = _TEMPLATES.get(kind, ("Checking in", "Hi {first},\n\nChecking in."))
    subject = _quote_subject(ctx, fill) if kind == "quote_no_reply" else subj.format(**fill)
    return {"subject": subject, "body": body.format(**fill), "source": "template", "refused": refused}


def _quote_subject(ctx: Dict[str, Any], fill: Dict[str, Any]) -> str:
    """The quote thread's own subject, so the draft stays in that thread."""
    return _reply_subject(ctx.get("thread_subject")) if ctx.get("thread_subject") else f"Re: {fill['what']}"


# ---------------------------------------------------------------------------
# finding them
# ---------------------------------------------------------------------------
def _last_seen(client) -> Dict[str, Dict[str, datetime]]:
    """Last mail either way, per address and per company site (from the
    address structures, refreshed by the mail-pool cycle)."""
    by_addr, by_site = {}, {}
    for d in client["email_automation"]["email_address_structures"].find(
            {"last_seen": {"$ne": None}}, {"last_seen": 1, "company_domain": 1}):
        ls = d["last_seen"]
        by_addr[d["_id"]] = ls
        site = d.get("company_domain")
        if site and (site not in by_site or ls > by_site[site]):
            by_site[site] = ls
    return {"addr": by_addr, "site": by_site}


def _site(email: str) -> str:
    from app.services import mail_categorizer as mc
    from app.services.rfq_from_mail import root_site
    d = mc._domain((email or "").lower())
    if not d or d in mc.WEBMAIL or d in mc.OWN_DOMAINS:
        return ""
    return root_site(d)


def _reply_on_thread(em, thread_ids: List[str], since: datetime) -> Optional[datetime]:
    """Latest inbound mail on the quote's own thread(s) after `since` -- a busy
    client writes about other studies all the time, so the company is no guide."""
    if not thread_ids:
        return None
    doc = em.find_one({"gmail_thread_id": {"$in": thread_ids}, "direction": "inbound",
                       "timestamp": {"$gt": since}}, {"timestamp": 1}, sort=[("timestamp", -1)])
    return doc["timestamp"] if doc else None


def _last_inbound_by_site(em) -> Dict[str, datetime]:
    """When each company last wrote to us (our own mail to them does not count)."""
    out: Dict[str, datetime] = {}
    for row in em.aggregate([
            {"$match": {"direction": "inbound", "from_email": {"$regex": "@"}}},
            {"$group": {"_id": {"$toLower": {"$arrayElemAt": [{"$split": ["$from_email", "@"]}, 1]}},
                        "last": {"$max": "$timestamp"}}}], allowDiskUse=True):
        site = _site("x@" + (row["_id"] or ""))
        if site and isinstance(row["last"], datetime) and (site not in out or row["last"] > out[site]):
            out[site] = row["last"]
    return out


def _email_time(em, ref) -> Optional[datetime]:
    from bson import ObjectId
    if not ref:
        return None
    q = None
    try:
        q = em.find_one({"_id": ObjectId(ref) if isinstance(ref, str) else ref}, {"timestamp": 1})
    except Exception:
        q = None
    q = q or em.find_one({"gmail_message_id": ref}, {"timestamp": 1})
    return (q or {}).get("timestamp")


def find_candidates(client, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    opp = client["crm_db"]["opportunities"]
    em = client["torpedo_gmail"]["email_metadata"]
    seen = _last_seen(client)
    out: List[Dict[str, Any]] = []

    # sites with something open -- not dormant
    open_sites = set()
    for o in opp.find({"status": "open"}, {"metadata.rfq.from_email": 1}):
        s = _site(((o.get("metadata") or {}).get("rfq") or {}).get("from_email"))
        if s:
            open_sites.add(s)

    for o in opp.find({"stage": "proposal", "status": "open"}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        email = (r.get("from_email") or r.get("contact_email") or "").lower()
        if not email:
            continue
        quoted_at = _email_time(em, r.get("quote_email_id"))
        if not quoted_at:
            continue  # no quote mail on record -- its date would only be a guess
        threads = [t for t in [r.get("gmail_thread_id")] + list(r.get("gmail_thread_ids") or []) if t]
        if quote_is_silent(quoted_at, _reply_on_thread(em, threads, quoted_at), now):
            last_msg = em.find_one({"gmail_thread_id": {"$in": threads}}, {"subject": 1},
                                   sort=[("timestamp", -1)]) if threads else None
            out.append({"kind": "quote_no_reply", "key": str(o["_id"]), "email": email,
                        "name": r.get("from_name") or "", "company": r.get("account_name") or "",
                        "what": o.get("title") or "", "mailbox_id": r.get("mailbox_id"),
                        "thread_id": r.get("gmail_thread_id"), "since": quoted_at,
                        "thread_subject": (last_msg or {}).get("subject") or "",
                        "days": (now - quoted_at).days, "linked": ("opportunity", str(o["_id"]))})

    for o in opp.find({"stage": "rfq", "status": "open"}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        rec = r.get("received_at") or o.get("created_at")
        if rec and rec < now - timedelta(days=UNQUOTED_DAYS):
            out.append({"kind": "rfq_not_quoted", "key": str(o["_id"]), "email": (r.get("from_email") or "").lower(),
                        "name": r.get("from_name") or "", "company": r.get("account_name") or "",
                        "what": o.get("title") or "", "since": rec, "days": (now - rec).days,
                        "linked": ("opportunity", str(o["_id"]))})

    le = client["email_automation"]["leads_enriched"]
    for lead in le.find({"lead_status": "Positive", "stage": {"$nin": ["won", "lost", "converted"]},
                         "email": {"$regex": "@"}}):
        if is_own(lead):
            continue
        email = lead["email"].strip().lower()
        last = max([t for t in (seen["addr"].get(email), (lead.get("mail_pool") or {}).get("last_contact_at"),
                                lead.get("outreach_replied_at")) if isinstance(t, datetime)], default=None)
        if positive_is_quiet(lead, last, now):
            triage = lead.get("reply_triage") or (lead.get("mail_pool") or {}).get("triage") or {}
            out.append({"kind": "positive_quiet", "key": email, "email": email, "name": lead.get("name") or "",
                        "company": lead.get("company_name") or "", "what": lead.get("reply_subject") or "",
                        "context": triage.get("reply_text") or triage.get("reason") or "",
                        "mailbox_id": triage.get("mailbox_id"), "thread_id": triage.get("gmail_thread_id"),
                        "since": last, "days": (now - last).days, "linked": ("lead", str(lead["_id"]))})

    clients: Dict[str, Dict[str, Any]] = {}
    for o in opp.find({"stage": "won"}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        email = (r.get("from_email") or r.get("contact_email") or "").lower()
        site = _site(email)
        won = o.get("won_at") or o.get("closed_at") or r.get("received_at")
        if not site or not isinstance(won, datetime):
            continue
        c = clients.get(site)
        if not c or won > c["won"]:
            clients[site] = {"won": won, "email": email, "name": r.get("from_name") or "",
                             "company": r.get("account_name") or site, "what": o.get("title") or "",
                             "mailbox_id": r.get("mailbox_id"), "id": str(o["_id"]),
                             "account_id": o.get("account_id")}
    inbound = _last_inbound_by_site(em)
    for site, c in clients.items():
        last = inbound.get(site)
        if is_dormant(last, c["won"], site in open_sites, now):
            out.append({"kind": "dormant_client", "key": site, "email": c["email"], "name": c["name"],
                        "company": c["company"], "what": c["what"], "mailbox_id": c["mailbox_id"],
                        "since": last or c["won"], "days": (now - (last or c["won"])).days,
                        "linked": ("account", str(c["account_id"])) if c.get("account_id")
                        else ("opportunity", c["id"])})

    # warmest first: the most recently quiet are the easiest to pick back up
    out.sort(key=lambda x: (PRIORITY.index(x["kind"]), x.get("days") or 0))
    return out


# ---------------------------------------------------------------------------
# acting on them
# ---------------------------------------------------------------------------
def _mailbox(client, mailbox_id) -> Dict[str, str]:
    from bson import ObjectId
    box = None
    if mailbox_id:
        try:
            box = client["torpedo_gmail"]["workspace_mailboxes"].find_one(
                {"_id": ObjectId(mailbox_id) if not isinstance(mailbox_id, ObjectId) else mailbox_id})
        except Exception:
            box = None
    return {"email": (box or {}).get("email") or "", "display_name": (box or {}).get("display_name") or ""}


def _task_open(client, task_id) -> bool:
    from bson import ObjectId
    try:
        oid = ObjectId(task_id) if not isinstance(task_id, ObjectId) else task_id
    except Exception:
        return False
    t = client["crm_db"]["tasks"].find_one({"_id": oid}, {"status": 1})
    return bool(t) and t.get("status") == "open"


def _suppressed(email: str) -> bool:
    try:
        from messaging import suppression
        return suppression.is_suppressed(email)
    except Exception:
        return False


def _create_draft(box: Dict[str, str], to: str, subject: str, body: str, thread_id: Optional[str]) -> Dict[str, Any]:
    from app.services.gmail_workspace_service import GmailWorkspaceService
    svc = GmailWorkspaceService(mongo_uri=os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                                db_name="torpedo_gmail")
    svc.load_service_account()
    return svc.create_draft(from_email=box["email"], to=[to], subject=subject, body_plain=body,
                            thread_id=thread_id, signature_html=svc.get_signature(box["email"]))


def run(client=None, now: Optional[datetime] = None, dry_run: bool = False,
        max_drafts: Optional[int] = None) -> Dict[str, Any]:
    """The daily sweep. dry_run: find and write nothing (no model calls)."""
    if client is None:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")
    now = now or datetime.utcnow()
    state = client["email_automation"]["reengagement"]
    le = client["email_automation"]["leads_enriched"]
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    budget = daily_draft_limit() if max_drafts is None else max_drafts
    budget -= state.count_documents({"drafted_at": {"$gte": day_start}})
    stats: Dict[str, Any] = {"found": {}, "due": 0, "drafts": 0, "ai": 0, "template": 0, "tasks": 0,
                             "skipped_optout": 0, "no_mailbox": 0, "waiting_for_draft_budget": 0, "errors": 0}
    cands = find_candidates(client, now)
    for c in cands:
        stats["found"][c["kind"]] = stats["found"].get(c["kind"], 0) + 1
    if dry_run:
        stats["sample"] = [{k: c.get(k) for k in ("kind", "company", "name", "email", "what", "days")}
                           for c in cands[:25]]
        return stats

    from app.services import crm_service
    for c in cands:
        sid = f"{c['kind']}:{c['key']}"
        st = state.find_one({"_id": sid})
        if not due(st, now):
            continue
        if st and st.get("task_id") and _task_open(client, st["task_id"]):
            # the last touch is still waiting on a person -- don't stack another
            state.update_one({"_id": sid}, {"$set": {
                "next_eligible_at": now + timedelta(days=COOLDOWN_DAYS[c["kind"]]), "updated_at": now}})
            continue
        email = c.get("email") or ""
        if email and (_suppressed(email) or le.count_documents({"email": email, "lead_status": "Negative"}, limit=1)):
            stats["skipped_optout"] += 1
            state.update_one({"_id": sid}, {"$set": {"kind": c["kind"], "status": "skipped_optout",
                                                     "next_eligible_at": now + timedelta(days=365)}}, upsert=True)
            continue
        wants_mail = c["kind"] != "rfq_not_quoted" and email
        if wants_mail and budget <= 0:
            stats["waiting_for_draft_budget"] += 1
            continue
        stats["due"] += 1
        first = _first(c.get("name") or "")
        doc = {"kind": c["kind"], "key": c["key"], "email": email, "name": c.get("name"),
               "company": c.get("company"), "what": c.get("what"), "last_contact_at": c.get("since"),
               "days_quiet": c.get("days"), "touched_at": now,
               "next_eligible_at": now + timedelta(days=COOLDOWN_DAYS[c["kind"]]), "updated_at": now}
        draft_note = ""
        if wants_mail:
            box = _mailbox(client, c.get("mailbox_id"))
            text = write_check_in(c["kind"], {"first": first, "company": c.get("company"), "what": c.get("what"),
                                              "days": c.get("days"), "context": c.get("context"),
                                              "thread_subject": c.get("thread_subject")})
            stats[text["source"]] += 1
            signer = (box.get("display_name") or "").split("@")[0].split(" ")[0].capitalize()
            body = text["body"] + (f"\n\nBest,\n{signer}" if signer else "")
            doc.update({"subject": text["subject"], "body": body, "text_source": text["source"],
                        "text_refused": text.get("refused") or None, "mailbox": box["email"]})
            if not box["email"]:
                stats["no_mailbox"] += 1
                doc["status"] = "stored"
                draft_note = "No mailbox on record -- the text is below, send it from the right mailbox:"
            else:
                try:
                    res = _create_draft(box, email, text["subject"], body, c.get("thread_id"))
                except Exception as e:
                    res = {"success": False, "error": str(e)}
                if res.get("success"):
                    stats["drafts"] += 1
                    budget -= 1
                    doc.update({"status": "drafted", "draft_id": res.get("draft_id"), "drafted_at": now})
                    draft_note = f"Draft ready in Gmail ({box['email']}) -- review and send:"
                else:
                    stats["errors"] += 1
                    doc.update({"status": "stored", "error": str(res.get("error"))[:300]})
                    draft_note = f"Draft could not be created ({str(res.get('error'))[:120]}); text:"
        else:
            doc["status"] = "task_only"
        who = c.get("name") or email or c.get("company") or "?"
        title = TASK_TITLES[c["kind"]].format(what=(c.get("what") or "")[:80], who=who,
                                              company=c.get("company") or who)
        desc = f"Quiet for {c.get('days')} days ({c.get('company') or ''}, {email})."
        if draft_note:
            desc += f"\n\n{draft_note}\n\n{doc['body']}"
        try:
            kind_, obj_id = c.get("linked") or ("", "")
            task = crm_service.create("tasks", {
                "title": title, "description": desc, "linked_object_type": kind_, "linked_object_id": obj_id,
                "lead_email": email, "due_date": now + timedelta(days=2), "status": "open",
                "source": "reengagement", "reengagement_kind": c["kind"]})
            doc["task_id"] = task.get("_id")
            stats["tasks"] += 1
        except Exception as e:
            logger.warning("reengagement: task failed for %s: %s", sid, e)
            stats["errors"] += 1
        state.update_one({"_id": sid}, {"$set": doc, "$inc": {"touches": 1}}, upsert=True)
    logger.info("[Reengagement] %s", stats)
    return stats


def summary(client, now: Optional[datetime] = None) -> Dict[str, Any]:
    """For the dashboard: open touches by kind, and drafts waiting this week."""
    now = now or datetime.utcnow()
    col = client["email_automation"]["reengagement"]
    by_kind = {r["_id"]: r["n"] for r in col.aggregate([
        {"$match": {"status": {"$in": ["drafted", "stored", "task_only"]},
                    "touched_at": {"$gte": now - timedelta(days=30)}}},
        {"$group": {"_id": "$kind", "n": {"$sum": 1}}}])}
    drafts = col.count_documents({"status": "drafted", "drafted_at": {"$gte": now - timedelta(days=7)}})
    return {"by_kind": by_kind, "drafts_this_week": drafts}
