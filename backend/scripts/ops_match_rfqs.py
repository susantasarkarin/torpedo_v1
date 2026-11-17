"""Link ops_projects to RFQs in crm_db.opportunities. DRY RUN by default.

Usage (repo root):
  python backend/scripts/ops_match_rfqs.py                         # dry run, counts to stdout
  python backend/scripts/ops_match_rfqs.py --report out.json       # dry run + JSON report
  python backend/scripts/ops_match_rfqs.py --apply --backup-dir D  # backup first, then write

Tiers, first tier that yields exactly one opportunity wins:
  legacy-link      legacy traffic docs behind the project's suppliers carry rfqId/opportunity_id
  title-exact      projectName == opportunity title (case-insensitive, whitespace collapsed)
  title-normalized same, after stripping RE:/FW:/Fwd: prefixes, ' - <vendor>' suffixes and punctuation
A tier yielding >1 opportunities is disambiguated only by account name (project clientName ==
account name). If still >1, the project is left unmatched with rfqCandidates (max 5) and the
cascade stops there (a later, looser tier must not silently pick one of them).

Never touches a project that already has rfqId or a rfqMatch.method of 'manual'.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from bson import ObjectId  # noqa: E402

SCRIPT_USER = "ops_match_rfqs"
ACTION = "project.rfq_match"
TIERS = ("legacy-link", "title-exact", "title-normalized")
CANDIDATE_LIMIT = 5

_PREFIX = re.compile(r"^\s*(re|fw|fwd)\s*:\s*", re.I)
_VENDOR_SUFFIX = re.compile(r"\s+-\s+(research\s+desk|lucid[\s_]*new|lucid|sfw)\s*$", re.I)
_PUNCT = re.compile(r"[\W_]+")
_WS = re.compile(r"\s+")


def collapse(s: Any) -> str:
    """Whitespace-collapsed, casefolded."""
    return _WS.sub(" ", str(s or "")).strip().casefold()


def normalize_title(s: Any) -> str:
    t = str(s or "")
    while True:
        t2 = _PREFIX.sub("", t, count=1)
        if t2 == t:
            break
        t = t2
    while True:
        t2 = _VENDOR_SUFFIX.sub("", t, count=1)
        if t2 == t:
            break
        t = t2
    return collapse(_PUNCT.sub(" ", t))


def _ref(o: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(o["_id"]), "title": o.get("title"), "stage": o.get("stage")}


def _by_id(col, raw: Any) -> Optional[Dict[str, Any]]:
    key = str(raw)
    doc = col.find_one({"_id": key})
    if not doc and ObjectId.is_valid(key):
        doc = col.find_one({"_id": ObjectId(key)})
    return doc


# ------------------------------------------------------------------ planning

def _index(ctx) -> Dict[str, Any]:
    opps = list(ctx["opps"].find({}))
    idx = {"by_id": {str(o["_id"]): o for o in opps},
           "exact": defaultdict(list), "norm": defaultdict(list)}
    for o in opps:
        e, n = collapse(o.get("title")), normalize_title(o.get("title"))
        if e:
            idx["exact"][e].append(o)
        if n:
            idx["norm"][n].append(o)
    # project id -> legacy traffic doc ids (via live surveys -> live supplier links)
    survey_project = {str(s["_id"]): str(s.get("projectId"))
                      for s in ctx["surveys"].find({"is_deleted": {"$ne": True}})}
    links: Dict[str, set] = defaultdict(set)
    for r in ctx["suppliers"].find({"removed": {"$ne": True}}):
        pid = survey_project.get(str(r.get("surveyId")))
        if pid and r.get("legacyProjectId"):
            links[pid].add(str(r["legacyProjectId"]))
    oids = [ObjectId(x) for s in links.values() for x in s if ObjectId.is_valid(x)]
    legacy = {}
    if oids:
        legacy = {str(d["_id"]): d for d in ctx["legacy"].find(
            {"_id": {"$in": oids}, "is_deleted": {"$ne": True}})}
    idx["links"] = links
    idx["legacy"] = legacy
    return idx


def _account_name(ctx, cache: Dict[str, str], account_id: Any) -> str:
    if account_id is None:
        return ""
    key = str(account_id)
    if key not in cache:
        doc = _by_id(ctx["accounts"], key)
        cache[key] = collapse((doc or {}).get("name"))
    return cache[key]


def _resolve(ctx, idx, project, cands: List[Dict[str, Any]], accounts) -> Tuple[Optional[Dict], List[Dict]]:
    """Exactly one candidate -> it. More -> account-name disambiguation. Returns (opp, narrowed)."""
    if len(cands) == 1:
        return cands[0], []
    client = collapse(project.get("clientName"))
    if client:
        narrowed = [o for o in cands if _account_name(ctx, accounts, o.get("account_id")) == client]
        if len(narrowed) == 1:
            return narrowed[0], []
        if narrowed:
            cands = narrowed
    return None, cands


def _decide(ctx, idx, project, accounts) -> Dict[str, Any]:
    pid = str(project["_id"])
    link_opps: Dict[str, Dict[str, Any]] = {}
    for lid in idx["links"].get(pid, ()):
        legacy_doc = idx["legacy"].get(lid)
        if not legacy_doc:
            continue
        for key in ("rfqId", "opportunity_id"):
            v = legacy_doc.get(key)
            if v and str(v) in idx["by_id"]:
                link_opps[str(v)] = idx["by_id"][str(v)]
    pname = collapse(project.get("projectName"))
    tiers = [
        ("legacy-link", list(link_opps.values())),
        ("title-exact", idx["exact"].get(pname, []) if pname else []),
        ("title-normalized", idx["norm"].get(normalize_title(project.get("projectName")), [])
         if pname else []),
    ]
    for method, cands in tiers:
        if not cands:
            continue
        opp, narrowed = _resolve(ctx, idx, project, cands, accounts)
        if opp:
            return {"state": "matched", "method": method, "opp": opp, "candidates": []}
        return {"state": "ambiguous", "method": method,
                "candidates": [_ref(o) for o in narrowed[:CANDIDATE_LIMIT]]}
    return {"state": "unmatched", "method": None, "candidates": []}


def plan(ctx) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    idx = _index(ctx)
    accounts: Dict[str, str] = {}
    counts: Dict[str, Any] = {"projects": 0, "skipped_linked": 0, "skipped_manual": 0,
                              "matched": {t: 0 for t in TIERS}, "ambiguous": 0, "unmatched": 0}
    decisions = []
    for p in ctx["projects"].find({"is_deleted": {"$ne": True}}):
        counts["projects"] += 1
        if p.get("rfqId"):
            counts["skipped_linked"] += 1
            continue
        if (p.get("rfqMatch") or {}).get("method") == "manual":
            counts["skipped_manual"] += 1
            continue
        d = _decide(ctx, idx, p, accounts)
        stored = [c.get("id") for c in (p.get("rfqCandidates") or [])]
        row = {"_id": p["_id"], "projectNumber": p.get("projectNumber"),
               "projectName": p.get("projectName"), "clientName": p.get("clientName"),
               "state": d["state"], "method": d["method"], "candidates": d["candidates"],
               "storedCandidateIds": stored}
        if d["state"] == "matched":
            counts["matched"][d["method"]] += 1
            row["opp"] = d["opp"]
        elif d["state"] == "ambiguous":
            counts["ambiguous"] += 1
        else:
            counts["unmatched"] += 1
        decisions.append(row)
    return decisions, counts


# ------------------------------------------------------------------ apply

def write_backup(ctx, backup_dir: str, stamp: str) -> Tuple[str, int]:
    """Full ops_projects dump. Raises on any failure; the caller must not write then."""
    rows = list(ctx["projects"].find({}))
    out = Path(backup_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ops_projects_{stamp}.json"
    path.write_text(json.dumps(rows, default=str, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(json.loads(path.read_text(encoding="utf-8"))) != len(rows):
        raise RuntimeError(f"backup verification failed: {path}")
    return str(path), len(rows)


def apply_decisions(ctx, decisions: List[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    done = {"matched": 0, "candidates_updated": 0}
    for d in decisions:
        if d["state"] == "matched":
            o = d["opp"]
            ctx["projects"].update_one(
                {"_id": d["_id"], "rfqId": None, "rfqMatch.method": {"$ne": "manual"}},
                {"$set": {"rfqId": str(o["_id"]), "rfqTitle": o.get("title"),
                          "rfqStage": o.get("stage"),
                          "rfqMatch": {"method": d["method"], "matchedAt": now, "by": SCRIPT_USER},
                          "rfqCandidates": [], "updatedAt": now}})
            ctx["log"].insert_one({"ts": now, "userId": SCRIPT_USER, "projectId": str(d["_id"]),
                                   "surveyId": None, "action": ACTION, "field": "rfqId",
                                   "old": None, "new": str(o["_id"]), "method": d["method"]})
            done["matched"] += 1
        else:
            new_ids = [c["id"] for c in d["candidates"]]
            if new_ids != d["storedCandidateIds"]:
                ctx["projects"].update_one({"_id": d["_id"], "rfqId": None},
                                           {"$set": {"rfqCandidates": d["candidates"]}})
                done["candidates_updated"] += 1
    return done


# ------------------------------------------------------------------ CLI

def run(ctx, apply: bool = False, backup_dir: Optional[str] = None,
        now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.utcnow()  # naive UTC, same convention as ops_surveys._now()
    decisions, counts = plan(ctx)
    report: Dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "generatedAt": now.isoformat(),
        "counts": counts,
        "matches": [{"projectNumber": d["projectNumber"], "projectName": d["projectName"],
                     "method": d["method"], "rfqId": str(d["opp"]["_id"]),
                     "rfqTitle": d["opp"].get("title")}
                    for d in decisions if d["state"] == "matched"],
        "ambiguous": [{"projectNumber": d["projectNumber"], "projectName": d["projectName"],
                       "clientName": d["clientName"], "tier": d["method"],
                       "candidates": d["candidates"]}
                      for d in decisions if d["state"] == "ambiguous"],
        "unmatched": [{"projectNumber": d["projectNumber"], "projectName": d["projectName"],
                       "clientName": d["clientName"]}
                      for d in decisions if d["state"] == "unmatched"],
    }
    if apply:
        if not backup_dir:
            raise ValueError("apply requires a backup_dir")
        path, n = write_backup(ctx, backup_dir, now.strftime("%Y%m%dT%H%M%SZ"))
        report["backup"] = {"path": path, "projects": n}
        report["applied"] = apply_decisions(ctx, decisions, now)
    return report


def real_ctx() -> Dict[str, Any]:
    from database import get_email_automation_db
    from db import crm
    ea = get_email_automation_db()
    c = crm()
    return {"projects": ea["ops_projects"], "surveys": ea["ops_surveys"],
            "suppliers": ea["survey_suppliers"], "legacy": ea["projects"],
            "log": ea["ops_change_log"], "opps": c["opportunities"], "accounts": c["accounts"]}


def main(argv=None, ctx=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--report", help="write JSON report to this path")
    ap.add_argument("--backup-dir", help="ops_projects backup dir (required with --apply)")
    args = ap.parse_args(argv)
    if args.apply and not args.backup_dir:
        ap.error("--apply requires --backup-dir")
    try:
        report = run(ctx or real_ctx(), apply=args.apply, backup_dir=args.backup_dir)
    except Exception as exc:  # backup failure refuses the apply
        print(f"ABORTED, nothing written: {exc}", file=sys.stderr)
        return 2
    if args.report:
        Path(args.report).write_text(json.dumps(report, default=str, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    c = report["counts"]
    print(f"mode={report['mode']} projects={c['projects']} skipped_linked={c['skipped_linked']} "
          f"skipped_manual={c['skipped_manual']}")
    print("matched by tier: " + ", ".join(f"{t}={n}" for t, n in c["matched"].items()))
    print(f"ambiguous={c['ambiguous']} unmatched={c['unmatched']}")
    if "applied" in report:
        print(f"backup={report['backup']['path']} applied={report['applied']}")
    if args.report:
        print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
