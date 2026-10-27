"""Turn email_metadata.reanalysis_v2 into CRM updates (owner, 2026-10-27). Fill-only; dry run unless --apply.

    python3 backfill/mail_reanalysis_apply.py            # report only
    python3 backfill/mail_reanalysis_apply.py --apply    # needs a mongodump < 3 h old

  accounts   per sender domain: counts of relationship / category / unit from its mails.
             Written as account.mail_signal (always) and, only when the account has none,
             bu (one unit >= 70% of its non-"none" mails). kind is NEVER changed here:
             a domain whose mails say client/vendor but whose account kind is empty or
             different goes to account.mail_signal.suggested_kind for a person.
  rfqs       mails with is_rfq, status new/revision/clarification, not needs_review, confidence >= 0.8:
             - thread already an RFQ opportunity -> fill-only metadata.rfq.reanalysis (scope, budget text,
               deadline, status, unit) and opportunity.bu when empty
             - thread not an RFQ yet -> a row in email_automation.rfq_candidates (status new) for a person;
               no opportunity is created here
Stamped backfill.mail_reanalysis_apply.
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIN_RFQ_CONF = 0.8
CLIENT_SIDE = {"known_client", "prospect"}
VENDOR_SIDE = {"vendor", "service_provider"}


def dom(e):
    e = (e or "").lower()
    return e.rsplit("@", 1)[-1] if "@" in e else ""


def run(c, apply=False, now=None):
    now = now or datetime.utcnow()
    md, crm, ea = c.torpedo_gmail["email_metadata"], c.crm_db, c.email_automation
    stamp = {"backfill.mail_reanalysis_apply": now}
    rep, samples = Counter(), defaultdict(list)

    thread_opp = {}
    for o in crm.opportunities.find({"metadata.rfq": {"$exists": True}, "is_deleted": {"$ne": True}},
                                    {"bu": 1, "metadata.rfq.gmail_thread_id": 1, "metadata.rfq.gmail_thread_ids": 1}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        for t in [r.get("gmail_thread_id")] + list(r.get("gmail_thread_ids") or []):
            if t:
                thread_opp[t] = o
    have_cand = {x["message_id"] for x in ea.rfq_candidates.find({}, {"message_id": 1})}

    dstat = defaultdict(lambda: {"rel": Counter(), "cat": Counter(), "bu": Counter(), "n": 0})
    for m in md.find({"reanalysis_v2": {"$exists": True}},
                     {"from_email": 1, "subject": 1, "gmail_thread_id": 1, "timestamp": 1, "reanalysis_v2": 1}):
        r = m["reanalysis_v2"]
        d = dom(m.get("from_email"))
        if d and not r.get("needs_review"):
            s = dstat[d]
            s["n"] += 1
            s["rel"][r["sender_relationship"]] += 1
            s["cat"][r["email_category"]] += 1
            if r.get("business_unit") not in (None, "none"):
                s["bu"][r["business_unit"]] += 1
        if not (r.get("is_rfq") and r.get("rfq_status") in ("new", "revision", "clarification")
                and not r.get("needs_review") and float(r.get("confidence") or 0) >= MIN_RFQ_CONF):
            continue
        rep["rfq mails (confident)"] += 1
        opp = thread_opp.get(m.get("gmail_thread_id"))
        if opp:
            rep["rfq mail on an existing RFQ -> filled"] += 1
            if apply:
                upd = {"metadata.rfq.reanalysis": {k: r.get(k) for k in ("rfq_scope", "rfq_budget", "deadline", "rfq_status",
                                                                         "business_unit", "confidence")} | {"at": now},
                       **stamp}
                crm.opportunities.update_one({"_id": opp["_id"], "metadata.rfq.reanalysis": {"$exists": False}}, {"$set": upd})
                if not opp.get("bu") and r.get("business_unit") not in (None, "none"):
                    crm.opportunities.update_one({"_id": opp["_id"], "bu": {"$in": [None, ""]}},
                                                 {"$set": {"bu": r["business_unit"], **stamp}})
        elif str(m["_id"]) not in have_cand:
            rep["rfq mail with no RFQ yet -> rfq_candidates"] += 1
            if len(samples["new_rfq"]) < 12:
                samples["new_rfq"].append(f"{(m.get('subject') or '')[:60]} | {r['business_unit']} | {r['rfq_scope'][:50]}")
            if apply:
                ea.rfq_candidates.insert_one({"message_id": str(m["_id"]), "gmail_thread_id": m.get("gmail_thread_id"),
                                              "subject": m.get("subject"), "from_domain": d, "received_at": m.get("timestamp"),
                                              "rfq_scope": r.get("rfq_scope"), "rfq_budget": r.get("rfq_budget"),
                                              "deadline": r.get("deadline"), "business_unit": r.get("business_unit"),
                                              "confidence": r.get("confidence"), "status": "new", "created_at": now, **stamp})

    for d, s in dstat.items():
        acc = crm.accounts.find_one({"$or": [{"domain": d}, {"domain": "www." + d}], "is_deleted": {"$ne": True}},
                                    {"kind": 1, "bu": 1})
        if not acc:
            continue
        client = sum(s["rel"][x] for x in CLIENT_SIDE)
        vendor = sum(s["rel"][x] for x in VENDOR_SIDE)
        sig = {"mails": s["n"], "relationship": dict(s["rel"]), "category": dict(s["cat"]), "bu": dict(s["bu"]), "at": now}
        kind = acc.get("kind")
        if s["n"] >= 3 and vendor / s["n"] >= 0.7 and kind not in ("vendor", "both", "own"):
            sig["suggested_kind"] = "vendor"
        elif s["n"] >= 3 and client / s["n"] >= 0.7 and kind not in ("client", "both", "own"):
            sig["suggested_kind"] = "client"
        if sig.get("suggested_kind"):
            rep["account kind suggestion"] += 1
            if len(samples["kind"]) < 12:
                samples["kind"].append(f"{d}: kind={kind} -> {sig['suggested_kind']} ({s['n']} mails)")
        bu_total = sum(s["bu"].values())
        top = s["bu"].most_common(1)
        set_bu = None
        if not acc.get("bu") and top and bu_total >= 3 and top[0][1] / bu_total >= 0.7:
            set_bu = top[0][0]
            rep["account bu filled"] += 1
        rep["accounts with mail signal"] += 1
        if apply:
            crm.accounts.update_one({"_id": acc["_id"]}, {"$set": {"mail_signal": sig, **({"bu": set_bu} if set_bu else {}), **stamp}})
    return {**rep, "samples": dict(samples)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
        from sync_zoho_invoices import backup_age_hours
        if backup_age_hours() > 3:
            sys.exit("refusing to apply: newest mongodump is older than 3 h")
    from database import get_database
    c = type("", (), {"torpedo_gmail": get_database("torpedo_gmail"), "crm_db": get_database("crm_db"),
                      "email_automation": get_database("email_automation")})()
    out = run(c, apply=a.apply)
    samples = out.pop("samples", {})
    print("APPLIED" if a.apply else "DRY RUN", dict(sorted(out.items())))
    for k, v in samples.items():
        print("---", k)
        for s in v:
            print("   ", s)


if __name__ == "__main__":
    main()
