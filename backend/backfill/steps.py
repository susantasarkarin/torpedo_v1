"""Phase 4 backfill (CRM plan Section 5, LINKING_PLAN run order).

Every step: dry run by default (counts + masked samples, nothing written);
apply=True writes. Writes only fill empty fields or add flags -- nothing is
deleted and nothing already set is overwritten (where a value is replaced the
old one is kept under legacy.<field>). Each written document gets
backfill.<step> = timestamp, so a step can be found and undone. Ambiguous
cases go to the Review Queue, never guessed. Re-running a step is a no-op.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import UpdateMany, UpdateOne

OURS = {"surveyfieldwork.com", "cogentixresearch.com", "bimwavesolutions.com"}
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "rediffmail.com",
        "yahoo.co.in", "aol.com", "protonmail.com", "msn.com", "ymail.com", "googlemail.com", "zoho.com"}
SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc"}
SUFFIXES = r"\b(private|pvt|limited|ltd|llp|llc|inc|incorporated|corp|corporation|company|co|gmbh|plc|pte|sa|ag|bv|srl|the)\b"
BU_OF_DOMAIN = {"surveyfieldwork.com": "SFW", "cogentixresearch.com": "COGENTIX", "bimwavesolutions.com": "BIM"}
BU_OF_BRANCH = {"survey fieldwork": "SFW", "cogentix research": "COGENTIX", "bim wave solutions": "BIM"}
SUBJECT_TAG = re.compile(r"(?:^|[_\s\-\[(])(SFW|CGX|COGENTIX|CR|BIM)(?:$|[_\s\-\])])", re.I)
TAG_BU = {"SFW": "SFW", "CGX": "COGENTIX", "COGENTIX": "COGENTIX", "CR": "COGENTIX", "BIM": "BIM"}


def mask(e):
    u, _, d = (e or "").partition("@")
    return f"{u[:2]}***@{d}" if d else (e or "")[:40]


def reg_domain(v):
    if not v or not isinstance(v, str):
        return None
    v = v.strip().lower()
    if "@" in v:
        v = v.rsplit("@", 1)[1]
    v = re.sub(r"^[a-z]+://", "", v).split("/")[0].split(":")[0]
    v = re.sub(r"^www\d?\.", "", v).strip(".")
    parts = [p for p in v.split(".") if p]
    if len(parts) < 2 or not re.fullmatch(r"[a-z0-9.-]+", v):
        return None
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def business_domain(v) -> Optional[str]:
    d = reg_domain(v)
    return d if d and d not in FREE and d not in OURS else None


def norm_name(n):
    if not n or not isinstance(n, str):
        return ""
    n = n.lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(SUFFIXES, " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return re.sub(r"(^and\s+|\s+and$)", "", n).strip()


def majority_domain(emails: List[str]) -> Optional[str]:
    """The business domain held by more than half of an account's contacts."""
    doms = [d for d in (business_domain(e) for e in emails) if d]
    if not doms:
        return None
    top, n = Counter(doms).most_common(1)[0]
    return top if n * 2 > len(doms) else None


def plausible_domain(d: str) -> bool:
    label = d.split(".")[0]
    return 2 <= len(label) <= 30 and not re.search(r"\d{5,}", label)


def subject_bu(subject: str) -> Optional[str]:
    hits = {TAG_BU[m.upper()] for m in SUBJECT_TAG.findall(subject or "")}
    return hits.pop() if len(hits) == 1 else None


