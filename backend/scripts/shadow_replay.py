"""
Shadow replay: the whole mail pool, oldest first, through the sales ->
finance/operations flow (sales-module points 3-8), as if each week's mail had
just arrived.

ISOLATION -- production is never written:
  * Everything runs against a SEPARATE mongod (SHADOW_URI, default
    mongodb://127.0.0.1:27018/). MONGO_URI is pointed there before any backend
    module is imported, so every module's own connection lands there.
  * Production is read through exactly one connection (SOURCE_URI), opened
    before a guard that makes any other MongoClient to the production port
    raise. A module that tries to reach production fails loudly.
  * Gmail send/draft, SMTP and every outside HTTP call are intercepted and
    recorded in the shadow `replay.outbox` collection instead of executed.
  * Rules only: no local-model calls (the model is shared with production and
    would need days for this volume). Mail the rules cannot place stays
    "pending model"; the report counts it.

WHAT IS REAL AND WHAT IS SIMULATED
  Real production code: segregation (mail_categorizer), client/vendor leads,
  reply triage, won conversion (sales/mailpool_leads), nurture
  (sales/nurture), RFQ + won + handoff (crm_service, won_handoff), project
  close + invoice (routers/operations), overdue/reminders/reconcile/CA pack
  (finance_automation).
  Simulated -- no mail-driven trigger exists; in production a person clicks:
    RFQ     one RFQ per thread a client opened with an RFQ (production uses
            the model-based mail_pool_ai for this, which cannot run here);
            title = subject, description = the mail's extracted summary
    won     a client's mail in an open RFQ thread with award language (PO,
            "go ahead", "please proceed", "awarded"...); the amount is the
            largest currency amount in that mail, if any
    close   30 days after the won thread's last message
  Static reference data copied from production as it is today: party
  relationships, outreach campaigns, Finance vendor records.

Usage (on the VM, shadow mongod already running on 27018):
  python scripts/shadow_replay.py --reset                 # full history
  python scripts/shadow_replay.py --reset --weeks 8       # smoke test
Report: printed at the end, and in shadow `replay.report`.
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta

SOURCE_URI = os.getenv("REPLAY_SOURCE_URI", "mongodb://127.0.0.1:27017/")
SHADOW_URI = os.getenv("REPLAY_SHADOW_URI", "mongodb://127.0.0.1:27018/")
SOURCE_PORT = 27017
REPLAY_DBS = ("torpedo_gmail", "email_automation", "crm_db", "finance_db", "torpedo", "replay")

# ---------------------------------------------------------------------------
# 1. isolation -- before any backend import
# ---------------------------------------------------------------------------
for var in ("MONGO_URI", "MONGODB_URI", "MONGO_URL", "MONGODB_URL"):
    os.environ[var] = SHADOW_URI
os.environ["MAIL_AI_ENABLED"] = "false"
os.environ["NURTURE_AUTO_SEND"] = "false"

import pymongo  # noqa: E402

SOURCE = pymongo.MongoClient(SOURCE_URI, serverSelectionTimeoutMS=5000)
SHADOW = pymongo.MongoClient(SHADOW_URI, serverSelectionTimeoutMS=5000)
SHADOW.admin.command("ping")
SOURCE.admin.command("ping")
assert SHADOW.address[1] != SOURCE_PORT, "shadow must not be the production mongod"
assert SOURCE.address[1] == SOURCE_PORT

_orig_client_init = pymongo.MongoClient.__init__


def _guarded_init(self, host=None, port=None, *args, **kwargs):
    target = f"{host or 'localhost'}:{port or ''}"
    if host is None or f":{SOURCE_PORT}" in target or port == SOURCE_PORT or (
            isinstance(host, str) and "27018" not in host and "mongodb://" in host):
        raise RuntimeError(f"[replay guard] refused a MongoClient to {target!r} -- "
                           f"only the shadow ({SHADOW_URI}) is allowed")
    _orig_client_init(self, host, port, *args, **kwargs)


pymongo.MongoClient.__init__ = _guarded_init

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _outbox(kind, **data):
    SHADOW["replay"]["outbox"].insert_one({"kind": kind, "at": SIM.now, **data})


class ReplayBlocked(RuntimeError):
    pass


def _block_network():
    import smtplib
    import urllib.request

    import requests

    def _req(self, method, url, *a, **k):
        if "127.0.0.1" in str(url) or "localhost" in str(url):
            _outbox("local_http_blocked", method=method, url=str(url)[:200])
        else:
            _outbox("http", method=method, url=re.sub(r"key=[^&]+", "key=***", str(url))[:200])
        raise ReplayBlocked(f"network blocked in replay: {method} {str(url)[:80]}")

    requests.Session.request = _req

    def _urlopen(url, *a, **k):
        _outbox("http", method="urlopen", url=str(getattr(url, "full_url", url))[:200])
        raise ReplayBlocked("network blocked in replay (urlopen)")

    urllib.request.urlopen = _urlopen

    def _smtp(self, *a, **k):
        _outbox("smtp", args=[str(x) for x in a][:2])
        raise ReplayBlocked("SMTP blocked in replay")

    smtplib.SMTP.__init__ = _smtp
    smtplib.SMTP_SSL.__init__ = _smtp
    try:
        import httpx

        def _hx(self, request, *a, **k):
            _outbox("http", method=request.method, url=str(request.url)[:200])
            raise ReplayBlocked("httpx blocked in replay")

        async def _ahx(self, request, *a, **k):
            _hx(self, request)

        httpx.Client.send = _hx
        httpx.AsyncClient.send = _ahx
    except ImportError:
        pass


def _stub_gmail():
    from app.services.gmail_workspace_service import GmailWorkspaceService as G
    counter = {"n": 0}

    def _fake(kind):
        def f(self, *a, **k):
            counter["n"] += 1
            _outbox(kind, to=k.get("to"), subject=k.get("subject"), from_email=k.get("from_email"))
            mid = f"replay-{kind}-{counter['n']}"
            return {"success": True, "message_id": mid, "thread_id": k.get("thread_id") or mid,
                    "draft_id": mid, "id": mid}
        return f

    G.send_email = _fake("gmail_send")
    G.create_draft = _fake("gmail_draft")
    G.get_signature = lambda self, *a, **k: ""
    G.load_service_account = lambda self, *a, **k: None
    G.is_configured = lambda self, *a, **k: True


# ---------------------------------------------------------------------------
# 2. simulated clock
# ---------------------------------------------------------------------------
class SIM:
    now = datetime(2017, 1, 1)


class _SimMeta(type):
    # Modules do isinstance(ts, datetime) on values read from Mongo (plain
    # datetimes). With datetime swapped for this subclass that check failed and
    # the first replay never saw a reply as "fresh", so nurture never started.
    def __instancecheck__(cls, obj):
        return isinstance(obj, datetime)


class SimDatetime(datetime, metaclass=_SimMeta):
    @classmethod
    def utcnow(cls):
        return SIM.now

    @classmethod
    def now(cls, tz=None):
        return SIM.now


def _install_clock(*modules):
    for m in modules:
        if getattr(m, "datetime", None) is datetime:
            m.datetime = SimDatetime


# ---------------------------------------------------------------------------
# 3. simulated human decisions
# ---------------------------------------------------------------------------
_AWARD = re.compile(
    r"\b(purchase order|p\.?o\.? (no|number|#|attached|is attached)|please (go ahead|proceed)|"
    r"go[- ]ahead|you can (start|proceed|go ahead)|we (would like to|will|can) (proceed|go ahead|start)|"
    r"approved (the|your) (quote|proposal|costing|cost|estimate)|(project|study|job) (is )?(awarded|confirmed)|"
    r"awarded (to you|the (project|study))|let'?s (go ahead|proceed|start))\b", re.I)
_MONEY = re.compile(r"(USD|US\$|\$|INR|Rs\.?|₹|EUR|€|GBP|£)\s?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(\.[0-9]+)?", re.I)
_CUR = {"usd": "USD", "us$": "USD", "$": "USD", "inr": "INR", "rs": "INR", "rs.": "INR", "₹": "INR",
        "eur": "EUR", "€": "EUR", "gbp": "GBP", "£": "GBP"}
CLOSE_AFTER_DAYS = 30


def largest_amount(text):
    best = None
    for m in _MONEY.finditer(text or ""):
        try:
            v = float(m.group(2).replace(",", "") + (m.group(3) or ""))
        except ValueError:
            continue
        if v >= 50 and (best is None or v > best[0]):
            best = (v, _CUR.get(m.group(1).lower().rstrip(), "USD"))
    return best


# ---------------------------------------------------------------------------
# 4. replay
# ---------------------------------------------------------------------------
_SRC_PROJECTION = {
    "mailbox_id": 1, "gmail_message_id": 1, "gmail_thread_id": 1, "direction": 1,
    "from_email": 1, "from_name": 1, "to_emails": 1, "cc_emails": 1, "subject": 1,
    "snippet": 1, "timestamp": 1, "has_attachments": 1,
    "body_plain": {"$substrCP": [{"$ifNull": ["$body_plain", ""]}, 0, 6000]},
}


def reset_shadow():
    for name in REPLAY_DBS:
        SHADOW.drop_database(name)
    src_ea, src_t, src_f = SOURCE["email_automation"], SOURCE["torpedo"], SOURCE["finance_db"]
    for doc in src_ea["party_relationships"].find():
        SHADOW["email_automation"]["party_relationships"].insert_one(doc)
    for doc in src_t["outreach_campaigns_v2"].find():
        SHADOW["torpedo"]["outreach_campaigns_v2"].insert_one(doc)
    for doc in src_f["vendors"].find():
        SHADOW["finance_db"]["vendors"].insert_one(doc)
    # Nurture drafts from the mailbox the prospect wrote to; without the
    # mailbox list every step was "stored" (third replay, 2026-09-28).
    for doc in SOURCE["torpedo_gmail"]["workspace_mailboxes"].find({}, {"email": 1, "display_name": 1,
                                                                        "is_active": 1}):
        SHADOW["torpedo_gmail"]["workspace_mailboxes"].insert_one(doc)
    em = SHADOW["torpedo_gmail"]["email_metadata"]
    for keys in (("timestamp",), ("gmail_thread_id",), ("from_email",), ("direction", "timestamp")):
        em.create_index([(k, 1) for k in keys])


def copy_week(start, end):
    docs = list(SOURCE["torpedo_gmail"]["email_metadata"].aggregate([
        {"$match": {"timestamp": {"$gte": start, "$lt": end}}},
        {"$project": _SRC_PROJECTION}], allowDiskUse=True))
    if docs:
        SHADOW["torpedo_gmail"]["email_metadata"].insert_many(docs, ordered=False)
    sends = list(SOURCE["torpedo"]["outreach_sends_v2"].find({"sent_at": {"$gte": start, "$lt": end}}))
    if sends:
        SHADOW["torpedo"]["outreach_sends_v2"].insert_many(sends, ordered=False)
    return docs


class Replay:
    def __init__(self):
        from app.services import crm_service, finance_automation, mail_categorizer, won_handoff
        from routers import operations
        from sales import mailpool_leads, nurture, reply_triage
        self.mc, self.ml, self.crm = mail_categorizer, mailpool_leads, crm_service
        self.fa, self.ops, self.nurture = finance_automation, operations, nurture
        _install_clock(mailpool_leads, nurture, reply_triage, won_handoff, finance_automation,
                       crm_service, operations)
        self.stats = defaultdict(Counter)
        self.errors = defaultdict(list)
        self.threads = SHADOW["replay"]["threads"]
        self.last_month = None

    def _err(self, stage, e):
        self.stats[stage]["errors"] += 1
        if len(self.errors[stage]) < 15:
            self.errors[stage].append(f"{SIM.now:%Y-%m-%d}: {type(e).__name__}: {str(e)[:200]}\n"
                                      + "".join(traceback.format_exc().splitlines(True)[-4:])[:600])

    def week(self, start, end):
        SIM.now = end
        docs = copy_week(start, end)
        self.stats["mail"]["inbound"] += sum(d.get("direction") == "inbound" for d in docs)
        self.stats["mail"]["outbound"] += sum(d.get("direction") == "outbound" for d in docs)
        if not docs:
            self.finance(end)
            return
        ctx = None
        try:  # point 3: segregation
            ctx = self.mc.build_context(SHADOW)
            r = self.mc.run_rules_pass(SHADOW, ctx=ctx)
            for k, v in r["by_category"].items():
                self.stats["3_category"][k] += v
            self.stats["3_segregation"]["pending_model"] += r["pending_ai"]
            self.stats["3_segregation"]["system_mail"] += r["system"]
        except Exception as e:
            self._err("3_segregation", e)
        try:  # points 3, 4, 6: client/vendor leads, triage, won conversion
            ml = self.ml
            m = ml.run_message_pass(SHADOW, ctx)
            for k, v in m["by_party"].items():
                self.stats["3_party"][k] += v
            for party, fn in (("client", ml.upsert_client_leads), ("vendor", ml.upsert_vendor_leads)):
                recent = {r["_id"] for r in ml.contact_rollup(SHADOW, party, since=start)}
                rows = [r for r in ml.contact_rollup(SHADOW, party) if r["_id"] in recent] if recent else []
                out = fn(SHADOW, rows, end)
                self.stats[f"3_{party}_leads"]["created"] += out["created"]
                self.stats[f"3_{party}_leads"]["updated"] += out["updated"]
            self.stats["6_converted_leads"]["converted"] += ml.convert_won_leads(SHADOW, end)
            t = ml.run_triage_pass(SHADOW, ctx, use_model=False)
            for k, v in t.items():
                self.stats["4_triage"][k] += v
        except Exception as e:
            self._err("3_4_6_leads", e)
        try:  # point 5: nurture steps due this week (drafts are recorded, not made)
            n = self.nurture.run_nurture_due_batch(limit=200)
            for k, v in n.items():
                self.stats["5_nurture"][k] += v
        except Exception as e:
            self._err("5_nurture", e)
        week_ids = [d["_id"] for d in docs]
        self.rfqs(week_ids)
        self.wins(week_ids)
        self.closes(end)
        self.finance(end)

    def rfqs(self, ids):
        em = SHADOW["torpedo_gmail"]["email_metadata"]
        for d in em.find({"_id": {"$in": ids}, "direction": "inbound", "mail_party": "client",
                          "ai_tier1_category": "rfq"}).sort("timestamp", 1):
            tid = d.get("gmail_thread_id")
            if not tid or self.threads.find_one({"_id": tid}):
                continue
            first = em.find_one({"gmail_thread_id": tid}, sort=[("timestamp", 1)])
            if (first or {}).get("direction") == "outbound":
                continue  # we opened it: we were buying
            try:
                sender = (d.get("from_email") or "").lower()
                domain = sender.split("@")[-1]
                company = self.ml._company_from_domain(domain) or sender
                account, _ = self.crm.get_or_create_account(company, {"website": domain})
                contact, _ = self.crm.get_or_create_contact(sender, {"name": d.get("from_name") or ""})
                res = self.crm.create_rfq({
                    "title": (d.get("subject") or "RFQ")[:150], "account_id": account["_id"],
                    "contact_id": contact["_id"], "description": d.get("mail_summary") or "",
                    "source_email_id": str(d["_id"]), "received_at": d.get("timestamp"),
                    "source": "shadow_replay_rules"})
                self.threads.insert_one({"_id": tid, "opportunity_id": res["opportunity"]["_id"],
                                         "rfq_at": d.get("timestamp"), "status": "rfq",
                                         "last_message_at": d.get("timestamp")})
                self.stats["rfq"]["created"] += 1
            except Exception as e:
                self._err("rfq", e)

    def wins(self, ids):
        em = SHADOW["torpedo_gmail"]["email_metadata"]
        for d in em.find({"_id": {"$in": ids}}, {"gmail_thread_id": 1, "timestamp": 1}):
            self.threads.update_one({"_id": d.get("gmail_thread_id"), "last_message_at": {"$lt": d["timestamp"]}},
                                    {"$set": {"last_message_at": d["timestamp"]}})
        for d in em.find({"_id": {"$in": ids}, "direction": "inbound", "mail_party": "client"}).sort("timestamp", 1):
            t = self.threads.find_one({"_id": d.get("gmail_thread_id"), "status": "rfq"})
            if not t:
                continue
            from sales.reply_triage import strip_quoted
            text = f"{d.get('subject') or ''}\n{strip_quoted(d.get('body_plain') or '')}"
            if not _AWARD.search(text):
                continue
            try:
                amount = largest_amount(text)
                if amount:
                    self.crm.update("opportunities", t["opportunity_id"],
                                    {"amount": amount[0], "currency": amount[1]})
                    self.stats["7_won"]["with_amount"] += 1
                else:
                    self.stats["7_won"]["no_amount_in_mail"] += 1
                out = self.crm.mark_opportunity_won(t["opportunity_id"])
                h = (out or {}).get("handoff") or {}
                self.stats["7_won"]["won"] += 1
                for k in ("finance_customer_id", "work_order_id", "contract_id", "ops_project_id"):
                    self.stats["7_handoff"][k + (" ok" if h.get(k) else " missing")] += 1
                if h.get("error"):
                    self._err("7_handoff", RuntimeError(h["error"]))
                self.threads.update_one({"_id": t["_id"]}, {"$set": {
                    "status": "won", "won_at": d.get("timestamp"), "ops_project_id": h.get("ops_project_id"),
                    "amount": amount[0] if amount else 0}})
            except Exception as e:
                self._err("7_won", e)

    def closes(self, end):
        cutoff = end - timedelta(days=CLOSE_AFTER_DAYS)
        for t in self.threads.find({"status": "won", "last_message_at": {"$lt": cutoff}}):
            try:
                if not t.get("ops_project_id"):
                    self.stats["8_close"]["no_ops_project"] += 1
                    self.threads.update_one({"_id": t["_id"]}, {"$set": {"status": "closed_no_project"}})
                    continue
                res = self.ops.close_project(t["ops_project_id"], {"notes": "shadow replay: simulated close"})
                self.stats["8_close"]["closed"] += 1
                self.stats["8_close"]["final_invoice" if res.get("final_invoice") else "no_invoice_zero_value"] += 1
                self.threads.update_one({"_id": t["_id"]}, {"$set": {"status": "closed", "closed_at": end}})
            except Exception as e:
                self._err("8_close", e)
                self.threads.update_one({"_id": t["_id"]}, {"$set": {"status": "close_failed"}})

    def finance(self, end):
        try:
            self.stats["8_finance"]["marked_overdue"] += self.fa.mark_overdue_invoices(now=end) or 0
            r = self.fa.run_invoice_reminders(now=end)
            for k, v in (r or {}).items():
                self.stats["8_reminders"][k] += v if isinstance(v, int) else 0
            r = self.fa.auto_reconcile_payments(now=end)
            for k, v in (r or {}).items():
                self.stats["8_reconcile"][k] += v if isinstance(v, int) else 0
            month = (end.year, end.month)
            if self.last_month and month != self.last_month:
                r = self.fa.run_monthly_ca_pack(now=end) or {}
                self.stats["8_ca_pack"]["runs"] += 1
                self.stats["8_ca_pack"]["with_invoices"] += int(bool(r.get("invoices") or r.get("invoice_count")))
            self.last_month = month
        except Exception as e:
            self._err("8_finance", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and reseed the shadow databases")
    ap.add_argument("--weeks", type=int, default=0, help="stop after N weeks (0 = all)")
    ap.add_argument("--from", dest="start", default=None)
    args = ap.parse_args()

    _block_network()
    _stub_gmail()
    if args.reset:
        reset_shadow()
    replay = Replay()
    first = SOURCE["torpedo_gmail"]["email_metadata"].find_one(sort=[("timestamp", 1)])["timestamp"]
    start = datetime.fromisoformat(args.start) if args.start else first.replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    stop = datetime.utcnow()
    t0, weeks = time.time(), 0
    while start < stop and (not args.weeks or weeks < args.weeks):
        end = start + timedelta(days=7)
        replay.week(start, end)
        weeks += 1
        if weeks % 10 == 0:
            print(f"[replay] {end:%Y-%m-%d} weeks={weeks} mail={dict(replay.stats['mail'])} "
                  f"rfq={dict(replay.stats['rfq'])} won={dict(replay.stats['7_won'])} "
                  f"errors={sum(c['errors'] for c in replay.stats.values())} {time.time()-t0:.0f}s", flush=True)
        start = end

    outbox = Counter(d["kind"] for d in SHADOW["replay"]["outbox"].find({}, {"kind": 1}))
    report = {"finished_at": datetime.utcnow(), "weeks": weeks, "seconds": round(time.time() - t0),
              "stats": {k: dict(v) for k, v in replay.stats.items()}, "outbox": dict(outbox),
              "errors": dict(replay.errors)}
    SHADOW["replay"]["report"].insert_one(dict(report))
    print("REPLAY DONE")
    print(json.dumps(report, default=str, indent=1))


if __name__ == "__main__":
    main()
