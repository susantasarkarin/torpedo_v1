"""
Ops research layer: cleaning requests (tracking only), client reconciliations,
project report and daily trend. Built on routers/ops_surveys.py helpers; metric
definitions are not duplicated here.

Reads never modify traffic rows. Every mutation is written to ops_change_log.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from rbac.decorators import require_permission
from rbac.permissions import Permissions
from routers.ops_surveys import (
    COL_VENDORS,
    _TRACK_PROJECTION,
    _TS,
    _active_suppliers,
    _agg,
    _bad,
    _can_see_pricing,
    _col,
    _ensure_indexes,
    _get_project,
    _get_survey,
    _group_by_pid,
    _iso,
    _link_for_survey,
    _log,
    _not_found,
    _now,
    _oid,
    _project_view,
    _survey_row,
    _surveys_under,
    _traffic_find,
    _vid_variants,
    _window,
)
from session_state import verify_session

router = APIRouter(prefix="/api/ops", tags=["Ops Research"])

COL_CLEANING = "ops_cleaning_requests"
COL_RECON = "ops_reconciliations"

CLEANING_STATUSES = ("submitted", "in_progress", "completed", "cancelled")
MAX_RECON_IDS = 100_000
UNMATCHED_CAP = 5000
NOTES_LIMIT = 2000
IST = ZoneInfo("Asia/Kolkata")

_RECON_PROJECTION = {"respondentId": 1, "vendorId": 1, "status": 1, "params.pid": 1}


# ============================================================ helpers

def _is_complete(r: Dict[str, Any]) -> bool:
    return _TS._normalize_status(r.get("status", "")) == "Complete"


def _rid(r: Dict[str, Any]) -> str:
    return str(r.get("respondentId") or "").strip()


def _money(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _clean_ids(values: Optional[List[Any]], field: str, required: bool) -> List[str]:
    """Trim, drop empties, de-duplicate (order kept). Exact compare, same as traffic respondentId."""
    out: List[str] = []
    seen: Set[str] = set()
    for v in values or []:
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    if required and not out:
        _bad(f"{field} must be a non-empty list")
    return out


def _survey_of_project(project_id: str, survey_id: str) -> Dict[str, Any]:
    link = _link_for_survey(str(survey_id))
    if not link or str(link.get("parentProjectId")) != str(project_id):
        _bad(f"survey {survey_id} does not belong to this project")
    return _get_survey(str(survey_id))


def _vendor_names(vids: List[str]) -> Dict[str, Any]:
    vids = [v for v in vids if v not in (None, "")]
    if not vids:
        return {}
    names: Dict[str, Any] = {}
    for v in _col(COL_VENDORS).find({"vid": {"$in": _vid_variants(vids)}}):
        names[str(v.get("vid"))] = v.get("vendorName")
    return names


def _ist_day(value: Any) -> Optional[str]:
    dt = _TS._safe_parse_datetime(value)  # naive UTC or None
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def _sort_newest(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(docs, key=lambda d: d.get("createdAt") or datetime.min, reverse=True)


# ============================================================ cleaning requests

class CleaningCreate(BaseModel):
    surveyIds: List[str]
    notes: Optional[str] = None


class CleaningStatus(BaseModel):
    status: str
    note: Optional[str] = None


def _cleaning_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "projectId": doc.get("projectId"),
        "surveyIds": doc.get("surveyIds", []),
        "notes": doc.get("notes"),
        "requestedBy": doc.get("requestedBy"),
        "status": doc.get("status"),
        "history": [{**h, "ts": _iso(h.get("ts"))} for h in doc.get("history", [])],
        "createdAt": _iso(doc.get("createdAt")),
    }


def _get_cleaning(rid: str) -> Dict[str, Any]:
    doc = _col(COL_CLEANING).find_one({"_id": _oid(rid, "Cleaning request")})
    if not doc:
        _not_found("Cleaning request not found")
    return doc


@router.post("/projects/{project_id}/cleaning-requests")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def create_cleaning_request(project_id: str, request: Request, body: CleaningCreate,
                            user: str = Depends(verify_session)):
    _ensure_indexes()
    project = _get_project(project_id)
    pid = str(project["_id"])
    sids = _clean_ids(body.surveyIds, "surveyIds", required=True)
    for sid in sids:
        _survey_of_project(pid, sid)
    notes = (body.notes or "").strip()
    if len(notes) > NOTES_LIMIT:
        _bad("notes is too long")
    now = _now()
    doc = {"projectId": pid, "surveyIds": sids, "notes": notes or None, "requestedBy": user,
           "status": "submitted",
           "history": [{"ts": now, "user": user, "status": "submitted", "note": notes or None}],
           "createdAt": now}
    rid = str(_col(COL_CLEANING).insert_one(doc).inserted_id)
    _log(user=user, action="cleaning.create", project_id=pid, new=sids, extra={"requestId": rid})
    return {"request": _cleaning_view(_get_cleaning(rid))}


@router.get("/projects/{project_id}/cleaning-requests")
def list_cleaning_requests(project_id: str, user: str = Depends(verify_session)):
    project = _get_project(project_id)
    docs = _sort_newest(list(_col(COL_CLEANING).find({"projectId": str(project["_id"])})))
    return {"items": [_cleaning_view(d) for d in docs]}


@router.post("/cleaning-requests/{rid}/status")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def set_cleaning_status(rid: str, request: Request, body: CleaningStatus,
                        user: str = Depends(verify_session)):
    _ensure_indexes()
    if body.status not in CLEANING_STATUSES:
        _bad(f"status must be one of {', '.join(CLEANING_STATUSES)}")
    doc = _get_cleaning(rid)
    note = (body.note or "").strip() or None
    entry = {"ts": _now(), "user": user, "status": body.status, "note": note}
    _col(COL_CLEANING).update_one({"_id": doc["_id"]},
                                  {"$set": {"status": body.status}, "$push": {"history": entry}})
    _log(user=user, action="cleaning.status", project_id=doc.get("projectId"),
         field="status", old=doc.get("status"), new=body.status, extra={"requestId": rid})
    return {"request": _cleaning_view(_get_cleaning(rid))}


# ============================================================ reconciliations

class ReconciliationCreate(BaseModel):
    surveyId: str
    acceptedIds: List[str]
    rejectedIds: Optional[List[str]] = None
    note: Optional[str] = None


def _reconcile(survey: Dict[str, Any], accepted: List[str], rejected: List[str]) -> Dict[str, Any]:
    """Read-only comparison of the client file against our traffic rows for this survey."""
    no = survey.get("surveyNo")
    recs = _traffic_find([no], projection=_RECON_PROJECTION) if no else []
    acc, rej = set(accepted), set(rejected)

    by_rid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        if _rid(r):
            by_rid[_rid(r)].append(r)
    completes = [r for r in recs if _is_complete(r)]

    matched = not_complete = not_found = 0
    unmatched: List[str] = []
    for aid in accepted:
        rows = by_rid.get(aid, [])
        if any(_is_complete(r) for r in rows):
            matched += 1
        else:
            if rows:
                not_complete += 1
            else:
                not_found += 1
            unmatched.append(aid)

    per: Dict[str, Dict[str, int]] = {}
    for r in recs:
        per.setdefault(str(r.get("vendorId")), {"ourCompletes": 0, "reconciledCompletes": 0, "rejected": 0})
    for r in completes:
        s = per[str(r.get("vendorId"))]
        s["ourCompletes"] += 1
        if _rid(r) in acc:
            s["reconciledCompletes"] += 1
        if _rid(r) in rej:
            s["rejected"] += 1
    names = _vendor_names(list(per))
    by_supplier = [{"vendorId": v, "vendorName": names.get(v), **per[v]} for v in sorted(per)]

    reconciled = sum(1 for r in completes if _rid(r) in acc)
    counts = {
        "ourCompletes": len(completes),
        "accepted": len(acc),
        "rejected": len(rej),
        "acceptedMatched": matched,            # accepted ids with at least one Complete row
        "acceptedNotFound": not_found,         # accepted ids absent from traffic
        "acceptedNotComplete": not_complete,   # accepted ids present in traffic, no Complete row
        "completesNotInClientFile": len(completes) - reconciled,
        "reconciledCompletes": reconciled,
    }
    return {"counts": counts, "bySupplier": by_supplier, "unmatched": unmatched}


def _recon_view(doc: Dict[str, Any], full: bool) -> Dict[str, Any]:
    out = {
        "id": str(doc["_id"]),
        "projectId": doc.get("projectId"),
        "surveyId": doc.get("surveyId"),
        "surveyNo": doc.get("surveyNo"),
        "createdBy": doc.get("createdBy"),
        "createdAt": _iso(doc.get("createdAt")),
        "note": doc.get("note"),
        "counts": doc.get("counts"),
        "bySupplier": doc.get("bySupplier", []),
    }
    if full:
        out["unmatchedIds"] = doc.get("unmatchedIds", [])
        out["unmatchedIdsTruncated"] = bool(doc.get("unmatchedIdsTruncated"))
        out["rejectedIds"] = doc.get("rejectedIds", [])
    return out


def _get_recon(rid: str) -> Dict[str, Any]:
    doc = _col(COL_RECON).find_one({"_id": _oid(rid, "Reconciliation")})
    if not doc:
        _not_found("Reconciliation not found")
    return doc


@router.post("/projects/{project_id}/reconciliations")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def create_reconciliation(project_id: str, request: Request, body: ReconciliationCreate,
                          user: str = Depends(verify_session)):
    _ensure_indexes()
    if len(body.acceptedIds) + len(body.rejectedIds or []) > MAX_RECON_IDS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_RECON_IDS} ids per request")
    project = _get_project(project_id)
    pid = str(project["_id"])
    survey = _survey_of_project(pid, body.surveyId)
    accepted = _clean_ids(body.acceptedIds, "acceptedIds", required=False)
    rejected = _clean_ids(body.rejectedIds, "rejectedIds", required=False)
    if set(accepted) & set(rejected):
        _bad("an id cannot be both accepted and rejected")
    note = (body.note or "").strip()
    if len(note) > NOTES_LIMIT:
        _bad("note is too long")

    result = _reconcile(survey, accepted, rejected)
    unmatched = result["unmatched"]
    doc = {
        "projectId": pid, "surveyId": str(survey["_id"]), "surveyNo": survey.get("surveyNo"),
        "createdBy": user, "createdAt": _now(), "note": note or None,
        "counts": result["counts"], "bySupplier": result["bySupplier"],
        "unmatchedIds": unmatched[:UNMATCHED_CAP],
        "unmatchedIdsTruncated": len(unmatched) > UNMATCHED_CAP,
        "rejectedIds": rejected,
    }
    rid = str(_col(COL_RECON).insert_one(doc).inserted_id)
    _log(user=user, action="reconciliation.create", project_id=pid, survey_id=str(survey["_id"]),
         new=rid, extra={"reconciliationId": rid, "counts": result["counts"]})
    return {"reconciliation": _recon_view(_get_recon(rid), full=True)}


@router.get("/projects/{project_id}/reconciliations")
def list_reconciliations(project_id: str, user: str = Depends(verify_session),
                         surveyId: Optional[str] = None):
    project = _get_project(project_id)
    q: Dict[str, Any] = {"projectId": str(project["_id"])}
    if surveyId:
        q["surveyId"] = str(surveyId)
    docs = _sort_newest(list(_col(COL_RECON).find(q)))
    return {"items": [_recon_view(d, full=False) for d in docs]}


@router.get("/reconciliations/{rid}")
def get_reconciliation(rid: str, user: str = Depends(verify_session)):
    return {"reconciliation": _recon_view(_get_recon(rid), full=True)}


# ============================================================ project report

@router.get("/projects/{project_id}/report")
def project_report(project_id: str, user: str = Depends(verify_session),
                   window: Optional[str] = None):
    _ensure_indexes()
    cutoff = _window(window)
    project = _get_project(project_id)
    pid = str(project["_id"])
    pricing = _can_see_pricing(user)
    surveys = sorted(_surveys_under([pid]).get(pid, []),
                     key=lambda s: str(s.get("projectName") or "").lower())

    # One traffic read; each surveyNo's rows are counted once (distinct surveyNo).
    nos: List[str] = []
    for s in surveys:
        no = str(s.get("surveyNo") or "")
        if no and no not in nos:
            nos.append(no)
    grouped = _group_by_pid(_traffic_find(nos, projection=_TRACK_PROJECTION))
    sid_of_no = {str(s.get("surveyNo")): str(s["_id"]) for s in surveys if s.get("surveyNo")}

    survey_rows = []
    for s in surveys:
        no = str(s.get("surveyNo") or "")
        m = _agg(grouped.get(no, []) if no else [], cutoff)
        row = _survey_row(s, m)
        row["target"] = int(s.get("totalCompletesRequired") or 0)
        survey_rows.append(row)

    all_records = [r for no in nos for r in grouped.get(no, [])]
    t = _agg(all_records, cutoff)
    totals = {
        "entrants": t["entrants"], "terms": t["terms"], "oqs": t["oqs"], "completes": t["completes"],
        "ir": t["ir"], "conversion": t["conversion"], "loi": t["loi"],
        "target": sum(r["target"] for r in survey_rows),
    }

    # Supplier aggregation across the project's surveys.
    by_vendor: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    vendor_sids: Dict[str, Set[str]] = defaultdict(set)
    for no in nos:
        for r in grouped.get(no, []):
            v = str(r.get("vendorId"))
            by_vendor[v].append(r)
            vendor_sids[v].add(sid_of_no[no])

    expense: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    name_hint: Dict[str, Any] = {}
    for s in surveys:
        sid = str(s["_id"])
        no = str(s.get("surveyNo") or "")
        survey_recs = grouped.get(no, []) if no else []
        for sup in _active_suppliers(sid):
            v = str(sup.get("vendorId"))
            vendor_sids[v].add(sid)
            name_hint.setdefault(v, sup.get("vendorName"))
            if sup.get("buyPrice") in (None, ""):
                continue
            comp = sum(1 for r in survey_recs if str(r.get("vendorId")) == v and _is_complete(r))
            cur = str(sup.get("currency") or "INR")
            expense[v][cur] += Decimal(comp) * Decimal(str(sup["buyPrice"]))

    vids = sorted(set(by_vendor) | set(vendor_sids))
    names = _vendor_names(vids)
    suppliers = []
    for v in vids:
        m = _agg(by_vendor.get(v, []), cutoff)
        row = {
            "vendorId": v,
            "vendorName": names.get(v) or name_hint.get(v),
            "surveys": len(vendor_sids[v]),
            "entrants": m["entrants"], "terms": m["terms"], "oqs": m["oqs"],
            "completes": m["completes"], "ir": m["ir"], "conversion": m["conversion"], "loi": m["loi"],
        }
        if pricing:
            row["expenseByCurrency"] = {c: _money(a) for c, a in sorted(expense.get(v, {}).items())}
        suppliers.append(row)

    latest: Dict[str, Dict[str, Any]] = {}
    for d in sorted(_col(COL_RECON).find({"projectId": pid}),
                    key=lambda d: d.get("createdAt") or datetime.min):
        latest[str(d.get("surveyId"))] = d  # ascending: newest wins
    latest_out = {sid: {"id": str(d["_id"]), "createdAt": _iso(d.get("createdAt")), "counts": d.get("counts")}
                  for sid, d in latest.items()}

    out: Dict[str, Any] = {
        "project": _project_view(project, user),
        "totals": totals,
        "surveys": survey_rows,
        "suppliers": suppliers,
        "latestReconciliation": latest_out,
        "meta": {"window": window or "p24h", "pricing": pricing},
    }
    if pricing:
        project_expense: Dict[str, Decimal] = defaultdict(Decimal)
        for v in expense:
            for c, a in expense[v].items():
                project_expense[c] += a
        out["expenseByCurrency"] = {c: _money(a) for c, a in sorted(project_expense.items())}
    return out


# ============================================================ trend

@router.get("/surveys/{survey_id}/trend")
def survey_trend(survey_id: str, user: str = Depends(verify_session),
                 days: int = Query(14, ge=1, le=90)):
    survey = _get_survey(survey_id)
    no = str(survey.get("surveyNo") or "")
    recs = _traffic_find([no], projection=_TRACK_PROJECTION) if no else []

    today = datetime.now(IST).date()
    day_keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    idx = {k: i for i, k in enumerate(day_keys)}

    entrants: Dict[str, List[int]] = {}
    completes: Dict[str, List[int]] = {}
    for r in recs:
        v = str(r.get("vendorId"))
        d = _ist_day(r.get("createdAt"))
        if d in idx:
            entrants.setdefault(v, [0] * days)[idx[d]] += 1
        if _is_complete(r):
            d = _ist_day(r.get("completedAt"))
            if d in idx:
                completes.setdefault(v, [0] * days)[idx[d]] += 1

    vids = sorted(set(entrants) | set(completes))
    names = _vendor_names(vids)
    series = [{"vendorId": v, "vendorName": names.get(v),
               "entrants": entrants.get(v, [0] * days), "completes": completes.get(v, [0] * days)}
              for v in vids]
    total_e = [0] * days
    total_c = [0] * days
    for s in series:
        for i in range(days):
            total_e[i] += s["entrants"][i]
            total_c[i] += s["completes"][i]
    return {"days": day_keys, "series": series,
            "total": {"entrants": total_e, "completes": total_c}}
