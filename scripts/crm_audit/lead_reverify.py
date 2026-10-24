"""Re-verify every queued / not-yet-contacted outreach lead before outreach resumes
(owner, 2026-10-24; CRM plan 3.2 step 4).

Scope: torpedo.outreach_leads_v2 rows with workflow_status in QUEUED (still due
to receive mail), all three BUs.

Per lead:
  1. MX + syntax/role/disposable + our own history (bounced before, delivered,
     wrote to us, domain bounce rate, proven local-part pattern)
     -> leads/inhouse_verifier.verify()
  2. Skrapp: the account has only the email *finder* API; each lookup costs one
     email credit. With --skrapp, a lead passes Skrapp when Skrapp finds the
     SAME address for that name + domain. Without credits the lead stays
     `skrapp: pending`.

Outcome per lead:
  fail     invalid (no MX, role, disposable, syntax, bounced before) or risky
           domain (>= 30% bounces), or Skrapp found a DIFFERENT address
  pass     MX/history ok (valid|likely) AND Skrapp confirmed
  pending  MX/history ok or unknown, Skrapp not yet run

--apply (default is a dry run that writes nothing):
  fail    -> suppressed: true, suppressed_reason, suppressed_at,
             previous_workflow_status, workflow_status "suppressed", sendable False
             (flagged, never deleted; previous status kept for rollback)
  all     -> reverify: {verdict, why, skrapp, outcome, at}
A collection backup must be taken first (the script refuses --apply without
--backup-dir pointing at an existing dump).

Run from backend/:  venv/bin/python ../scripts/crm_audit/lead_reverify.py [--skrapp] [--apply --backup-dir DIR]
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.getcwd())
from pymongo import MongoClient  # noqa: E402

from leads.inhouse_verifier import Evidence, verify  # noqa: E402

QUEUED = ("not_started", "pending_scheduled", "in_sequence")
OK_VERDICTS = ("valid", "likely")
FAIL_VERDICTS = ("invalid", "risky")


def mask(e):
    u, _, d = (e or "").partition("@")
    return f"{u[:2]}***@{d}" if d else e


def split_name(name):
    parts = (name or "").strip().split()
    return (parts[0], parts[-1]) if len(parts) >= 2 else ((parts[0], "") if parts else ("", ""))


def skrapp_check(client, lead, spend):
    """'confirmed' | 'catch_all' | 'different:<masked>' | 'not_found' | 'no_credits' | 'pending' | 'skipped'.

    Always reads earlier Skrapp results (email_automation.skrapp_lookups, free).
    Only with spend=True does it call Skrapp for leads not in the cache
    (1 email credit each; refused by skrapp_client when credits are 0)."""
    from leads import skrapp_client as sc
    first, last = split_name(lead.get("name"))
    email = (lead.get("email") or "").lower()
    if not first or "@" not in email:
        return "skipped"
    domain = email.split("@")[1]
    hit = client["email_automation"]["skrapp_lookups"].find_one({"_id": sc._cache_key(first, last, domain, "")})
    if hit is None and not spend:
        return "pending"
    res = hit if hit is not None else (sc.find(client, first, last, domain=domain) or {})
    st = res.get("status")
    if st == "found":
        found = (res.get("email") or "").lower()
        if found != email:
            return f"different:{mask(found)}"
        return "confirmed" if (res.get("quality") or "valid") == "valid" else "catch_all"
    if st == "not_found":
        return "not_found"
    if st in ("monthly_limit", "no_credits"):
        return "no_credits"
    return st or "pending"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir")
    ap.add_argument("--skrapp", action="store_true", help="spend Skrapp credits (1 per lead)")
    a = ap.parse_args()
    if a.apply and not (a.backup_dir and os.path.isdir(a.backup_dir)):
        sys.exit("--apply needs --backup-dir pointing at a fresh dump of torpedo.outreach_leads_v2")

    client = MongoClient(os.environ["MONGO_URI"])
    t = client["torpedo"]
    col = t["outreach_leads_v2"]
    bu_of = {c["campaign_id"]: c.get("business") for c in t["outreach_campaigns_v2"].find({}, {"campaign_id": 1, "business": 1})}
    ev = Evidence(client)
    now = datetime.utcnow()

    stats = defaultdict(Counter)
    reasons = defaultdict(Counter)
    samples = defaultdict(list)
    writes = 0
    for lead in col.find({"workflow_status": {"$in": list(QUEUED)}},
                         {"email": 1, "name": 1, "campaign_id": 1, "workflow_status": 1, "sendable": 1}):
        bu = bu_of.get(lead.get("campaign_id"), "unknown")
        r = verify(lead.get("email"), lead.get("name"), ev)
        sk = "pending"
        if r["verdict"] in FAIL_VERDICTS:
            outcome, why = "fail", r["why"]
        else:
            sk = skrapp_check(client, lead, spend=a.skrapp)
            if sk.startswith("different:"):
                outcome, why = "fail", f"Skrapp found a different address ({sk.split(':', 1)[1]})"
            elif sk == "confirmed" and r["verdict"] in OK_VERDICTS:
                outcome, why = "pass", r["why"] + "; Skrapp confirmed"
            else:
                outcome, why = "pending", f"{r['verdict']}: {r['why']}; skrapp={sk}"
        stats[bu][outcome] += 1
        stats[bu][f"verdict_{r['verdict']}"] += 1
        stats[bu][f"skrapp_{sk.split(':')[0]}"] += 1
        if outcome == "fail":
            reasons[bu][why.split(" (")[0]] += 1
        if len(samples[(bu, outcome)]) < 3:
            samples[(bu, outcome)].append(f"{mask(lead.get('email'))} [{lead.get('workflow_status')}] {why}")
        if a.apply:
            upd = {"reverify": {"verdict": r["verdict"], "why": why, "skrapp": sk, "outcome": outcome, "at": now}}
            if outcome == "fail":
                upd.update({"suppressed": True, "suppressed_reason": f"reverify_2026-10-24: {why}",
                            "suppressed_at": now, "previous_workflow_status": lead.get("workflow_status"),
                            "previous_sendable": lead.get("sendable"),
                            "workflow_status": "suppressed", "sendable": False})
            col.update_one({"_id": lead["_id"]}, {"$set": upd})
            writes += 1

    out = {"mode": "apply" if a.apply else "dry-run", "skrapp_requested": a.skrapp, "at": now.isoformat(),
           "per_bu": {bu: dict(c) for bu, c in stats.items()},
           "fail_reasons": {bu: dict(c) for bu, c in reasons.items()},
           "samples": {f"{k[0]}/{k[1]}": v for k, v in samples.items()},
           "writes": writes}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
