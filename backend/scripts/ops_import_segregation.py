"""
IMPORT THE OWNER-APPROVED PROJECT > SURVEY > SUPPLIER SEGREGATION
=================================================================
Reads the approved paste (header line, then one entry per project) and writes it
into the new ops schema (email_automation):

  ops_projects      one per "P###" line (key: projectNumber)
  ops_surveys       one per survey (key: projectId + surveyName); surveyNumber from
                    counters {_id: 'ops_survey_number'}, first issued 100001
  survey_suppliers  one per supplier; legacyProjectId = _id of the legacy `projects`
                    doc (key: legacyProjectId, so re-runs never duplicate)

Paste format
    P001 Project name [Client]                       -> project + one survey
      Sup(surveyNo,Status), Sup(surveyNo,Status)     -> one survey (project name), all suppliers attached
    P013 Project name [Client]
      S1 label: Sup(surveyNo,Status)                 -> one survey per S-line
      S2 label: Sup(surveyNo,Status)
    P006 Project name [Client] -- no supplier        -> project only
Status words: Live / Paused / Closed (Closed -> completed).

Rollup (project and survey): any supplier Live -> live; else any Paused -> paused;
else completed. A project with no suppliers therefore gets completed.

Matching: the legacy doc is the live `projects` doc with that surveyNo (leading
zeros kept). Its vendorId must resolve in `vendors` (by vid), be active, and its
vendorName must equal the pasted supplier name (case-insensitive, spaces and
underscores ignored). Anything else lands in `problems` and is skipped.

    python backend/scripts/ops_import_segregation.py --file F                 # dry run
    python backend/scripts/ops_import_segregation.py --file F --apply         # write
          [--report R.json] [--backup-dir D]

Dry run writes nothing to the database. --apply first backs up the collections it
touches to JSON (aborts if the backup fails), then deletes superseded backfill
artifacts (ops_projects with backfilledFromSurveyId, ops_survey_links with
source 'backfill'), then imports.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("ops_import_segregation")

# Collection names mirror routers/ops_surveys.py (declared here so this script does
# not import the router module).
COL_PROJECTS = "projects"              # legacy: one doc per survey
COL_OPS_PROJECTS = "ops_projects"
COL_OPS_SURVEYS = "ops_surveys"
COL_LINKS = "ops_survey_links"
COL_SUPPLIERS = "survey_suppliers"
COL_CHANGE_LOG = "ops_change_log"
COL_VENDORS = "vendors"
COL_COUNTERS = "counters"

SURVEY_SEQ_ID = "ops_survey_number"
SURVEY_SEQ_START = 100000              # first issued surveyNumber is 100001
IMPORT_USER = "import"
TIMEZONE = "Asia/Kolkata"
DEAD_VENDOR_STATUSES = ("deleted", "inactive", "archived")
BACKUP_COLLECTIONS = (COL_OPS_PROJECTS, COL_OPS_SURVEYS, COL_SUPPLIERS, COL_LINKS,
                      COL_COUNTERS, COL_CHANGE_LOG)
IST = timezone(timedelta(hours=5, minutes=30))

PROJECT_RE = re.compile(r"^(P\d+)\s+(.*)$")
SLINE_RE = re.compile(r"^\s+S(\d+)\s+(.+?):\s*(.*)$")
SUPPLIER_RE = re.compile(r"([^(),]+?)\s*\((\d+),\s*(\w+)\)")
CLIENT_RE = re.compile(r"\[([^\[\]]*)\]\s*$")
NO_SUPPLIER_RE = re.compile(r"\s*--\s*no supplier\s*$", re.IGNORECASE)
STATUS_WORDS = {"live": "live", "paused": "paused", "closed": "completed"}


def _now() -> datetime:
    return datetime.utcnow()


def _problem(line: Optional[int], project_number: Optional[str], reason: str) -> Dict[str, Any]:
    return {"line": line, "projectNumber": project_number, "reason": reason}


def _norm_name(value: Any) -> str:
    return re.sub(r"[\s_]+", " ", str(value or "")).strip().lower()


def _is_deleted(doc: Dict[str, Any]) -> bool:
    return doc.get("is_deleted") is True or doc.get("deleted_at") is not None


def _rollup(statuses: List[str]) -> str:
    if "live" in statuses:
        return "live"
    if "paused" in statuses:
        return "paused"
    return "completed"


# ============================================================ parsing

def _parse_project_line(lineno: int, number: str, rest: str, problems: List[Dict[str, Any]]):
    no_supplier = bool(NO_SUPPLIER_RE.search(rest))
    rest = NO_SUPPLIER_RE.sub("", rest).strip()
    m = CLIENT_RE.search(rest)
    if not m:
        problems.append(_problem(lineno, number, "no [client] group at end of line"))
        return None
    name = rest[:m.start()].strip()
    client = m.group(1).strip()
    if not name or not client:
        problems.append(_problem(lineno, number, "empty project name or client"))
        return None
    return {"lineNo": lineno, "projectNumber": number, "projectName": name,
            "clientName": client, "noSupplier": no_supplier, "suppliers": []}


def _parse_supplier_line(lineno: int, line: str, project: Dict[str, Any],
                         problems: List[Dict[str, Any]]) -> None:
    label = None
    group = None
    body = line.strip()
    m = SLINE_RE.match(line)
    if m:
        group = ("S", m.group(1))
        label = m.group(2).strip()
        body = m.group(3)
    matches = list(SUPPLIER_RE.finditer(body))
    if not matches or body.count("(") != len(matches):
        problems.append(_problem(lineno, project["projectNumber"],
                                 f"unparsed supplier text: {body.strip()}"))
        return
    for mm in matches:
        name, surveyNo, word = mm.group(1).strip(), mm.group(2), mm.group(3)
        status = STATUS_WORDS.get(word.lower())
        if status is None:
            problems.append(_problem(lineno, project["projectNumber"],
                                     f"unknown status '{word}' for {name}({surveyNo})"))
            continue
        project["suppliers"].append({
            "lineNo": lineno, "name": name, "surveyNo": surveyNo, "status": status,
            "group": group or ("P", ""), "label": label,
        })


def parse_segregation(text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pure parser. Returns (projects, problems). The first line is the header."""
    projects: List[Dict[str, Any]] = []
    problems: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():
            m = PROJECT_RE.match(line)
            if not m:
                if lineno > 1:
                    problems.append(_problem(lineno, None, "unrecognised line"))
                current = None
                continue
            current = _parse_project_line(lineno, m.group(1), m.group(2), problems)
            if current is not None:
                projects.append(current)
            continue
        if current is None:
            problems.append(_problem(lineno, None, "supplier line without a valid project line"))
            continue
        _parse_supplier_line(lineno, line, current, problems)
    return projects, problems