class AccountIndex:
    """Domain first, then normalised name: exact / fuzzy >= 0.90 auto,
    0.75-0.90 review, more than one candidate -> review."""

    def __init__(self, accounts):
        self.by_domain, self.by_name, self.by_token = defaultdict(set), defaultdict(set), defaultdict(set)
        for a in accounts:
            aid = str(a["_id"])
            for f in ("domain", "root_domain", "website"):
                d = business_domain(a.get(f))
                if d:
                    self.by_domain[d].add(aid)
            nn = norm_name(a.get("name"))
            if nn:
                self.by_name[nn].add(aid)
                self.by_token[nn.split()[0]].add(nn)

    def resolve(self, name, domain) -> Tuple[str, Optional[str], str]:
        if domain:
            hit = self.by_domain.get(domain)
            if hit:
                return ("auto", next(iter(hit)), "domain") if len(hit) == 1 else ("review", None, "domain matches >1 account")
        nn = norm_name(name)
        if not nn:
            return ("orphan", None, "no name or domain")
        if nn in self.by_name:
            ids = self.by_name[nn]
            return ("auto", next(iter(ids)), "name_exact") if len(ids) == 1 else ("review", None, "name matches >1 account")
        best, cand = 0.0, None
        for c in self.by_token.get(nn.split()[0], ()):
            r = SequenceMatcher(None, nn, c).ratio()
            if r > best:
                best, cand = r, c
        if best >= 0.90 and len(self.by_name[cand]) == 1:
            return ("auto", next(iter(self.by_name[cand])), f"name_fuzzy {best:.2f}")
        if best >= 0.75:
            return ("review", None, f"name_fuzzy {best:.2f}")
        return ("new", None, "no match")


# ---------------------------------------------------------------- helpers


def _flush(col, ops, apply, rep, chunk=1000):
    if apply and ops:
        for i in range(0, len(ops), chunk):
            r = col.bulk_write(ops[i:i + chunk], ordered=False)
            rep["modified"] = rep.get("modified", 0) + r.modified_count
    ops.clear()


def _review(apply, rep, **kw):
    rep["to_review"] = rep.get("to_review", 0) + 1
    if apply:
        from platform_core import review_queue
        review_queue.enqueue(**kw)


def _mark(step, now):
    return {f"backfill.{step}": now}


# ---------------------------------------------------------------- steps


def account_domains(c, apply=False, now=None):
    """1. accounts.domain from the majority business domain of their contacts."""
    now, rep, ops = now or datetime.utcnow(), Counter(), []
    emails = defaultdict(list)
    for ct in c.crm_db.contacts.find({"account_id": {"$nin": [None, ""]}, "email": {"$type": "string"}}, {"account_id": 1, "email": 1}):
        emails[str(ct["account_id"])].append(ct["email"])
    from reengage.runner import domain_last_seen
    mailed = set(domain_last_seen(c.torpedo_gmail.email_metadata))      # domains we actually exchanged mail with
    taken = defaultdict(set)
    for a in c.crm_db.accounts.find({"domain": {"$nin": [None, ""]}}, {"domain": 1}):
        taken[business_domain(a["domain"])].add(str(a["_id"]))
    samples = []
    for a in c.crm_db.accounts.find({"$or": [{"domain": None}, {"domain": ""}, {"domain": {"$exists": False}}],
                                     "merged_into": {"$exists": False}}, {"name": 1}):
        rep["accounts_without_domain"] += 1
        d = majority_domain(emails.get(str(a["_id"]), []))
        if not d:
            rep["no_majority_domain"] += 1
            continue
        if not plausible_domain(d) or d not in mailed:
            rep["domain_never_mailed_or_implausible"] += 1      # guessed contact emails, not evidence
            continue
        if taken.get(d):
            rep["domain_already_on_another_account"] += 1      # duplicate account: entity_link review
            _review(apply, rep, type="entity_link", module="linking", ref={"collection": "crm_db.accounts", "id": str(a["_id"])},
                    reason=f"its contacts' domain {d} already belongs to another account (possible duplicate)",
                    payload={"domain": d, "other_accounts": sorted(taken[d])})
            continue
        taken[d].add(str(a["_id"]))
        rep["domain_set"] += 1
        if len(samples) < 5:
            samples.append(f"{(a.get('name') or '')[:40]} -> {d}")
        ops.append(UpdateOne({"_id": a["_id"], "$or": [{"domain": None}, {"domain": ""}, {"domain": {"$exists": False}}]},
                             {"$set": {"domain": d, **_mark("account_domains", now)}}))
    _flush(c.crm_db.accounts, ops, apply, rep)
    return {**rep, "samples": samples}


def _live_account(c, aid, archived) -> Optional[str]:
    seen = set()
    while aid and aid not in seen:
        seen.add(aid)
        try:
            a = c.crm_db.accounts.find_one({"_id": ObjectId(aid)}, {"merged_into": 1})
        except Exception:
            a = None
        if a and not a.get("merged_into"):
            return aid
        nxt = (a or {}).get("merged_into") or archived.get(aid)
        aid = str(nxt) if nxt else None
    return None


