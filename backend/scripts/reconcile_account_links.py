"""
ACCOUNT LINK RECONCILIATION — PHASE 0 (READ-ONLY)
=================================================
Proposes, but never applies, links between the operations/finance modules and
the canonical CRM spine (`crm_db.accounts`). Output is a CSV for human review.

WHY THIS IS PROPOSE-ONLY
------------------------
`crm_account_id` is not inert metadata — it gates two dormant code paths on
finance customers that currently no-op for unlinked records:

  * routers/finance.py update_customer  -> renaming a customer propagates the
    new name onto the linked spine account
  * routers/finance.py delete_customer  -> deleting a customer marks the linked
    spine account deleted

Backfilling turns those on. A wrong link means renaming client A silently
renames account B. Both paths write only into crm_db (never back into finance
or operations) and are best-effort/non-fatal, so the blast radius is
recoverable — but silently-wrong links are the worst kind to debug. Hence:
this script writes NOTHING. A human fills in `approved_account_id`, and the
apply step consumes that reviewed file rather than these proposals.

The money paths are unaffected either way: finance joins invoices, estimates
and payments on `customer_id`, never on `crm_account_id`.

MATCH TIERS (descending confidence, for triage only — none is auto-applied)
  exact    normalized name is identical to an account's name_normalized
  domain   email domain matches an account's, excluding personal domains
  fuzzy    single candidate after token-normalizing (drops Ltd/Inc/.com etc.)
  ambiguous  several candidates tied — always needs a human
  none     no candidate

`priority` flags rows that actually carry operational or financial weight
(projects and/or invoices). Link those first; leaving the long tail unlinked
is a safe state, wrongly linked is not.

Usage:
    python -m scripts.reconcile_account_links
    python -m scripts.reconcile_account_links --out review.csv --priority-only
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
CRM_DB_NAME = os.getenv("CRM_DB_NAME", "crm_db")

AUTOSYNC_SOURCE = "contact_autosync"

# Consolidated from the five divergent copies across the leads package
# (icp.py, phase5_agent.py, ai_classifier.py, ai_email_agents.py, router.py).
PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "hotmail.com",
    "outlook.com", "live.com", "aol.com", "icloud.com", "me.com", "msn.com",
    "protonmail.com", "proton.me", "rediffmail.com", "mail.com", "gmx.com",
    "yandex.com", "zoho.com",
}

# Suffixes stripped for fuzzy matching only — never for exact matching.
_NOISE = re.compile(
    r"\b(pvt|private|ltd|limited|llp|llc|inc|incorporated|corp|corporation|"
    r"co|company|group|holdings|technologies|technology|solutions|services|"
    r"research|consulting|consultants|international|india|global)\b",
    re.IGNORECASE,
)
_TLD = re.compile(r"\.(com|net|org|io|ai|co|in|co\.in|uk|us|biz|info)\b", re.IGNORECASE)


def normalize(name):
    """Mirror crm_service._normalize_name so 'exact' means exact to the spine."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def fuzzy_key(name):
    """Aggressively normalized key: drops legal suffixes, TLDs, punctuation."""
    s = _TLD.sub(" ", normalize(name))
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def domain_of(email):
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    domain = email.rsplit("@", 1)[1]
    return "" if domain in PERSONAL_DOMAINS else domain


def build_account_index(accounts):
    """Index spine accounts by exact / fuzzy / domain keys."""
    by_exact, by_fuzzy, by_domain = {}, defaultdict(list), defaultdict(list)
    for acc in accounts:
        name = acc.get("name") or ""
        exact = acc.get("name_normalized") or normalize(name)
        if exact:
            by_exact.setdefault(exact, acc)
        fkey = fuzzy_key(name)
        if fkey:
            by_fuzzy[fkey].append(acc)
        for field in ("email", "domain", "website"):
            dom = domain_of(acc.get(field)) if field == "email" else (acc.get(field) or "").strip().lower()
            dom = re.sub(r"^(https?://)?(www\.)?", "", dom).split("/")[0]
            if dom and dom not in PERSONAL_DOMAINS:
                by_domain[dom].append(acc)
    return by_exact, by_fuzzy, by_domain