# ============================================================ matching (read-only)

def _find_legacy(db, surveyNo: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    variants: List[Any] = [surveyNo]
    if surveyNo.isdigit():
        n = int(surveyNo)
        variants += [str(n), n]  # zero-stripped / int stored
    docs = [d for d in db[COL_PROJECTS].find({"surveyNo": {"$in": variants}}) if not _is_deleted(d)]
    if not docs:
        return None, f"no live legacy projects doc for surveyNo {surveyNo}"
    if len(docs) > 1:
        return None, f"{len(docs)} live legacy docs for surveyNo {surveyNo}"
    return docs[0], None


def _resolve_supplier(db, sup: Dict[str, Any]) -> Tuple[str, Any]:
    """Returns ('attached', legacyId) | ('problem', reason) | ('ok', info)."""
    legacy, err = _find_legacy(db, sup["surveyNo"])
    if err:
        return "problem", err
    lid = str(legacy["_id"])
    if db[COL_SUPPLIERS].find_one({"legacyProjectId": lid}):
        return "attached", lid
    vid = str(legacy.get("vendorId") or "").strip()
    if not vid:
        return "problem", f"legacy doc {lid} has no vendorId"
    vendor = db[COL_VENDORS].find_one({"vid": vid})
    if vendor is None:
        return "problem", f"vendor vid {vid} not in vendors"
    if str(vendor.get("status") or "").lower() in DEAD_VENDOR_STATUSES:
        return "problem", f"vendor vid {vid} is {vendor.get('status')}"
    if _norm_name(vendor.get("vendorName")) != _norm_name(sup["name"]):
        return "problem", (f"name mismatch: pasted '{sup['name']}' vs vendor "
                           f"'{vendor.get('vendorName')}' (vid {vid})")
    return "ok", {"legacyProjectId": lid, "surveyNo": sup["surveyNo"], "vendorId": vid,
                  "vendorName": vendor.get("vendorName"), "status": sup["status"],
                  "group": sup["group"], "label": sup["label"]}


def build_plan(db, parsed: List[Dict[str, Any]], problems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Read-only. Resolves every supplier and returns the projects to write."""
    plan: List[Dict[str, Any]] = []
    seen_numbers = set()
    seen_legacy = set()
    for proj in parsed:
        pn = proj["projectNumber"]
        if pn in seen_numbers:
            problems.append(_problem(proj["lineNo"], pn, "projectNumber appears twice in the file"))
            continue
        seen_numbers.add(pn)
        if proj["noSupplier"] and proj["suppliers"]:
            problems.append(_problem(proj["lineNo"], pn, "marked '-- no supplier' but lists suppliers"))
            continue

        ok: List[Dict[str, Any]] = []
        attached = 0
        for sup in proj["suppliers"]:
            kind, payload = _resolve_supplier(db, sup)
            if kind == "problem":
                problems.append(_problem(sup["lineNo"], pn, f"{sup['name']}({sup['surveyNo']}): {payload}"))
                continue
            lid = payload if kind == "attached" else payload["legacyProjectId"]
            if lid in seen_legacy:
                problems.append(_problem(sup["lineNo"], pn,
                                         f"{sup['name']}({sup['surveyNo']}): same legacy doc listed twice"))
                continue
            seen_legacy.add(lid)
            if kind == "attached":
                attached += 1
            else:
                ok.append(payload)

        if not proj["noSupplier"] and not ok and not attached:
            if proj["suppliers"]:
                problems.append(_problem(proj["lineNo"], pn, "no supplier could be imported; project skipped"))
            continue

        groups: "OrderedDict[Tuple[str, str], List[Dict[str, Any]]]" = OrderedDict()
        for item in ok:
            groups.setdefault(item["group"], []).append(item)
        survey_plans = []
        for key, items in groups.items():
            # Plain supplier lines = one survey named after the project; S-lines = one survey per label.
            name = items[0]["label"] if key[0] == "S" else proj["projectName"]
            survey_plans.append({"name": name, "status": _rollup([i["status"] for i in items]),
                                 "suppliers": items, "existingId": None})

        existing = db[COL_OPS_PROJECTS].find_one({"projectNumber": pn})
        pid = str(existing["_id"]) if existing else None
        for sp in survey_plans:
            if pid:
                found = db[COL_OPS_SURVEYS].find_one({"projectId": pid, "surveyName": sp["name"]})
                sp["existingId"] = str(found["_id"]) if found else None

        plan.append({
            "projectNumber": pn, "projectName": proj["projectName"], "clientName": proj["clientName"],
            "lineNo": proj["lineNo"], "status": _rollup([i["status"] for i in ok]),
            "existingId": pid, "surveys": survey_plans, "attachedSuppliers": attached,
            "noSupplier": proj["noSupplier"] and not proj["suppliers"],
        })
    return plan


def summarize(plan: List[Dict[str, Any]]) -> Dict[str, int]:
    c = {"projectsToCreate": 0, "projectsExisting": 0, "noSupplierProjectsToCreate": 0,
         "surveysToCreate": 0, "surveysExisting": 0, "suppliersToCreate": 0,
         "suppliersAlreadyAttached": 0, "legacyDocsMatched": 0}
    for p in plan:
        if p["existingId"]:
            c["projectsExisting"] += 1
        else:
            c["projectsToCreate"] += 1
            if p["noSupplier"]:
                c["noSupplierProjectsToCreate"] += 1
        c["suppliersAlreadyAttached"] += p["attachedSuppliers"]
        c["legacyDocsMatched"] += p["attachedSuppliers"]
        for sp in p["surveys"]:
            if sp["existingId"]:
                c["surveysExisting"] += 1
            else:
                c["surveysToCreate"] += 1
            c["suppliersToCreate"] += len(sp["suppliers"])
            c["legacyDocsMatched"] += len(sp["suppliers"])
    return c


# ============================================================ backfill artifacts

BACKFILL_PROJECT_Q = {"backfilledFromSurveyId": {"$exists": True, "$ne": None}}
BACKFILL_LINK_Q = {"source": "backfill"}


def _backfill_targets(db) -> Dict[str, Any]:
    projects = list(db[COL_OPS_PROJECTS].find(BACKFILL_PROJECT_Q))
    links = list(db[COL_LINKS].find(BACKFILL_LINK_Q))
    pids = [str(p["_id"]) for p in projects]
    orphans = len(list(db[COL_OPS_SURVEYS].find({"projectId": {"$in": pids}}))) if pids else 0
    return {"opsProjects": len(projects), "opsSurveyLinks": len(links),
            "surveysUnderBackfillProjects": orphans}


def delete_backfill(db) -> Dict[str, int]:
    removed = {"opsProjects": 0, "opsSurveyLinks": 0}
    for doc in list(db[COL_OPS_PROJECTS].find(BACKFILL_PROJECT_Q)):
        db[COL_OPS_PROJECTS].delete_one({"_id": doc["_id"]})
        removed["opsProjects"] += 1
    for doc in list(db[COL_LINKS].find(BACKFILL_LINK_Q)):
        db[COL_LINKS].delete_one({"_id": doc["_id"]})
        removed["opsSurveyLinks"] += 1
    return removed


# ============================================================ apply helpers

def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def backup_collections(db, backup_dir: str) -> Dict[str, Dict[str, Any]]:
    """Raises on any failure; the caller must not write when this raises."""
    os.makedirs(backup_dir, exist_ok=True)
    files: Dict[str, Dict[str, Any]] = {}
    for name in BACKUP_COLLECTIONS:
        docs = list(db[name].find({}))
        path = os.path.join(backup_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(docs, fh, default=_json_default, ensure_ascii=False)
        with open(path, encoding="utf-8") as fh:
            if len(json.load(fh)) != len(docs):
                raise RuntimeError(f"backup of {name} did not verify")
        files[name] = {"path": path, "count": len(docs)}
    return files


def ensure_indexes(db) -> Dict[str, str]:
    specs = [
        (COL_OPS_PROJECTS, "projectNumber", {"unique": True, "name": "ux_ops_projects_number"}),
        (COL_OPS_SURVEYS, "surveyNumber", {"unique": True, "name": "ux_ops_surveys_number"}),
        (COL_SUPPLIERS, [("surveyId", 1), ("legacyProjectId", 1)],
         {"unique": True, "partialFilterExpression": {"removed": False},
          "name": "ux_survey_suppliers_survey_legacy"}),
    ]
    results: Dict[str, str] = {}
    for col, keys, kw in specs:
        coll = db[col]
        if not hasattr(coll, "create_index"):
            results[col] = "skipped (collection has no create_index)"
            continue
        try:
            coll.create_index(keys, **kw)
            results[col] = "ok"
        except Exception as exc:  # e.g. existing duplicates block a unique index
            logger.warning("index on %s failed: %s", col, exc)
            results[col] = f"failed: {exc}"
    return results


def _next_survey_number(db) -> str:
    """Atomic $inc on counters {_id: 'ops_survey_number'}; first issued value 100001."""
    ctr = db[COL_COUNTERS]
    ctr.update_one({"_id": SURVEY_SEQ_ID}, {"$setOnInsert": {"seq": SURVEY_SEQ_START}}, upsert=True)
    if hasattr(ctr, "find_one_and_update"):
        from pymongo import ReturnDocument
        doc = ctr.find_one_and_update({"_id": SURVEY_SEQ_ID}, {"$inc": {"seq": 1}},
                                      return_document=ReturnDocument.AFTER)
        value = doc["seq"]
    else:
        ctr.update_one({"_id": SURVEY_SEQ_ID}, {"$inc": {"seq": 1}})
        value = ctr.find_one({"_id": SURVEY_SEQ_ID})["seq"]
    return str(value)


def write_plan(db, plan: List[Dict[str, Any]]) -> Dict[str, int]:
    now = _now()
    written = {"projects": 0, "surveys": 0, "suppliers": 0}
    for p in plan:
        pid = p["existingId"]
        if pid is None:
            res = db[COL_OPS_PROJECTS].insert_one({
                "projectName": p["projectName"], "projectNumber": p["projectNumber"],
                "clientName": p["clientName"], "managerId": "unassigned", "managerName": "Unassigned",
                "fieldworkDatetime": None, "timezone": TIMEZONE, "status": p["status"],
                "favoriteBy": [], "is_deleted": False, "source": "import",
                "createdAt": now, "updatedAt": now,
            })
            pid = str(res.inserted_id)
            db[COL_CHANGE_LOG].insert_one({
                "ts": now, "userId": IMPORT_USER, "projectId": pid, "surveyId": None,
                "action": "project.import", "field": "projectNumber", "old": None,
                "new": p["projectNumber"], "source": "import",
            })
            written["projects"] += 1
        for sp in p["surveys"]:
            sid = sp["existingId"]
            if sid is None:
                res = db[COL_OPS_SURVEYS].insert_one({
                    "projectId": pid, "surveyName": sp["name"],
                    "surveyNumber": _next_survey_number(db), "status": sp["status"],
                    "surveyUrl": None, "targetN": None, "loi": None, "ir": None,
                    "countryCode": None, "languageCode": None, "devices": {},
                    "piiEnabled": False, "outOfFieldAt": None, "timezone": None,
                    "createdAt": now, "updatedAt": now, "is_deleted": False, "source": "import",
                })
                sid = str(res.inserted_id)
                written["surveys"] += 1
            for sup in sp["suppliers"]:
                db[COL_SUPPLIERS].insert_one({
                    "surveyId": sid, "legacyProjectId": sup["legacyProjectId"],
                    "surveyNo": sup["surveyNo"], "vendorId": sup["vendorId"],
                    "vendorName": sup["vendorName"], "buyPrice": None, "currency": "INR",
                    "removed": False, "status": sup["status"], "createdAt": now,
                })
                written["suppliers"] += 1
    return written


# ============================================================ orchestration

def run(db, text: str, *, apply: bool, report_path: str, backup_dir: Optional[str] = None) -> Dict[str, Any]:
    parsed, problems = parse_segregation(text)
    report: Dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "generatedAt": datetime.now(IST).isoformat(timespec="seconds"),
        "parsedProjects": len(parsed),
    }
    if not apply:
        plan = build_plan(db, parsed, problems)
        report["counts"] = summarize(plan)
        report["backfillToDelete"] = _backfill_targets(db)
    else:
        if not backup_dir:
            raise ValueError("--apply needs a backup directory")
        report["backup"] = backup_collections(db, backup_dir)  # raises: nothing written
        report["backupDir"] = backup_dir
        report["backfillDeleted"] = delete_backfill(db)
        report["indexes"] = ensure_indexes(db)
        plan = build_plan(db, parsed, problems)
        report["counts"] = summarize(plan)
        report["written"] = write_plan(db, plan)
    report["problems"] = problems
    report["problemCount"] = len(problems)
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=_json_default, ensure_ascii=False)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Import the approved Project > Survey > Supplier segregation.")
    ap.add_argument("--file", required=True, help="segregation paste (UTF-8)")
    ap.add_argument("--apply", action="store_true", help="write to the database (default: dry run)")
    ap.add_argument("--report", help="JSON report path (default: next to the input file)")
    ap.add_argument("--backup-dir", help="backup folder for --apply (default: next to the input file)")
    args = ap.parse_args(argv)

    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(os.path.abspath(args.file))[0]
    report_path = args.report or f"{base}_report_{stamp}.json"
    backup_dir = args.backup_dir or os.path.join(os.path.dirname(os.path.abspath(args.file)),
                                                 f"ops_import_backup_{stamp}")
    with open(args.file, encoding="utf-8-sig") as fh:
        text = fh.read()

    from database import get_email_automation_db  # same getter as routers/ops_surveys._db()
    db = get_email_automation_db()
    try:
        report = run(db, text, apply=args.apply, report_path=report_path, backup_dir=backup_dir)
    except Exception as exc:
        print(f"ABORTED, nothing imported: {exc}")
        return 2

    c = report["counts"]
    print(f"mode={report['mode']} parsedProjects={report['parsedProjects']} problems={report['problemCount']}")
    for k, v in c.items():
        print(f"  {k}: {v}")
    print(f"  backfill: {report.get('backfillDeleted') or report.get('backfillToDelete')}")
    if args.apply:
        print(f"  written: {report['written']}  backup: {backup_dir}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