def customer_links(c, apply=False, now=None):
    """3. finance customers pointing at merged/deleted accounts: follow
    merged_into, else re-resolve by name; flag smoke-test customers; our
    own companies -> review (inter-company?)."""
    now, rep = now or datetime.utcnow(), Counter()
    archived = {}
    for r in c.crm_db["_archived_records_20261003"].find({"merged_into": {"$exists": True}}, {"original_id": 1, "merged_into": 1, "record": 1}):
        oid = str(r.get("original_id") or (r.get("record") or {}).get("_id") or "")
        if oid:
            archived[oid] = str(r["merged_into"])
    idx = AccountIndex(c.crm_db.accounts.find({"merged_into": {"$exists": False}}, {"name": 1, "domain": 1, "website": 1}))
    ops = []
    for cu in c.finance_db.customers.find({"is_deleted": {"$ne": True}}, {"name": 1, "company_name": 1, "email": 1, "crm_account_id": 1}):
        name = cu.get("company_name") or cu.get("name") or ""
        if re.search(r"smoke|\.invalid$|^_", (name + " " + (cu.get("email") or "")).lower()):
            rep["smoke_test_flagged"] += 1
            ops.append(UpdateOne({"_id": cu["_id"], "is_test": {"$ne": True}}, {"$set": {"is_test": True, **_mark("customer_links", now)}}))
            continue
        if norm_name(name) in {"cogentix research", "cogentix researach", "survey fieldwork", "bim wave solutions"} or \
                reg_domain(cu.get("email")) in OURS:
            rep["own_company"] += 1
            _review(apply, rep, type="entity_link", module="linking", ref={"collection": "finance_db.customers", "id": str(cu["_id"])},
                    reason="customer is one of our own companies: inter-company record or a mistake?")
            continue
        cur = str(cu.get("crm_account_id") or "")
        live = _live_account(c, cur, archived) if cur else None
        if live and live == cur:
            rep["ok"] += 1
            continue
        if live:
            rep["followed_merge"] += 1
            ops.append(UpdateOne({"_id": cu["_id"]}, {"$set": {"crm_account_id": live, "legacy.crm_account_id": cur,
                                                                **_mark("customer_links", now)}}))
            continue
        outcome, aid, why = idx.resolve(name, business_domain(cu.get("email")))
        if outcome == "auto":
            rep["relinked_by_" + why.split()[0]] += 1
            ops.append(UpdateOne({"_id": cu["_id"]}, {"$set": {"crm_account_id": aid, "legacy.crm_account_id": cur or None,
                                                                **_mark("customer_links", now)}}))
        else:
            rep["unresolved_" + outcome] += 1
            _review(apply, rep, type="entity_link", module="linking", ref={"collection": "finance_db.customers", "id": str(cu["_id"])},
                    reason=f"finance customer has no live CRM account ({why})", payload={"name": name[:80]})
    _flush(c.finance_db.customers, ops, apply, rep)
    return dict(rep)