def match(name, email, index):
    """Return (tier, candidates). Never decides — only proposes."""
    by_exact, by_fuzzy, by_domain = index

    hit = by_exact.get(normalize(name))
    if hit:
        return "exact", [hit]

    dom = domain_of(email)
    if dom and by_domain.get(dom):
        cands = by_domain[dom]
        return ("domain" if len(cands) == 1 else "ambiguous"), cands

    fkey = fuzzy_key(name)
    if fkey and by_fuzzy.get(fkey):
        cands = by_fuzzy[fkey]
        return ("fuzzy" if len(cands) == 1 else "ambiguous"), cands

    return "none", []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="account_link_review.csv",
                    help="CSV to write (review file)")
    ap.add_argument("--priority-only", action="store_true",
                    help="only emit rows that have projects or invoices")
    args = ap.parse_args()

    mongo = MongoClient(MONGO_URI)
    ops = mongo["email_automation"]
    fin = mongo["finance_db"]
    crm = mongo[CRM_DB_NAME]

    accounts = list(crm["accounts"].find(
        {}, {"name": 1, "name_normalized": 1, "email": 1, "domain": 1,
             "website": 1, "account_type": 1}))
    index = build_account_index(accounts)
    print(f"spine accounts ({CRM_DB_NAME}.accounts) ... {len(accounts)}")

    # Operational/financial weight, used only to rank what deserves review first.
    project_counts = defaultdict(int)
    for proj in ops["projects"].find({}, {"client": 1}):
        if proj.get("client"):
            project_counts[normalize(proj["client"])] += 1

    invoice_counts = defaultdict(int)
    for inv in fin["invoices"].find({}, {"customer_id": 1}):
        if inv.get("customer_id"):
            invoice_counts[str(inv["customer_id"])] += 1

    customers = list(fin["customers"].find(
        {"source": {"$ne": AUTOSYNC_SOURCE}},
        {"name": 1, "company_name": 1, "email": 1,
         "customer_number": 1, "crm_account_id": 1}))
    print(f"finance clients (excl. autosync) ...... {len(customers)}")
    print(f"operations project client strings ..... {len(project_counts)}")
    print(f"invoices with a customer_id ........... {sum(invoice_counts.values())}")

    rows = []
    tier_counts = defaultdict(int)

    # --- finance customers -> spine accounts ---
    for cust in customers:
        name = cust.get("company_name") or cust.get("name") or ""
        cust_id = str(cust["_id"])
        n_proj = project_counts.get(normalize(name), 0)
        n_inv = invoice_counts.get(cust_id, 0)

        if cust.get("crm_account_id"):
            tier, cands = "already_linked", []
        else:
            tier, cands = match(name, cust.get("email"), index)
        tier_counts[tier] += 1

        if args.priority_only and not (n_proj or n_inv):
            continue

        rows.append({
            "side": "finance_customer",
            "source_id": cust_id,
            "source_name": name,
            "source_email": cust.get("email") or "",
            "customer_number": cust.get("customer_number") or "",
            "projects": n_proj,
            "invoices": n_inv,
            "priority": "YES" if (n_proj or n_inv) else "",
            "match_tier": tier,
            "candidate_count": len(cands),
            "candidate_account_ids": "|".join(str(c["_id"]) for c in cands),
            "candidate_account_names": "|".join(c.get("name") or "" for c in cands),
            "existing_crm_account_id": cust.get("crm_account_id") or "",
            "approved_account_id": "",   # <- human fills this in
        })

    # --- operations project client strings -> spine accounts ---
    # projects.client is free text and carries no id, so it is reconciled by
    # its distinct string values rather than per-project.
    for client_norm, count in sorted(project_counts.items(), key=lambda kv: -kv[1]):
        sample = ops["projects"].find_one(
            {"client": {"$regex": f"^{re.escape(client_norm)}$", "$options": "i"}},
            {"client": 1})
        display = (sample or {}).get("client") or client_norm
        tier, cands = match(display, "", index)
        tier_counts[f"project:{tier}"] += 1

        rows.append({
            "side": "operations_project_client",
            "source_id": "",
            "source_name": display,
            "source_email": "",
            "customer_number": "",
            "projects": count,
            "invoices": 0,
            "priority": "YES",
            "match_tier": tier,
            "candidate_count": len(cands),
            "candidate_account_ids": "|".join(str(c["_id"]) for c in cands),
            "candidate_account_names": "|".join(c.get("name") or "" for c in cands),
            "existing_crm_account_id": "",
            "approved_account_id": "",
        })

    order = {"YES": 0, "": 1}
    rows.sort(key=lambda r: (order.get(r["priority"], 1),
                             -(r["projects"] + r["invoices"]),
                             r["source_name"].lower()))

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                                ["side", "source_name", "approved_account_id"])
        writer.writeheader()
        writer.writerows(rows)

    print("\nmatch tiers:")
    for tier, n in sorted(tier_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {tier:28} {n}")

    priority = sum(1 for r in rows if r["priority"] == "YES")
    print(f"\nrows written .......... {len(rows)} -> {args.out}")
    print(f"  priority (projects/invoices) ... {priority}")
    print(f"  long tail ...................... {len(rows) - priority}")
    print("\nREAD-ONLY: no documents were modified.")
    print("Next: fill in `approved_account_id` for rows you have verified. "
          "Blank rows stay unlinked, which is the safe state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
