"""
The structure of every email address in the mail pool (owner, 2026-09-29):
susanta@cogentixresearch.com -> {first_name}@cogentixresearch.com, company
Cogentix Research, domain cogentixresearch.com.

  email_automation.email_address_structures  one per address: structure, name,
                                             company, domain, times seen
  email_automation.email_domain_structures   one per domain: which structures
                                             its people use, and how often
  email_automation.email_patterns            the lead-gen pattern store
                                             (leads/email_pattern_system.py):
                                             a domain's proven structure is
                                             added when nothing stronger is on
                                             file -- it is how lead-gen builds
                                             addresses for new people there

Names come from the mail itself (the sender's display name) and from CRM
contacts / leads for addresses we only ever wrote to.
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from app.services import mail_categorizer as mc

logger = logging.getLogger(__name__)

ROLE_LOCALS = {"info", "sales", "support", "admin", "accounts", "account", "billing", "finance", "hr", "careers",
               "jobs", "contact", "hello", "team", "office", "marketing", "noreply", "no-reply", "enquiry",
               "enquiries", "inquiry", "projects", "project", "ops", "operations", "panel", "research",
               "accountspayable", "payables", "invoices", "procurement", "purchase", "bd", "business"}
_NONALPHA = re.compile(r"[^a-z]")
_NAME_NOISE = re.compile(r"\(.*?\)|\[.*?\]|\|.*$|<.*?>|\bvia\b.*$|\"|'", re.I)


def split_name(display: str) -> Tuple[str, str]:
    """'Keya Kundu | Hansa Research Group' -> ('keya', 'kundu')."""
    s = _NAME_NOISE.sub(" ", display or "")
    if "," in s:  # 'Chin, Alfred'
        last, _, first = s.partition(",")
        s = f"{first} {last}"
    parts = [_NONALPHA.sub("", p.lower()) for p in s.split()]
    parts = [p for p in parts if len(p) > 1]
    if not parts:
        return "", ""
    return parts[0], (parts[-1] if len(parts) > 1 else "")


# (label shown to people, pattern-store form, render)
_STRUCTURES = [
    ("{first_name}.{last_name}", "{first}.{last}", lambda f, l: f"{f}.{l}"),
    ("{first_name}{last_name}", "{first}{last}", lambda f, l: f"{f}{l}"),
    ("{first_name}_{last_name}", "{first}_{last}", lambda f, l: f"{f}_{l}"),
    ("{first_name}-{last_name}", "{first}-{last}", lambda f, l: f"{f}-{l}"),
    ("{first_initial}{last_name}", "{f}{last}", lambda f, l: f"{f[:1]}{l}"),
    ("{first_initial}.{last_name}", "{f}.{last}", lambda f, l: f"{f[:1]}.{l}"),
    ("{first_name}{last_initial}", "{first}{l}", lambda f, l: f"{f}{l[:1]}"),
    ("{first_name}.{last_initial}", "{first}.{l}", lambda f, l: f"{f}.{l[:1]}"),
    ("{last_name}.{first_name}", "{last}.{first}", lambda f, l: f"{l}.{f}"),
    ("{last_name}{first_name}", "{last}{first}", lambda f, l: f"{l}{f}"),
    ("{last_name}{first_initial}", "{last}{f}", lambda f, l: f"{l}{f[:1]}"),
]


def structure_of(email: str, first: str, last: str) -> Tuple[str, Optional[str]]:
    """-> (structure label, pattern-store form or None).
    'susanta@cogentixresearch.com', 'susanta', 'sarkar' -> ('{first_name}', '{first}')."""
    local = (email or "").split("@")[0].lower()
    clean = re.sub(r"\d+$", "", local)
    if clean in ROLE_LOCALS or local in ROLE_LOCALS:
        return f"role:{local}", None
    if first:
        if last:
            for label, form, render in _STRUCTURES:
                if render(first, last) == clean:
                    return label + ("{digits}" if clean != local else ""), form
        if clean == first:
            return "{first_name}" + ("{digits}" if clean != local else ""), "{first}"
        if last and clean == last:
            return "{last_name}", "{last}"
    return "unknown", None


OWN_COMPANIES = {"cogentixresearch": "Cogentix Research", "surveyfieldwork": "Survey Fieldwork",
                 "bimwavesolutions": "BIMwave Solutions"}
_MESSY_NAME = re.compile(r"[(|_@]|\s-\s|\bvia\b", re.I)


def _company_names(client) -> Dict[str, str]:
    """company root -> company name, from CRM accounts and Finance customers
    (read-only). Names that are really people or variants ('Hansa Research
    Group - dooblo', 'Adarsh V (Phoenixdatainnov)') are skipped; of the rest
    the one used most wins, the shorter on a tie."""
    from app.services.rfq_from_mail import registrable_root
    cands: Dict[str, Counter] = defaultdict(Counter)
    for a in client["crm_db"]["accounts"].find({}, {"name": 1, "website": 1}):
        nm = (a.get("name") or "").strip()
        if not nm or _MESSY_NAME.search(nm):
            continue
        d = re.sub(r"^(https?://)?(www\.)?", "", (a.get("website") or "").lower()).split("/")[0]
        if d:
            cands[registrable_root(d)][nm] += 2
    for c in client["finance_db"]["customers"].find({"email": {"$regex": "@"}}, {"company_name": 1, "name": 1, "email": 1}):
        nm = (c.get("company_name") or c.get("name") or "").strip()
        d = mc._domain(c["email"].lower())
        if nm and d and d not in mc.WEBMAIL and not _MESSY_NAME.search(nm):
            cands[registrable_root(d)][nm] += 1
    # the rebuilt RFQs carry the cleanest names ('Hansa Research Group',
    # 'Rakuten Insight'), resolved per sender domain
    for o in client["crm_db"]["opportunities"].find({"metadata.rfq.account_name": {"$nin": [None, ""]}},
                                                    {"metadata.rfq.account_name": 1, "metadata.rfq.from_email": 1}):
        r = o["metadata"]["rfq"]
        nm, d = r["account_name"].strip(), mc._domain((r.get("from_email") or "").lower())
        if d and d not in mc.WEBMAIL and not _MESSY_NAME.search(nm):
            cands[registrable_root(d)][nm] += 3

    def best(root, names):
        # a name that is just the domain ('Hansaresearch') only if nothing better
        proper = {n: c for n, c in names.items() if re.sub(r"[^a-z0-9]", "", n.lower()) != root}
        pool = proper or names
        return sorted(pool.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]

    out = {root: best(root, names) for root, names in cands.items()}
    out.update(OWN_COMPANIES)
    return out


def _known_names(client) -> Dict[str, str]:
    """address -> display name from CRM contacts and leads."""
    names: Dict[str, str] = {}
    for coll, db, fields in (("contacts", "crm_db", ("name",)), ("leads_enriched", "email_automation", ("name",)),
                             ("vendor_leads", "email_automation", ("name",))):
        for d in client[db][coll].find({"email": {"$regex": "@"}}, {"email": 1, "name": 1, "first_name": 1,
                                                                   "last_name": 1}):
            nm = d.get("name") or f"{d.get('first_name') or ''} {d.get('last_name') or ''}".strip()
            if nm:
                names.setdefault(d["email"].strip().lower(), nm)
    return names


def bounced_addresses(client) -> set:
    """Every address that ever bounced: the suppression list (bounce,
    gmail_bounce) and outreach rows marked bounced. A structure learned from
    one of these may be the very guess that bounced."""
    out = set()
    for d in client["email_automation"]["suppression_list"].find(
            {"reason": {"$in": ["bounce", "gmail_bounce", "bounced", "hard_bounce"]}}, {"email": 1}):
        if d.get("email"):
            out.add(d["email"].strip().lower())
    for d in client["torpedo"]["outreach_leads_v2"].find(
            {"$or": [{"bounced": True}, {"workflow_status": "bounced"}]}, {"email": 1}):
        if d.get("email"):
            out.add(d["email"].strip().lower())
    return out


def backfill(client, since: Optional[datetime] = None, write_patterns: bool = True) -> Dict[str, int]:
    """Every address in the mail pool (or those seen since `since`).

    Only addresses that never bounced teach a domain its structure; one that
    has written to us is proven real and weighs double (owner, 2026-09-30:
    "use email structure of those mails which has no bounce")."""
    from pymongo import UpdateOne
    from app.services.rfq_from_mail import registrable_root, root_site
    em = client["torpedo_gmail"]["email_metadata"]
    ea = client["email_automation"]
    now = datetime.utcnow()
    seen: Dict[str, Dict[str, Any]] = {}
    match: Dict[str, Any] = {}
    if since:
        match["timestamp"] = {"$gte": since}
    for d in em.find(match, {"from_email": 1, "from_name": 1, "to_emails": 1, "cc_emails": 1, "timestamp": 1,
                             "direction": 1}):
        ts = d.get("timestamp")
        addrs = []
        if d.get("from_email"):
            addrs.append((d["from_email"], d.get("from_name") or "", True))
        for r in (d.get("to_emails") or []) + (d.get("cc_emails") or []):
            if isinstance(r, str):
                addrs.append((r, "", False))
        for addr, nm, sender in addrs:
            a = addr.strip().lower()
            if not mc._domain(a):
                continue
            row = seen.setdefault(a, {"n": 0, "from_n": 0, "first": ts, "last": ts, "names": Counter()})
            row["n"] += 1
            if sender:
                row["from_n"] += 1
            if ts:
                row["first"] = min(row["first"] or ts, ts)
                row["last"] = max(row["last"] or ts, ts)
            if nm:
                row["names"][nm.strip()] += 1
    known = _known_names(client)
    companies = _company_names(client)
    bounced = bounced_addresses(client)
    ops, touched = [], set()
    stats = {"addresses": 0, "with_structure": 0, "role": 0, "unknown": 0, "bounced": 0, "wrote_to_us": 0}
    for a, row in seen.items():
        if not mc._domain(a) or "@" not in a:
            continue
        dom = mc._domain(a)
        root = registrable_root(dom)
        display = row["names"].most_common(1)[0][0] if row["names"] else known.get(a, "")
        first, last = split_name(display)
        label, form = structure_of(a, first, last)
        stats["addresses"] += 1
        stats["role" if label.startswith("role:") else "unknown" if label == "unknown" else "with_structure"] += 1
        is_bounced = a in bounced
        stats["bounced"] += is_bounced
        stats["wrote_to_us"] += row["from_n"] > 0
        if dom not in mc.WEBMAIL:
            touched.add(dom)
        company = companies.get(root) or ("" if dom in mc.WEBMAIL else root.replace("-", " ").title())
        ops.append(UpdateOne({"_id": a}, {"$set": {
            "email": a, "local_part": a.split("@")[0], "domain": dom, "company_domain": root_site(dom),
            "company_name": company, "name": display, "first_name": first, "last_name": last,
            "structure": f"{label}@{dom}" if not label.startswith("role:") else f"{a.split('@')[0]}@{dom}",
            "structure_kind": "role" if label.startswith("role:") else label,
            "times_seen": row["n"], "first_seen": row["first"], "last_seen": row["last"],
            "wrote_to_us": row["from_n"], "bounced": is_bounced, "pattern_form": form,
            "webmail": dom in mc.WEBMAIL, "updated_at": now}}, upsert=True))
        if len(ops) >= 2000:
            ea["email_address_structures"].bulk_write(ops, ordered=False)
            ops = []
    if ops:
        ea["email_address_structures"].bulk_write(ops, ordered=False)

    # per domain, from EVERY stored address there (a daily run sees one day
    # of mail; counting only that overwrote the full picture), bounce-free
    # only, an address that wrote to us counting double
    by_domain = domain_evidence(ea["email_address_structures"], touched)
    dops = []
    stats["domains"] = len(by_domain)
    stats["patterns_added"] = 0
    patterns = ea["email_patterns"]
    confirmed = set()
    for dom, counts in by_domain.items():
        form, n = counts.most_common(1)[0]
        total = sum(counts.values())
        dops.append(UpdateOne({"_id": dom}, {"$set": {
            "domain": dom, "company_name": companies.get(registrable_root(dom), ""),
            "structures": {k.replace(".", "·"): v for k, v in counts.items()},
            "dominant": f"{form}@{dom}", "people": total, "share": round(n / total, 2),
            "bounce_free": True, "updated_at": now}},
            upsert=True))
        if write_patterns and n >= 2 and n / total >= 0.6:
            confirmed.add(dom)
            conf = min(0.9, 0.55 + 0.1 * n)
            existing = patterns.find_one({"domain": dom}, {"source": 1, "confidence": 1})
            if not existing or existing.get("source") in ("guess", "analysis", "mail_pool") or                     float(existing.get("confidence") or 0) < conf:
                patterns.update_one({"domain": dom}, {"$set": {
                    "domain": dom, "pattern": f"{form}@{{domain}}", "confidence": conf, "source": "mail_pool",
                    "samples_analyzed": total, "last_verified": now, "discovered_at": now}}, upsert=True)
                stats["patterns_added"] += 1
    if dops:
        ea["email_domain_structures"].bulk_write(dops, ordered=False)
    # a mail-pool pattern whose evidence was only bounced addresses no longer stands
    if write_patterns and touched:
        stale = [d for d in touched if d not in confirmed]
        stats["patterns_retired"] = patterns.delete_many(
            {"domain": {"$in": stale}, "source": "mail_pool"}).deleted_count if stale else 0
    return stats


def domain_evidence(col, domains) -> Dict[str, Counter]:
    """domain -> {pattern form: weight} from bounce-free stored addresses."""
    out: Dict[str, Counter] = defaultdict(Counter)
    domains = list(domains)
    for i in range(0, len(domains), 500):
        for d in col.find({"domain": {"$in": domains[i:i + 500]}, "bounced": {"$ne": True},
                           "pattern_form": {"$nin": [None, ""]}},
                          {"domain": 1, "pattern_form": 1, "wrote_to_us": 1}):
            out[d["domain"]][d["pattern_form"]] += 2 if d.get("wrote_to_us") else 1
    return out