def mail_links(c, apply=False, now=None):
    """5. email_metadata: contact_id by counterparty email, else vendor /
    account by domain; internal and free-mail counted, not linked."""
    now, rep = now or datetime.utcnow(), Counter()
    contact = {}
    for ct in c.crm_db.contacts.find({"email": {"$type": "string"}}, {"email": 1, "account_id": 1}):
        contact[ct["email"].lower()] = (str(ct["_id"]), str(ct.get("account_id") or "") or None)
    vend = {}
    for v in c.finance_db.vendors.find({}, {"email": 1}):
        d = business_domain(v.get("email"))
        if d:
            vend.setdefault(d, str(v["_id"]))
    acct = defaultdict(set)
    for a in c.crm_db.accounts.find({"merged_into": {"$exists": False}, "domain": {"$nin": [None, ""]}}, {"domain": 1}):
        d = business_domain(a["domain"])
        if d:
            acct[d].add(str(a["_id"]))
    ops = []
    md = c.torpedo_gmail.email_metadata
    for g in md.aggregate([{"$match": {"mail_counterparty": {"$type": "string"}, "link.backfilled": {"$ne": True}}},
                           {"$group": {"_id": "$mail_counterparty", "n": {"$sum": 1}}}], allowDiskUse=True):
        raw_addr, n = g["_id"], g["n"]
        addr = raw_addr.strip().lower()
        dom = reg_domain(addr)
        s: Dict[str, Any] = {}
        if dom in OURS:
            rep["internal"] += n
            continue
        if addr in contact:
            s = {"contact_id": contact[addr][0], "account_id": contact[addr][1], "link_how": "contact_email"}
            rep["contact"] += n
        elif dom in FREE:
            rep["free_mail_unknown"] += n
            continue
        elif dom in vend:
            s = {"vendor_id": vend[dom], "sender_type_hint": "vendor", "link_how": "vendor_domain"}
            rep["vendor"] += n
        elif len(acct.get(dom, ())) == 1:
            s = {"account_id": next(iter(acct[dom])), "link_how": "account_domain"}
            rep["account"] += n
        elif len(acct.get(dom, ())) > 1:
            rep["domain_on_several_accounts"] += n
            continue
        else:
            rep["unlinked_domain"] += n
            continue
        s = {f"link.{k}": v for k, v in s.items() if v}
        ops.append(UpdateMany({"mail_counterparty": raw_addr, "link.backfilled": {"$ne": True}},
                              {"$set": {**s, "link.backfilled": True, **_mark("mail_links", now)}}))
        if len(ops) >= 1000:
            _flush(md, ops, apply, rep)
    _flush(md, ops, apply, rep)
    total = sum(v for k, v in rep.items() if k not in ("modified",))
    linked = rep["contact"] + rep["vendor"] + rep["account"]
    return {**rep, "linked_pct": round(100 * linked / total, 1) if total else None}


def _mailbox_bu(c) -> Dict[str, str]:
    out = {}
    for col in ("workspace_mailboxes", "mailboxes"):
        for b in c.torpedo_gmail[col].find({}, {"email": 1}):
            bu = BU_OF_DOMAIN.get(reg_domain(b.get("email")) or "")
            if bu:
                out[str(b["_id"])] = bu
    return out


def rfq_bu(c, apply=False, now=None):
    """6. RFQ BU: invoice branch of its project, else BU tag in the subject,
    else receiving mailbox; none -> Review Queue."""
    now, rep, ops = now or datetime.utcnow(), Counter(), []
    boxes = _mailbox_bu(c)
    inv_bu = {}
    for i in c.finance_db.invoices.find({"opportunity_id": {"$nin": [None, ""]}}, {"opportunity_id": 1, "branch": 1}):
        b = BU_OF_BRANCH.get((i.get("branch") or "").strip().lower())
        if b:
            inv_bu[str(i["opportunity_id"])] = b
    md = c.torpedo_gmail.email_metadata
    for o in c.crm_db.opportunities.find({"metadata.rfq.bu": {"$exists": False}}, {"title": 1, "metadata.rfq": 1}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        bu, how = inv_bu.get(str(o["_id"])), "invoice_branch"
        if not bu:
            bu, how = subject_bu(o.get("title") or r.get("title") or ""), "subject_tag"
        if not bu:
            mb = r.get("mailbox_id")
            if not mb and r.get("source_email_id") and ObjectId.is_valid(str(r["source_email_id"])):
                mb = (md.find_one({"_id": ObjectId(r["source_email_id"])}, {"mailbox_id": 1}) or {}).get("mailbox_id")
            bu, how = boxes.get(str(mb)), "receiving_mailbox"
        if bu:
            rep[f"{how}:{bu}"] += 1
            ops.append(UpdateOne({"_id": o["_id"], "metadata.rfq.bu": {"$exists": False}},
                                 {"$set": {"metadata.rfq.bu": bu, "metadata.rfq.bu_how": how, **_mark("rfq_bu", now)}}))
        else:
            rep["unknown"] += 1
            _review(apply, rep, type="entity_link", module="linking", ref={"collection": "crm_db.opportunities", "id": str(o["_id"])},
                    reason="RFQ BU unknown: no invoice, subject tag or BU mailbox")
    _flush(c.crm_db.opportunities, ops, apply, rep)
    return dict(rep)


def projects(c, apply=False, now=None):
    """6/8. Operations projects: lifecycle_status from legacy fields, BU from
    invoice branch or RFQ; completed with no invoice -> finance review."""
    from ops.lifecycle import legacy_status
    now, rep, ops = now or datetime.utcnow(), Counter(), []
    inv_by_proj = defaultdict(set)
    for i in c.finance_db.invoices.find({"ops_project_id": {"$nin": [None, ""]}}, {"ops_project_id": 1, "branch": 1}):
        b = BU_OF_BRANCH.get((i.get("branch") or "").strip().lower())
        inv_by_proj[str(i["ops_project_id"])].add(b)
    opp_bu = {str(o["_id"]): ((o.get("metadata") or {}).get("rfq") or {}).get("bu")
              for o in c.crm_db.opportunities.find({"metadata.rfq.bu": {"$exists": True}}, {"metadata.rfq.bu": 1})}
    for p in c.email_automation.projects.find({"is_deleted": {"$ne": True}}):
        pid = str(p["_id"])
        s = {}
        if not p.get("lifecycle_status"):
            st = legacy_status({**p, "invoice_ids": p.get("invoice_ids") or (["x"] if inv_by_proj.get(pid) else [])})
            s["lifecycle_status"] = st
            rep[f"status:{st}"] += 1
        if not p.get("bu"):
            bus = {b for b in inv_by_proj.get(pid, set()) if b}
            bu = bus.pop() if len(bus) == 1 else opp_bu.get(str(p.get("opportunity_id") or p.get("rfqId") or ""))
            if bu:
                s["bu"] = bu
                rep[f"bu:{bu}"] += 1
            else:
                rep["bu_unknown"] += 1
        if (p.get("status") == "completed") and not p.get("invoice_ids") and not inv_by_proj.get(pid):
            rep["completed_not_invoiced"] += 1
            _review(apply, rep, type="invoice_request", module="finance", ref={"collection": "email_automation.projects", "id": pid},
                    reason="completed project with no invoice linked (billed in Zoho without a link, or never billed?)",
                    payload={"project": (p.get("projectName") or "")[:80], "value": p.get("projectValue"), "currency": p.get("currency")})
        if s:
            ops.append(UpdateOne({"_id": p["_id"]}, {"$set": {**s, **_mark("projects", now)}}))
    _flush(c.email_automation.projects, ops, apply, rep)
    return dict(rep)


def estimates_archive(c, apply=False, now=None):
    """6. The auto-created draft estimates pointing at no RFQ: flag, keep."""
    now, rep = now or datetime.utcnow(), Counter()
    live = {o["_id"] for o in c.crm_db.opportunities.find({}, {"_id": 1})}
    live |= {str(x) for x in live}
    ops = []
    for e in c.finance_db.estimates.find({"status": "draft", "archived_backlog": {"$ne": True}}, {"opportunity_id": 1}):
        if e.get("opportunity_id") in live:
            rep["linked_kept"] += 1
            continue
        rep["archived"] += 1
        ops.append(UpdateOne({"_id": e["_id"]}, {"$set": {"archived_backlog": True, **_mark("estimates_archive", now)}}))
    _flush(c.finance_db.estimates, ops, apply, rep)
    return dict(rep)


def account_bu(c, apply=False, now=None):
    """7. Account BU = the entity that invoices it (majority branch), else its
    RFQs' BU (majority); a tie -> left empty (nothing guessed)."""
    now, rep, ops = now or datetime.utcnow(), Counter(), []
    by_acc = defaultdict(Counter)
    cust_acc = {str(cu["_id"]): str(cu.get("crm_account_id")) for cu in c.finance_db.customers.find({"crm_account_id": {"$nin": [None, ""]}}, {"crm_account_id": 1})}
    for i in c.finance_db.invoices.find({}, {"customer_id": 1, "branch": 1}):
        b = BU_OF_BRANCH.get((i.get("branch") or "").strip().lower())
        a = cust_acc.get(str(i.get("customer_id")))
        if a and b:
            by_acc[a]["inv:" + b] += 1
    for o in c.crm_db.opportunities.find({"metadata.rfq.bu": {"$exists": True}}, {"account_id": 1, "metadata.rfq.bu": 1}):
        by_acc[str(o.get("account_id"))]["rfq:" + o["metadata"]["rfq"]["bu"]] += 1
    for aid, cnt in by_acc.items():
        if not ObjectId.is_valid(aid):
            continue
        for kind in ("inv:", "rfq:"):
            sub = Counter({k[4:]: v for k, v in cnt.items() if k.startswith(kind)})
            if not sub:
                continue
            top = sub.most_common(2)
            if len(top) > 1 and top[0][1] == top[1][1]:
                rep["tie"] += 1
                break
            rep[f"{kind[:-1]}:{top[0][0]}"] += 1
            ops.append(UpdateOne({"_id": ObjectId(aid), "$or": [{"bu": {"$exists": False}}, {"bu": None}, {"bu": ""}]},
                                 {"$set": {"bu": top[0][0], "bu_how": "invoice_branch" if kind == "inv:" else "rfq_majority",
                                           **_mark("account_bu", now)}}))
            break
    _flush(c.crm_db.accounts, ops, apply, rep)
    return dict(rep)


def engagement_status(c, apply=False, now=None):
    """8. Stamp engagement_status on accounts with a relationship (the
    nightly job keeps it current once re-engagement is live)."""
    from reengage import rules
    from reengage.runner import domain_last_seen, last_two_way
    from crm360.view import BU_OF_DOMAIN as OWN, WEBMAIL
    now, rep, ops = now or datetime.utcnow(), Counter(), []
    seen = domain_last_seen(c.torpedo_gmail.email_metadata)
    cust_of = {str(x["crm_account_id"]): str(x["_id"]) for x in c.finance_db.customers.find({"crm_account_id": {"$nin": [None, ""]}}, {"crm_account_id": 1})}
    live = {str(p.get("customer_id")) for p in c.email_automation.projects.find({"status": "active", "is_deleted": {"$ne": True}}, {"customer_id": 1})}
    cdom = defaultdict(set)
    for ct in c.crm_db.contacts.find({"account_id": {"$nin": [None, ""]}, "email": {"$type": "string"}}, {"account_id": 1, "email": 1}):
        cdom[str(ct["account_id"])].add(ct["email"].rsplit("@", 1)[-1].lower())
    for a in c.crm_db.accounts.find({"merged_into": {"$exists": False}}, {"domain": 1, "dnd": 1}):
        doms = sorted({d.lower() for d in [a.get("domain"), *cdom.get(str(a["_id"]), ())] if d and d.lower() not in WEBMAIL and d.lower() not in OWN})
        tw, cust = last_two_way(seen, doms), cust_of.get(str(a["_id"]))
        if not tw and not cust and not a.get("dnd"):
            rep["prospect_untouched"] += 1
            continue
        st = rules.engagement_status(dnd=bool(a.get("dnd")), has_live_project=bool(cust) and cust in live, last_two_way=tw, now=now)
        rep[st] += 1
        ops.append(UpdateOne({"_id": a["_id"]}, {"$set": {"engagement_status": st, "engagement_checked_at": now,
                                                          **_mark("engagement_status", now)}}))
    _flush(c.crm_db.accounts, ops, apply, rep)
    return dict(rep)


INDEXES = [
    ("email_automation", "mail_decisions", [("message_id", 1)], {}),
    ("email_automation", "rfq_decisions", [("opportunity_id", 1)], {}),
    ("email_automation", "review_queue_items", [("status", 1), ("module", 1), ("created_at", 1)], {}),
    ("email_automation", "web_events", [("visitor_id", 1), ("at", -1)], {}),
    ("email_automation", "web_events", [("at", -1), ("bu", 1)], {}),
    ("email_automation", "web_visitors", [("visitor_id", 1)], {"unique": True}),
    ("email_automation", "web_visitors", [("last_seen", -1)], {}),
    ("email_automation", "kpi_snapshots", [("day", -1), ("bu", 1)], {}),
    ("email_automation", "ops_decisions", [("decided_at", -1)], {}),
    ("email_automation", "projects", [("bu", 1), ("lifecycle_status", 1)], {}),
    ("crm_db", "vendor_bids", [("ref_id", 1)], {}),
    ("crm_db", "service_projects", [("opportunity_id", 1)], {}),
    ("crm_db", "service_projects", [("bu", 1), ("status", 1)], {}),
    ("crm_db", "accounts", [("domain", 1)], {}),
    ("crm_db", "accounts", [("bu", 1), ("engagement_status", 1)], {}),
    ("crm_db", "opportunities", [("metadata.rfq.bu", 1), ("status", 1)], {}),
    ("finance_db", "bank_transactions", [("bu", 1), ("date", -1)], {}),
    ("finance_db", "bank_transactions", [("statement", 1)], {}),
    ("torpedo_gmail", "email_metadata", [("link.account_id", 1), ("timestamp", -1)], {}),
    ("torpedo_gmail", "email_metadata", [("link.contact_id", 1), ("timestamp", -1)], {}),
]


def indexes(c, apply=False, now=None):
    """Section 4: indexes for the new collections and link fields (background)."""
    rep = {"planned": len(INDEXES), "created": []}
    for db, col, keys, opts in INDEXES:
        if apply:
            rep["created"].append(c[db][col].create_index(keys, background=True, **opts))
    return rep


STEPS = [("indexes", indexes), ("account_domains", account_domains), ("customer_links", customer_links),
         ("rfq_bu", rfq_bu), ("projects", projects), ("estimates_archive", estimates_archive),
         ("account_bu", account_bu), ("mail_links", mail_links), ("engagement_status", engagement_status)]


BU_ENTITY = {"SFW": "SFW", "COGENTIX": "COGENTIX", "BIM": "BIM"}


def _fx_at(rates, cur, d):
    if (cur or "INR").upper() == "INR":
        return 1.0
    rs = [r for r in rates.get(cur.upper(), []) if r[0] <= d] or rates.get(cur.upper(), [])
    return rs[-1][1] if rs else None


def ledger_opening(c, apply=False, now=None):
    """3.9.19-20: post the existing (Zoho-imported) invoices into the per-entity
    journal (finance_db.journal) so its trial balance can be run in parallel
    with Zoho. Paid -> receipt into 1050 (until bank import matches it),
    written off -> 6100. One journal entry per source, never twice."""
    from accounting import ledger
    now, rep = now or datetime.utcnow(), Counter()
    rates = defaultdict(list)
    for r in c.finance_db.invoice_fx.find({}, {"currency": 1, "rate": 1, "rate_date": 1}).sort("rate_date", 1):
        rd = r.get("rate_date")
        if isinstance(rd, str):
            try:
                rd = datetime.fromisoformat(rd[:10])
            except ValueError:
                rd = None
        if r.get("rate") and isinstance(rd, datetime):
            rates[r["currency"].upper()].append((rd, float(r["rate"])))
    j = c.finance_db.journal
    have = {(e["source"]["type"], e["source"]["id"]) for e in j.find({}, {"source": 1})}
    new = []
    for i in c.finance_db.invoices.find({"status": {"$nin": ["draft", "void"]}, "is_deleted": {"$ne": True}}):
        ent = BU_ENTITY.get(BU_OF_BRANCH.get((i.get("branch") or "").strip().lower(), ""))
        num, d = i.get("invoice_number"), i.get("invoice_date")
        if not ent or not num or not isinstance(d, datetime):
            rep["skipped_no_entity_or_date"] += 1
            continue
        fx = _fx_at(rates, i.get("currency_code"), d)
        if fx is None:
            rep["skipped_no_fx"] += 1
            continue
        sub, tax = float(i.get("subtotal") or i.get("total") or 0), float(i.get("tax_total") or 0)
        total = round((sub + tax) * fx, 2)
        if total <= 0:
            rep["skipped_zero"] += 1
            continue
        meta = {"currency": (i.get("currency_code") or "INR").upper(), "fx_rate": fx if fx != 1.0 else None}
        if ("invoice", num) not in have:
            lines = [{"account": "1100", "debit": total, "party": str(i.get("customer_id"))},
                     {"account": "4000", "credit": round(sub * fx, 2)}]
            if tax:
                lines.append({"account": "2130", "credit": round(total - round(sub * fx, 2), 2)})
            new.append(ledger.entry(entity=ent, on=d, memo=f"Invoice {num} (imported)", lines=lines,
                                    source={"type": "invoice", "id": num}, **meta))
            rep[f"invoice:{ent}"] += 1
        paid = round(float(i.get("amount_paid") or 0) * fx, 2)
        if paid > 0 and ("receipt", num) not in have:
            new.append(ledger.entry(entity=ent, on=i.get("updated_at") or d, memo=f"Receipt {num} (imported, bank match pending)",
                                    lines=[{"account": "1050", "debit": min(paid, total)},
                                           {"account": "1100", "credit": min(paid, total), "party": str(i.get("customer_id"))}],
                                    source={"type": "receipt", "id": num}, **meta))
            rep["receipts"] += 1
        if i.get("status") == "written_off" and ("write_off", num) not in have:
            left = round(total - min(paid, total), 2)
            if left > 0:
                new.append(ledger.entry(entity=ent, on=i.get("updated_at") or d, memo=f"Write-off {num} (imported)",
                                        lines=[{"account": "6100", "debit": left},
                                               {"account": "1100", "credit": left, "party": str(i.get("customer_id"))}],
                                        source={"type": "write_off", "id": num}, **meta))
                rep["write_offs"] += 1
    for e in new:
        e.update(created_at=now, backfill={"ledger_opening": now})
    if apply and new:
        j.insert_many(new)
        j.create_index([("source.type", 1), ("source.id", 1)], unique=True)
        rep["inserted"] = len(new)
    tb = {}
    for ent in ("SFW", "COGENTIX", "BIM"):
        entries = list(j.find({"entity": ent})) if apply else [e for e in new if e["entity"] == ent]
        if entries:
            t = ledger.trial_balance(entries, ent)
            tb[ent] = {"balanced": t["balanced"], "debit": t["total_debit"], "ar_1100": round(sum(
                r["debit"] - r["credit"] for r in t["rows"] if r["account"] == "1100"), 2)}
    return {**rep, "trial_balance": tb}


STEPS.append(("ledger_opening", ledger_opening))


def lead_links(c, apply=False, now=None):
    """4. torpedo.outreach_leads_v2.crm_lead_id by exact email; a same-name +
    same-domain CRM lead with a different address goes to review, never auto."""
    now, rep, ops = now or datetime.utcnow(), Counter(), []
    by_email, by_name_dom = {}, defaultdict(list)
    for l in c.crm_db.leads.find({}, {"email": 1, "name": 1, "first_name": 1, "last_name": 1}):
        e = (l.get("email") or "").strip().lower()
        if e:
            by_email[e] = str(l["_id"])
        nm = norm_name(l.get("name") or f"{l.get('first_name') or ''} {l.get('last_name') or ''}")
        d = business_domain(e)
        if nm and d:
            by_name_dom[(nm, d)].append((str(l["_id"]), e))
    for o in c.torpedo.outreach_leads_v2.find({"crm_lead_id": {"$exists": False}}, {"email": 1, "name": 1, "first_name": 1, "last_name": 1}):
        e = (o.get("email") or "").strip().lower()
        if e in by_email:
            rep["exact_email"] += 1
            ops.append(UpdateOne({"_id": o["_id"]}, {"$set": {"crm_lead_id": by_email[e], **_mark("lead_links", now)}}))
            continue
        nm = norm_name(o.get("name") or f"{o.get('first_name') or ''} {o.get('last_name') or ''}")
        cands = by_name_dom.get((nm, business_domain(e))) if nm else None
        if cands:
            _review(apply, rep, type="entity_link", module="linking", ref={"collection": "torpedo.outreach_leads_v2", "id": str(o["_id"])},
                    reason="same name and company domain as a CRM lead, different address", payload={"candidates": [x[0] for x in cands[:3]]})
        else:
            rep["no_crm_lead"] += 1
    _flush(c.torpedo.outreach_leads_v2, ops, apply, rep)
    return dict(rep)


STEPS.append(("lead_links", lead_links))


def zoho_link(c, apply=False, now=None):
    """Zoho invoices -> the completed projects still marked 'no invoice'
    (the pending finance review items). See backfill/zoho_link.py."""
    from backfill import zoho_link as zl
    ids = {str((it.get("ref") or {}).get("id")) for it in c.email_automation.review_queue_items.find(
        {"status": "pending", "type": "invoice_request", "ref.collection": "email_automation.projects"}, {"ref": 1})}
    return zl.run(c, project_ids=ids, apply=apply, now=now)


STEPS.append(("zoho_link", zoho_link))
