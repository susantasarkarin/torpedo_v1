"""
Ops: Project -> Survey -> Supplier layer.

Parent "ops_projects" groups existing survey docs (email_automation.projects)
via "ops_survey_links". A survey IS the existing projects doc; extra survey
fields are written onto it with the legacy field names. Suppliers are rows in
"survey_suppliers" that reference email_automation.vendors by vid.

Metric definitions are NOT re-implemented here: status normalisation and
datetime parsing come from TrafficService (app/services/traffic_service.py).
Only the stored counts/grouping are local.
"""

import csv
import io
import json
import logging
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.services.traffic_service import TrafficService
from database import get_email_automation_db, get_traffic_db
from rbac.decorators import require_permission
from rbac.permissions import Permissions
from session_state import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops", tags=["Ops Surveys"])

# Collections (all in email_automation unless noted)
COL_PROJECTS = "projects"            # existing: one doc per survey
COL_OPS_PROJECTS = "ops_projects"
COL_LINKS = "ops_survey_links"
COL_SUPPLIERS = "survey_suppliers"
COL_CHANGE_LOG = "ops_change_log"
COL_VENDORS = "vendors"
COL_USERS = "users"
COL_TRAFFIC = "url_parameters"       # in traffic_flow_db

PROJECT_STATUSES = ("live", "paused", "completed")
SURVEY_STATUSES = ("live", "paused", "completed", "draft", "cancelled", "auto_paused", "scheduled")
SUPPLIER_STATUSES = ("live", "paused", "completed")
DEAD_VENDOR_STATUSES = ("deleted", "inactive", "archived")
# Metrics whose definition is not yet confirmed. Empty: sqTerms is defined below.
UNVERIFIED_METRICS: List[str] = []
SQ_TERMS_NOTE = "Screened out by our qualification before reaching the client survey; counted separately from Terms."
# notRoutedReason values written with status NOT_ROUTED (routers/traffic.py):
#   prescreen_fail  -> traffic.py:3455, fails our project qualification (screener)
#   country         -> traffic.py:3455, fails our country check (screener)
#   (empty)         -> traffic.py:3560 falls back to prescreen_fail (screener)
#   router_link     -> traffic.py:3465/3560, no eligible survey in the country (capacity, NOT sqTerms)
#   panel_first     -> never written as NOT_ROUTED (traffic.py:3557)
# Only the screener reasons feed sqTerms. Their rows carry params.pid == surveyNo
# (ADHOC flow, params.api "false"), so they are attributable per survey.
SCREENER_NOT_ROUTED_REASONS = ("prescreen_fail", "country")
WINDOWS = {"p24h": timedelta(hours=24), "p14d": timedelta(days=14)}

# Pure reuse of the traffic_service definitions (no collections bound).
_TS = TrafficService.__new__(TrafficService)
_TRACK_PROJECTION = {"status": 1, "createdAt": 1, "completedAt": 1, "params.pid": 1, "vendorId": 1,
                     "notRoutedReason": 1}

_INDEXES_READY = False


# ============================================================ infrastructure

def _db():
    return get_email_automation_db()


def _col(name: str):
    return _db()[name]


def _traffic_col():
    return get_traffic_db()[COL_TRAFFIC]


def _ensure_indexes() -> None:
    """Idempotent, created lazily on first use (never at import)."""
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        db = _db()
        db[COL_OPS_PROJECTS].create_index("projectNumber", unique=True, name="ux_ops_projects_number")
        db[COL_LINKS].create_index("surveyId", unique=True, name="ux_ops_links_survey")
        db[COL_LINKS].create_index("parentProjectId", name="ix_ops_links_parent")
        db[COL_SUPPLIERS].create_index([("surveyId", 1), ("vendorId", 1)], unique=True,
                                       name="ux_survey_suppliers_survey_vendor")
        db[COL_CHANGE_LOG].create_index([("projectId", 1), ("ts", -1)], name="ix_log_project")
        db[COL_CHANGE_LOG].create_index([("surveyId", 1), ("ts", -1)], name="ix_log_survey")
        _INDEXES_READY = True
    except Exception as exc:  # index creation must never break a request
        logger.warning("ops index ensure skipped: %s", exc)


def _now() -> datetime:
    return datetime.utcnow()


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _bad(msg: str):
    """422 with a plain-string detail. Pydantic body errors keep FastAPI's list-shaped
    detail (no global handler change); the UI flattens those client-side, and
    _validation_message() gives the same one-line form for anything server-side."""
    raise HTTPException(status_code=422, detail=msg)


def _validation_message(errors: List[Dict[str, Any]]) -> str:
    """Pydantic error list -> 'field: reason; field: reason'."""
    parts = []
    for e in errors:
        loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
        parts.append(f"{'.'.join(loc) or 'request'}: {e.get('msg', 'invalid')}")
    return "; ".join(parts)


def _not_found(msg: str):
    raise HTTPException(status_code=404, detail=msg)


def _oid(value: str, what: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except Exception:
        _not_found(f"{what} not found")


def _is_admin(username: str) -> bool:
    doc = _col(COL_USERS).find_one({"username": username}) or {}
    return "admin" in (doc.get("roles") or [])


def _require_admin(username: str, what: str) -> None:
    if not _is_admin(username):
        raise HTTPException(status_code=403, detail=f"{what} requires admin")


def _is_finance(username: str) -> bool:
    doc = _col(COL_USERS).find_one({"username": username}) or {}
    return "finance" in (doc.get("roles") or [])


def _can_see_pricing(username: str) -> bool:
    """Pricing (buyPrice, currency, expense) is visible/editable to admin and finance.
    PII is NOT covered by this: it stays admin-only (_is_admin)."""
    return _is_admin(username) or _is_finance(username)


def _require_pricing(username: str, what: str) -> None:
    if not _can_see_pricing(username):
        raise HTTPException(status_code=403, detail=f"{what} requires admin or finance")


_PRICING_KEYS = ("buyPrice", "currency", "expense", "expenseBasis", "expenseByCurrency")


def _strip_pricing(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in _PRICING_KEYS} for r in rows]


def _log(*, user: str, action: str, project_id: Optional[str] = None,
         survey_id: Optional[str] = None, field: Optional[str] = None,
         old: Any = None, new: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
    doc = {
        "ts": _now(), "userId": user, "projectId": project_id, "surveyId": survey_id,
        "action": action, "field": field, "old": _loggable(old), "new": _loggable(new),
    }
    if extra:
        doc.update(extra)
    _col(COL_CHANGE_LOG).insert_one(doc)


def _loggable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.loads(json.dumps(v, default=str))
    return v


# ============================================================ validation

_CC = re.compile(r"^[A-Za-z]{2}$")
_LANG = re.compile(r"^[A-Za-z]{2}(-[A-Za-z0-9]{2,8})?$")
_CUR = re.compile(r"^[A-Za-z]{3}$")


def _to_number(v: Any, field: str) -> float:
    if isinstance(v, bool):
        _bad(f"{field} must be a number")
    try:
        return float(v)
    except (TypeError, ValueError):
        _bad(f"{field} must be a number")


def _to_int(v: Any, field: str) -> int:
    n = _to_number(v, field)
    if n != int(n):
        _bad(f"{field} must be a whole number")
    return int(n)


def _check_url(v: Any, field: str) -> str:
    s = str(v or "").strip()
    p = urlparse(s)
    if p.scheme not in ("http", "https") or not p.netloc:
        _bad(f"{field} must be an http(s) URL")
    return s


def _check_tz(v: Any, field: str = "timezone") -> str:
    s = str(v or "").strip()
    try:
        ZoneInfo(s)
    except Exception:
        _bad(f"{field} is not a known IANA timezone")
    return s


def _check_dt(v: Any, field: str) -> str:
    s = str(v or "").strip()
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        _bad(f"{field} must be an ISO datetime")
    return s


def _check_name(v: Any, field: str, limit: int = 200) -> str:
    s = str(v or "").strip()
    if not s:
        _bad(f"{field} is required")
    if len(s) > limit:
        _bad(f"{field} is too long")
    return s


def _check_price(v: Any) -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        _bad("buyPrice must be a number")
    if not d.is_finite() or d < 0:
        _bad("buyPrice must be >= 0")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _check_currency(v: Any) -> str:
    s = str(v or "").strip().upper()
    if not _CUR.match(s):
        _bad("currency must be a 3-letter code")
    return s


_SURVEY_FIELDS = {
    # input key: (stored field on the projects doc, required on create)
    "surveyName": ("projectName", True),
    "surveyUrl": ("liveLink", True),
    "targetN": ("totalCompletesRequired", True),
    "loi": ("loi", True),
    "ir": ("clientIR", True),
    "countryCode": ("countryCode", True),
    "languageCode": ("languageCode", True),
    "timezone": ("timezone", False),
    "devices": ("devices", False),
    "piiEnabled": ("piiEnabled", False),
    "outOfFieldAt": ("outOfFieldAt", False),
}
_STORED_TO_INPUT = {v[0]: k for k, v in _SURVEY_FIELDS.items()}


def _clean_survey_value(key: str, v: Any) -> Any:
    if key == "surveyName":
        return _check_name(v, "surveyName")
    if key == "surveyUrl":
        return _check_url(v, "surveyUrl")
    if key == "targetN":
        n = _to_int(v, "targetN")
        if n <= 0:
            _bad("targetN must be > 0")
        return n
    if key == "loi":
        n = _to_number(v, "loi")
        if n <= 0:
            _bad("loi must be > 0")
        return n
    if key == "ir":
        n = _to_number(v, "ir")
        if not 0 <= n <= 100:
            _bad("ir must be between 0 and 100")
        return n
    if key == "countryCode":
        s = str(v or "").strip().upper()
        if not _CC.match(s):
            _bad("countryCode must be a 2-letter code")
        return s
    if key == "languageCode":
        s = str(v or "").strip()
        if not _LANG.match(s):
            _bad("languageCode must look like 'en' or 'en-IN'")
        return s
    if key == "timezone":
        return _check_tz(v)
    if key == "devices":
        if not isinstance(v, dict) or set(v) - {"desktop", "mobile", "tablet"}:
            _bad("devices must be an object with desktop/mobile/tablet booleans")
        return {k: bool(v[k]) for k in v}
    if key == "piiEnabled":
        return bool(v)
    if key == "outOfFieldAt":
        return _check_dt(v, "outOfFieldAt")
    return v


def _clean_survey(data: Dict[str, Any], partial: bool) -> Dict[str, Any]:
    """Returns stored-field -> value. Raises 422 on any invalid input."""
    out: Dict[str, Any] = {}
    for key, (stored, required) in _SURVEY_FIELDS.items():
        if data.get(key) is not None:
            out[stored] = _clean_survey_value(key, data[key])
        elif required and not partial:
            _bad(f"{key} is required")
    return out


def _window(window: Optional[str]) -> datetime:
    """Returns the cutoff (naive UTC) for completesWindow."""
    key = window or "p24h"
    if key not in WINDOWS:
        _bad("window must be p24h or p14d")
    return _now() - WINDOWS[key]


def _survey_status(raw: Any) -> str:
    """Legacy projectStatus -> exposed survey status. Unknown/missing -> draft."""
    key = str(raw or "").strip().lower()
    return {"live": "live", "pause": "paused", "paused": "paused",
            "close": "completed", "completed": "completed"}.get(
        key, key if key in SURVEY_STATUSES else "draft")


# ============================================================ metrics

def _vid_variants(vids) -> List[Any]:
    out: List[Any] = []
    for v in vids:
        s = str(v).strip()
        for cand in (s, int(s) if s.isdigit() else None):
            if cand is not None and cand not in out:
                out.append(cand)
    return out


def _traffic_find(pids, vendor_ids=None, projection=None, pii: bool = False) -> List[Dict[str, Any]]:
    """Traffic rows for survey numbers, same filter as TrafficService project stats
    (params.api == "false", params.pid in pids), optionally per vendor."""
    wanted = [str(p) for p in pids if p not in (None, "")]
    if not wanted:
        return []
    q: Dict[str, Any] = {"params.api": "false", "params.pid": {"$in": wanted}}
    if vendor_ids is not None:
        vids = _vid_variants(vendor_ids)
        if not vids:
            return []
        q["vendorId"] = {"$in": vids}
    return list(_traffic_col().find(q, projection))


def _inflight_minutes() -> int:
    """OPS_INFLIGHT_MINUTES (default 60). A non-final row created more recently
    than this is in-flight; an older one is an abandon. Read per call."""
    try:
        return max(1, int(os.getenv("OPS_INFLIGHT_MINUTES", "60")))
    except ValueError:
        return 60


def _is_defender_term(raw: Any) -> bool:
    """Client security/fraud terminate. Stored as SECURITY_TERMINATED by
    /surveyterminate?type=security (routers/traffic.py, outcome "security").
    SECURITY_TERM (bot check) carries no params.pid, so it only counts if it
    ever gets one. Always a subset of terms (SECURITY_* normalises to Terminate)."""
    return "SECURITY" in str(raw or "").upper()


def _is_screener_out(r: Dict[str, Any]) -> bool:
    """NOT_ROUTED caused by OUR screener (see SCREENER_NOT_ROUTED_REASONS)."""
    return (str(r.get("status") or "").strip().upper() == "NOT_ROUTED"
            and r.get("notRoutedReason") in SCREENER_NOT_ROUTED_REASONS)


def _agg(records: List[Dict[str, Any]], cutoff: Optional[datetime]) -> Dict[str, Any]:
    """Counts for one set of traffic rows.

    terms         = every row TrafficService normalises to Terminate.
    defenderTerms = subset of terms with a SECURITY status (client security terminate).
    sqTerms       = screener NOT_ROUTED rows (_is_screener_out). Separate from terms;
                    these rows are never counted as inFlights or abandons.
    inFlights     = non-final rows (normaliser "Incomplete") created within OPS_INFLIGHT_MINUTES.
    abandons      = non-final rows created earlier than that, or with no parseable createdAt.
    """
    live_after = _now() - timedelta(minutes=_inflight_minutes())
    entrants = terms = oqs = completes = in_window = sq_terms = 0
    defender = inflight = abandons = 0
    loi: List[float] = []
    for r in records:
        entrants += 1
        if _is_screener_out(r):
            sq_terms += 1
            continue
        norm = _TS._normalize_status(r.get("status", ""))
        if norm == "Complete":
            completes += 1
            created = _TS._safe_parse_datetime(r.get("createdAt"))
            done = _TS._safe_parse_datetime(r.get("completedAt"))
            if cutoff is not None and done is not None and done >= cutoff:
                in_window += 1
            if created and done:
                secs = (done - created).total_seconds()
                if secs > 0:
                    loi.append(secs / 60.0)
        elif norm == "Terminate":
            terms += 1
            if _is_defender_term(r.get("status")):
                defender += 1
        elif norm == "Quota Full":
            oqs += 1
        else:  # "Incomplete": the normaliser's default, i.e. every non-final status
            created = _TS._safe_parse_datetime(r.get("createdAt"))
            if created is not None and created >= live_after:
                inflight += 1
            else:
                abandons += 1
    return {
        "entrants": entrants,
        "terms": terms,
        "defenderTerms": defender,
        "sqTerms": sq_terms,
        "oqs": oqs,
        "completes": completes,
        "completesWindow": in_window,
        "ir": round(completes / (completes + terms) * 100, 1) if (completes + terms) else 0.0,
        "conversion": round(completes / entrants * 100, 1) if entrants else 0.0,
        "loi": round(statistics.median(loi), 1) if loi else None,
        "abandons": abandons,
        "inFlights": inflight,
    }


def _group_by_pid(records) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        grouped[str((r.get("params") or {}).get("pid"))].append(r)
    return grouped


def _survey_metrics(surveys: List[Dict[str, Any]], cutoff: datetime) -> Dict[str, Dict[str, Any]]:
    """surveyNo -> metrics. One traffic read for all surveys."""
    nos = [str(s.get("surveyNo")) for s in surveys if s.get("surveyNo")]
    grouped = _group_by_pid(_traffic_find(nos, projection=_TRACK_PROJECTION))
    return {no: _agg(grouped.get(no, []), cutoff) for no in nos}


def _survey_row(survey: Dict[str, Any], m: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(survey["_id"]),
        "surveyName": survey.get("projectName"),
        "surveyNo": survey.get("surveyNo"),
        "status": _survey_status(survey.get("projectStatus")),
        "entrants": m["entrants"],
        "defenderTerms": m["defenderTerms"],
        "terms": m["terms"],
        "oqs": m["oqs"],
        "sqTerms": m["sqTerms"],
        "abandons": m["abandons"],
        "inFlights": m["inFlights"],
        "completes": m["completes"],
        "completesWindow": m["completesWindow"],
        "ir": m["ir"],
        "conversion": m["conversion"],
        "loi": m["loi"],
    }


def _expense(completes: int, buy_price: Any) -> Dict[str, Any]:
    if buy_price in (None, ""):
        return {"expense": None, "expenseBasis": None}
    amount = (Decimal(completes) * Decimal(str(buy_price))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"expense": float(amount), "expenseBasis": "completes*buyPrice"}


# ============================================================ lookups

def _get_project(project_id: str) -> Dict[str, Any]:
    doc = _col(COL_OPS_PROJECTS).find_one({"_id": _oid(project_id, "Project"), "is_deleted": {"$ne": True}})
    if not doc:
        _not_found("Project not found")
    return doc


def _get_survey(survey_id: str) -> Dict[str, Any]:
    doc = _col(COL_PROJECTS).find_one({"_id": _oid(survey_id, "Survey"), "is_deleted": {"$ne": True}})
    if not doc:
        _not_found("Survey not found")
    return doc


def _get_supplier(sid: str) -> Dict[str, Any]:
    doc = _col(COL_SUPPLIERS).find_one({"_id": _oid(sid, "Supplier"), "removed": {"$ne": True}})
    if not doc:
        _not_found("Supplier not found")
    return doc


def _link_for_survey(survey_id: str) -> Optional[Dict[str, Any]]:
    return _col(COL_LINKS).find_one({"surveyId": str(survey_id)})


def _surveys_under(project_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """parent project id -> live survey docs (links resolved, one read each)."""
    links = list(_col(COL_LINKS).find({"parentProjectId": {"$in": project_ids}}))
    by_parent: Dict[str, List[str]] = defaultdict(list)
    for ln in links:
        by_parent[ln["parentProjectId"]].append(ln["surveyId"])
    ids = [ObjectId(s) for s in {sid for v in by_parent.values() for sid in v}]
    docs = {str(d["_id"]): d for d in _col(COL_PROJECTS).find(
        {"_id": {"$in": ids}, "is_deleted": {"$ne": True}})} if ids else {}
    return {pid: [docs[s] for s in sids if s in docs] for pid, sids in by_parent.items()}


def _project_rows(projects: List[Dict[str, Any]], username: str, cutoff: datetime) -> List[Dict[str, Any]]:
    pids = [str(p["_id"]) for p in projects]
    surveys_by_parent = _surveys_under(pids) if pids else {}
    all_surveys = [s for v in surveys_by_parent.values() for s in v]
    # One traffic read; each surveyNo's records counted exactly once.
    grouped = _group_by_pid(_traffic_find(
        [s.get("surveyNo") for s in all_surveys], projection=_TRACK_PROJECTION))
    rows = []
    for p in projects:
        pid = str(p["_id"])
        surveys = surveys_by_parent.get(pid, [])
        nos = {str(s.get("surveyNo")) for s in surveys if s.get("surveyNo")}
        records = [r for no in nos for r in grouped.get(no, [])]
        m = _agg(records, cutoff)
        rows.append({
            "id": pid,
            "projectName": p.get("projectName"),
            "projectNumber": p.get("projectNumber"),
            "managerId": p.get("managerId"),
            "managerName": p.get("managerName"),
            "status": p.get("status"),
            "isFavorite": username in (p.get("favoriteBy") or []),
            "surveyCount": len(surveys),
            "completes": m["completes"],
            "target": sum(int(s.get("totalCompletesRequired") or 0) for s in surveys),
            "ir": m["ir"],
            "conversion": m["conversion"],
            "loi": m["loi"],
        })
    return rows


def _project_view(doc: Dict[str, Any], username: str) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "projectName": doc.get("projectName"),
        "projectNumber": doc.get("projectNumber"),
        "managerId": doc.get("managerId"),
        "managerName": doc.get("managerName"),
        "fieldworkDatetime": doc.get("fieldworkDatetime"),
        "timezone": doc.get("timezone"),
        "status": doc.get("status"),
        "isFavorite": username in (doc.get("favoriteBy") or []),
        "createdAt": _iso(doc.get("createdAt")),
        "updatedAt": _iso(doc.get("updatedAt")),
    }


def _survey_detail(doc: Dict[str, Any], parent_id: Optional[str]) -> Dict[str, Any]:
    out = {
        "id": str(doc["_id"]),
        "surveyName": doc.get("projectName"),
        "surveyNo": doc.get("surveyNo"),
        "status": _survey_status(doc.get("projectStatus")),
        "parentProjectId": parent_id,
        "createdAt": _iso(doc.get("createdAt")),
        "updatedAt": _iso(doc.get("updatedAt")),
    }
    for key, (stored, _req) in _SURVEY_FIELDS.items():
        out[key] = doc.get(stored)
    return out


def _sort_rows(rows: List[Dict[str, Any]], sort: str, order: str) -> List[Dict[str, Any]]:
    desc = order.lower() == "desc"

    def key(r):
        v = r.get(sort)
        if isinstance(v, str):
            v = v.lower()
        return (v is None, "" if v is None else v)

    return sorted(rows, key=key, reverse=desc)


def _page(items: List[Any], page: int, page_size: int) -> List[Any]:
    start = (page - 1) * page_size
    return items[start:start + page_size]


def _check_order(order: str) -> None:
    if order.lower() not in ("asc", "desc"):
        _bad("order must be asc or desc")


# ============================================================ request models

class ProjectCreate(BaseModel):
    projectName: str
    projectNumber: str
    managerId: str
    fieldworkDatetime: str
    timezone: str


class ProjectUpdate(BaseModel):
    projectName: Optional[str] = None
    managerId: Optional[str] = None
    managerName: Optional[str] = None
    fieldworkDatetime: Optional[str] = None
    timezone: Optional[str] = None


class StatusBody(BaseModel):
    status: str


class SupplierAdd(BaseModel):
    vendorIds: List[str]
    buyPrice: Optional[str] = None
    currency: Optional[str] = None


class SupplierUpdate(BaseModel):
    buyPrice: Optional[str] = None
    currency: Optional[str] = None
    status: Optional[str] = None


# ============================================================ projects

@router.get("/projects")
def list_projects(
    user: str = Depends(verify_session),
    status: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "projectName",
    order: str = "asc",
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=200),
):
    _ensure_indexes()
    _check_order(order)
    COMPUTED = {"completes", "target", "ir", "conversion", "loi", "surveyCount"}
    if sort not in COMPUTED | {"projectName", "projectNumber", "status", "managerName"}:
        _bad("unknown sort field")
    cutoff = _now()  # list does not show window metrics

    everything = list(_col(COL_OPS_PROJECTS).find({"is_deleted": {"$ne": True}}))
    counts = {"all": len(everything)}
    for s in PROJECT_STATUSES:
        counts[s] = sum(1 for p in everything if p.get("status") == s)

    needle = (q or "").strip().lower()
    matched = [p for p in everything
               if (not status or p.get("status") == status)
               and (not needle or needle in str(p.get("projectName", "")).lower()
                    or needle in str(p.get("projectNumber", "")).lower())]

    if sort in COMPUTED:
        rows = _sort_rows(_project_rows(matched, user, cutoff), sort, order)
        items = _page(rows, page, pageSize)
    else:
        # simple field: sort docs, page, then compute metrics for the page only
        docs = sorted(matched, key=lambda p: (p.get(sort) is None,
                                              str(p.get(sort) or "").lower()),
                      reverse=order.lower() == "desc")
        items = _project_rows(_page(docs, page, pageSize), user, cutoff)

    return {"items": items, "total": len(matched), "counts": counts,
            "page": page, "pageSize": pageSize}


@router.post("/projects")
@require_permission(Permissions.OPS_PROJECT_CREATE)
def create_project(request: Request, body: ProjectCreate, user: str = Depends(verify_session)):
    _ensure_indexes()
    name = _check_name(body.projectName, "projectName")
    number = _check_name(body.projectNumber, "projectNumber", limit=32)
    manager = _check_name(body.managerId, "managerId")
    fieldwork = _check_dt(body.fieldworkDatetime, "fieldworkDatetime")
    tz = _check_tz(body.timezone)

    col = _col(COL_OPS_PROJECTS)
    if col.find_one({"projectNumber": number}):
        raise HTTPException(status_code=409, detail="Project number already exists")
    manager_doc = _col(COL_USERS).find_one({"username": manager}) or {}
    doc = {
        "projectName": name, "projectNumber": number, "managerId": manager,
        "managerName": manager_doc.get("name") or manager_doc.get("username") or manager,
        "fieldworkDatetime": fieldwork, "timezone": tz, "status": "live",
        "favoriteBy": [], "is_deleted": False,
        "createdAt": _now(), "updatedAt": _now(), "createdBy": user,
    }
    try:
        inserted = col.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Project number already exists")
    pid = str(inserted.inserted_id)
    _log(user=user, action="project.create", project_id=pid, new=number)
    return {"project": _project_view({**doc, "_id": inserted.inserted_id}, user)}


@router.post("/projects/backfill")
@require_permission(Permissions.OPS_PROJECT_CREATE)
def backfill_projects(request: Request, user: str = Depends(verify_session)):
    """Explicit only (never auto-run). One parent per legacy survey with no link.
    Idempotent: linked surveys are skipped on re-run."""
    _ensure_indexes()
    linked = {ln["surveyId"] for ln in _col(COL_LINKS).find({})}
    legacy = [s for s in _col(COL_PROJECTS).find({"is_deleted": {"$ne": True}})
              if str(s["_id"]) not in linked and s.get("surveyNo")
              and str(s.get("projectStatus") or "").lower() != "deleted"]
    created = linked_count = 0
    conflicts: List[str] = []
    for s in legacy:
        no = str(s["surveyNo"])
        parent = _col(COL_OPS_PROJECTS).find_one({"projectNumber": no})
        if parent is None:
            status = {"live": "live", "paused": "paused", "completed": "completed"}.get(
                _survey_status(s.get("projectStatus")), "paused")
            doc = {
                "projectName": s.get("projectName") or f"Survey {no}",
                "projectNumber": no, "managerId": "unassigned", "managerName": "Unassigned",
                "fieldworkDatetime": None, "timezone": s.get("timezone") or "Asia/Kolkata",
                "status": status, "favoriteBy": [], "is_deleted": False,
                "createdAt": _now(), "updatedAt": _now(), "createdBy": user,
                "backfilledFromSurveyId": str(s["_id"]),
            }
            parent_id = str(_col(COL_OPS_PROJECTS).insert_one(doc).inserted_id)
            created += 1
            _log(user=user, action="project.backfill", project_id=parent_id,
                 survey_id=str(s["_id"]), new=no)
        else:
            parent_id = str(parent["_id"])
            if parent.get("backfilledFromSurveyId") not in (None, str(s["_id"])):
                conflicts.append(no)  # number taken by an unrelated project: do not link
                continue
        _col(COL_LINKS).insert_one({"surveyId": str(s["_id"]), "parentProjectId": parent_id,
                                    "createdAt": _now(), "source": "backfill"})
        linked_count += 1
        _log(user=user, action="survey.link", project_id=parent_id, survey_id=str(s["_id"]),
             new=parent_id, extra={"source": "backfill"})
    return {"parentsCreated": created, "surveysLinked": linked_count, "conflicts": conflicts}


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: str = Depends(verify_session)):
    _ensure_indexes()
    doc = _get_project(project_id)
    return {"project": _project_view(doc, user)}


@router.put("/projects/{project_id}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def update_project(project_id: str, request: Request, body: ProjectUpdate,
                   user: str = Depends(verify_session)):
    _ensure_indexes()
    doc = _get_project(project_id)
    changes: Dict[str, Any] = {}
    data = body.model_dump(exclude_unset=True)
    if "projectName" in data:
        changes["projectName"] = _check_name(data["projectName"], "projectName")
    if "managerId" in data and data["managerId"] != doc.get("managerId"):
        # Changing the manager re-resolves the display name from users (same lookup as create).
        mid = _check_name(data["managerId"], "managerId")
        mdoc = _col(COL_USERS).find_one({"username": mid})
        if not mdoc:
            _bad("managerId is not a known user")
        changes["managerId"] = mid
        changes["managerName"] = mdoc.get("name") or mdoc.get("username") or mid
    elif "managerName" in data:
        changes["managerName"] = _check_name(data["managerName"], "managerName")
    if "fieldworkDatetime" in data and data["fieldworkDatetime"] is not None:
        changes["fieldworkDatetime"] = _check_dt(data["fieldworkDatetime"], "fieldworkDatetime")
    if "timezone" in data and data["timezone"] is not None:
        changes["timezone"] = _check_tz(data["timezone"])
    changes = {k: v for k, v in changes.items() if doc.get(k) != v}
    if changes:
        changes["updatedAt"] = _now()
        _col(COL_OPS_PROJECTS).update_one({"_id": doc["_id"]}, {"$set": changes})
        for k, v in changes.items():
            if k != "updatedAt":
                _log(user=user, action="project.update", project_id=str(doc["_id"]),
                     field=k, old=doc.get(k), new=v)
    return {"project": _project_view(_get_project(project_id), user)}


@router.post("/projects/{project_id}/favorite")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def toggle_favorite(project_id: str, request: Request, user: str = Depends(verify_session)):
    _ensure_indexes()
    doc = _get_project(project_id)
    fav = list(doc.get("favoriteBy") or [])
    was = user in fav
    fav = [u for u in fav if u != user] if was else fav + [user]
    _col(COL_OPS_PROJECTS).update_one({"_id": doc["_id"]}, {"$set": {"favoriteBy": fav}})
    _log(user=user, action="project.favorite", project_id=str(doc["_id"]),
         field="favoriteBy", old=was, new=not was)
    return {"isFavorite": not was}


@router.post("/projects/{project_id}/status")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def set_project_status(project_id: str, request: Request, body: StatusBody,
                       user: str = Depends(verify_session)):
    _ensure_indexes()
    if body.status not in PROJECT_STATUSES:
        _bad(f"status must be one of {', '.join(PROJECT_STATUSES)}")
    doc = _get_project(project_id)
    _col(COL_OPS_PROJECTS).update_one({"_id": doc["_id"]},
                                      {"$set": {"status": body.status, "updatedAt": _now()}})
    _log(user=user, action="project.status", project_id=str(doc["_id"]),
         field="status", old=doc.get("status"), new=body.status)
    return {"project": _project_view(_get_project(project_id), user)}


@router.get("/projects/{project_id}/surveys")
def list_project_surveys(
    project_id: str,
    user: str = Depends(verify_session),
    status: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "surveyName",
    order: str = "asc",
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=200),
    window: Optional[str] = None,
):
    _ensure_indexes()
    _check_order(order)
    cutoff = _window(window)
    project = _get_project(project_id)
    links = list(_col(COL_LINKS).find({"parentProjectId": str(project["_id"])}))
    ids = [ObjectId(ln["surveyId"]) for ln in links if ObjectId.is_valid(ln["surveyId"])]
    survey_docs = list(_col(COL_PROJECTS).find({"_id": {"$in": ids}, "is_deleted": {"$ne": True}})) if ids else []
    parent_of = {ln["surveyId"]: ln["parentProjectId"] for ln in links}
    metrics = _survey_metrics(survey_docs, cutoff)
    rows = [_survey_row(s, metrics.get(str(s.get("surveyNo")), _agg([], cutoff))) for s in survey_docs]

    counts = {"all": len(rows)}
    for s in SURVEY_STATUSES:
        counts[s] = sum(1 for r in rows if r["status"] == s)
    needle = (q or "").strip().lower()
    rows = [r for r in rows if (not status or r["status"] == status)
            and (not needle or needle in str(r["surveyName"] or "").lower()
                 or needle in str(r["surveyNo"] or "").lower())]
    if sort not in {"surveyName", "surveyNo", "status", "entrants", "terms", "oqs", "completes",
                    "completesWindow", "ir", "conversion", "loi", "abandons", "inFlights",
                    "defenderTerms", "sqTerms"}:
        _bad("unknown sort field")
    rows = _sort_rows(rows, sort, order)
    return {
        "project": _project_view(project, user),
        "items": _page(rows, page, pageSize),
        "total": len(rows),
        "counts": counts,
        "meta": {"window": window or "p24h", "unverifiedMetrics": UNVERIFIED_METRICS,
                 "sqTermsNote": SQ_TERMS_NOTE, "inflightMinutes": _inflight_minutes()},
    }


@router.post("/projects/{project_id}/surveys")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def create_survey(project_id: str, request: Request, body: Dict[str, Any] = Body(...),
                  user: str = Depends(verify_session)):
    _ensure_indexes()
    project = _get_project(project_id)
    fields = _clean_survey(body, partial=False)
    no = _generate_survey_no()
    doc = {**fields, "surveyNo": no, "projectStatus": "draft", "createdAt": _now(),
           "updatedAt": _now(), "is_deleted": False, "createdBy": user}
    doc.setdefault("devices", {})
    inserted = _col(COL_PROJECTS).insert_one(doc)
    sid = str(inserted.inserted_id)
    _col(COL_LINKS).insert_one({"surveyId": sid, "parentProjectId": str(project["_id"]),
                                "createdAt": _now()})
    _log(user=user, action="survey.create", project_id=str(project["_id"]), survey_id=sid, new=no)
    return {"survey": _survey_detail({**doc, "_id": inserted.inserted_id},
                                     str(project["_id"]))}


def _generate_survey_no() -> str:
    """Same logic as main.generate_survey_no (not imported: main is the app module)."""
    col = _col(COL_PROJECTS)
    for _ in range(1000):
        no = str(datetime.utcnow().microsecond % 100000).zfill(5)
        if not col.find_one({"surveyNo": no}):
            return no
    import random
    while True:
        no = str(random.randint(0, 99999)).zfill(5)
        if not col.find_one({"surveyNo": no}):
            return no


@router.get("/projects/{project_id}/change-log")
def project_change_log(project_id: str, user: str = Depends(verify_session),
                       page: int = Query(1, ge=1), pageSize: int = Query(100, ge=1, le=500)):
    _get_project(project_id)
    return _change_log_page({"projectId": str(project_id)}, page, pageSize)


# ============================================================ surveys

@router.get("/surveys/{survey_id}")
def get_survey(survey_id: str, user: str = Depends(verify_session)):
    doc = _get_survey(survey_id)
    link = _link_for_survey(survey_id)
    return {"survey": _survey_detail(doc, link["parentProjectId"] if link else None)}


@router.put("/surveys/{survey_id}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def update_survey(survey_id: str, request: Request, body: Dict[str, Any] = Body(...),
                  user: str = Depends(verify_session)):
    _ensure_indexes()
    doc = _get_survey(survey_id)
    fields = _clean_survey(body, partial=True)
    changes = {k: v for k, v in fields.items() if doc.get(k) != v}
    link = _link_for_survey(survey_id)
    parent_id = link["parentProjectId"] if link else None
    if changes:
        changes["updatedAt"] = _now()
        _col(COL_PROJECTS).update_one({"_id": doc["_id"]}, {"$set": changes})
        for stored, v in changes.items():
            if stored == "updatedAt":
                continue
            _log(user=user, action="survey.update", project_id=parent_id, survey_id=survey_id,
                 field=_STORED_TO_INPUT.get(stored, stored), old=doc.get(stored), new=v)
    return {"survey": _survey_detail(_get_survey(survey_id), parent_id)}


@router.post("/surveys/{survey_id}/status")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def set_survey_status(survey_id: str, request: Request, body: StatusBody,
                      user: str = Depends(verify_session)):
    _ensure_indexes()
    if body.status not in SURVEY_STATUSES:
        _bad(f"status must be one of {', '.join(SURVEY_STATUSES)}")
    doc = _get_survey(survey_id)
    link = _link_for_survey(survey_id)
    parent_id = link["parentProjectId"] if link else None
    old = _survey_status(doc.get("projectStatus"))
    # Legacy UI/routing read live|pause|close, so keep those spellings for the
    # three legacy states; new states are stored as-is (routing only serves 'live').
    stored = {"paused": "pause", "completed": "close"}.get(body.status, body.status)
    _col(COL_PROJECTS).update_one({"_id": doc["_id"]},
                                  {"$set": {"projectStatus": stored, "updatedAt": _now()}})
    _log(user=user, action="survey.status", project_id=parent_id, survey_id=survey_id,
         field="status", old=old, new=body.status)
    return {"survey": _survey_detail(_get_survey(survey_id), parent_id)}


@router.post("/surveys/{survey_id}/duplicate")
@require_permission(Permissions.OPS_PROJECT_CREATE)
def duplicate_survey(survey_id: str, request: Request, user: str = Depends(verify_session)):
    """Copies configuration only: new surveyNo, status draft, no suppliers, no traffic history."""
    _ensure_indexes()
    src = _get_survey(survey_id)
    link = _link_for_survey(survey_id)
    parent_id = link["parentProjectId"] if link else None
    skip = {"_id", "surveyNo", "createdAt", "updatedAt", "createdBy", "is_deleted", "deleted_at", "merged_into"}
    new_doc = {k: v for k, v in src.items() if k not in skip}
    new_no = _generate_survey_no()
    new_doc.update({"surveyNo": new_no, "projectStatus": "draft", "createdAt": _now(),
                    "updatedAt": _now(), "is_deleted": False, "createdBy": user,
                    "duplicatedFromSurveyId": survey_id})
    entry = new_doc.get("entryLink")
    if isinstance(entry, str) and "pid=" in entry:
        new_doc["entryLink"] = re.sub(r"pid=[^&]*", f"pid={new_no}", entry)
    inserted = _col(COL_PROJECTS).insert_one(new_doc)
    new_id = str(inserted.inserted_id)
    if parent_id:
        _col(COL_LINKS).insert_one({"surveyId": new_id, "parentProjectId": parent_id, "createdAt": _now()})
    _log(user=user, action="survey.duplicate", project_id=parent_id, survey_id=new_id,
         field="duplicatedFrom", old=survey_id, new=new_id)
    return {"survey": _survey_detail({**new_doc, "_id": inserted.inserted_id}, parent_id)}


@router.get("/surveys/{survey_id}/change-log")
def survey_change_log(survey_id: str, user: str = Depends(verify_session),
                      page: int = Query(1, ge=1), pageSize: int = Query(100, ge=1, le=500)):
    _get_survey(survey_id)
    return _change_log_page({"surveyId": str(survey_id)}, page, pageSize)


def _change_log_page(q: Dict[str, Any], page: int, page_size: int) -> Dict[str, Any]:
    rows = list(_col(COL_CHANGE_LOG).find(q))
    rows.sort(key=lambda r: r.get("ts") or datetime.min, reverse=True)
    items = [{**{k: v for k, v in r.items() if k != "_id"}, "ts": _iso(r.get("ts"))}
             for r in _page(rows, page, page_size)]
    return {"items": items, "total": len(rows), "page": page, "pageSize": page_size}


# ============================================================ suppliers

def _supplier_view(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(s["_id"]),
        "vendorId": s.get("vendorId"),
        "vendorName": s.get("vendorName"),
        "sourceName": s.get("sourceName"),
        "buyPrice": float(s["buyPrice"]) if s.get("buyPrice") not in (None, "") else None,
        "currency": s.get("currency", "INR"),
        "status": s.get("status", "live"),
    }


def _supplier_rows(survey: Dict[str, Any], sups: List[Dict[str, Any]], cutoff: datetime) -> List[Dict[str, Any]]:
    if not sups:
        return []
    recs = _traffic_find([survey.get("surveyNo")], vendor_ids=[s["vendorId"] for s in sups],
                         projection=_TRACK_PROJECTION)
    by_vid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by_vid[str(r.get("vendorId"))].append(r)
    rows = []
    for s in sups:
        m = _agg(by_vid.get(str(s["vendorId"]), []), cutoff)
        view = _supplier_view(s)
        rows.append({**view, **{k: m[k] for k in ("entrants", "terms", "defenderTerms", "oqs", "sqTerms",
                                                  "abandons", "inFlights", "completes", "completesWindow",
                                                  "ir", "conversion", "loi")},
                     **_expense(m["completes"], s.get("buyPrice"))})
    return rows


def _active_suppliers(survey_id: str) -> List[Dict[str, Any]]:
    return list(_col(COL_SUPPLIERS).find({"surveyId": str(survey_id), "removed": {"$ne": True}}))


@router.get("/surveys/{survey_id}/suppliers")
def list_suppliers(survey_id: str, user: str = Depends(verify_session), window: Optional[str] = None):
    _ensure_indexes()
    cutoff = _window(window)
    survey = _get_survey(survey_id)
    link = _link_for_survey(survey_id)
    project = _get_project(link["parentProjectId"]) if link else None
    rows = _supplier_rows(survey, _active_suppliers(survey_id), cutoff)
    if not _can_see_pricing(user):
        rows = _strip_pricing(rows)
    return {
        "project": _project_view(project, user) if project else None,
        "survey": {"id": str(survey["_id"]), "surveyName": survey.get("projectName"),
                   "surveyNo": survey.get("surveyNo"), "status": _survey_status(survey.get("projectStatus"))},
        "items": rows,
        "meta": {"window": window or "p24h", "unverifiedMetrics": UNVERIFIED_METRICS,
                 "sqTermsNote": SQ_TERMS_NOTE, "inflightMinutes": _inflight_minutes()},
    }


def _is_active_vendor(v: Dict[str, Any]) -> bool:
    return not v.get("is_deleted") and str(v.get("status") or "").lower() not in DEAD_VENDOR_STATUSES


@router.get("/managers")
def list_managers(user: str = Depends(verify_session)):
    """Active users who can be a project manager. Only username and display name
    leave this endpoint: no email, roles or other user fields."""
    out = []
    for u in _col(COL_USERS).find({"status": "active"}):
        username = str(u.get("username") or "").strip()
        if username:
            out.append({"username": username, "name": u.get("name") or username})
    out.sort(key=lambda m: m["name"].lower())
    return {"items": out}


@router.get("/vendors/lookup")
def vendor_lookup(q: Optional[str] = None, limit: int = Query(20, ge=1, le=100),
                  user: str = Depends(verify_session)):
    needle = (q or "").strip().lower()
    out = []
    for v in _col(COL_VENDORS).find({}):
        if not _is_active_vendor(v):
            continue
        vid = str(v.get("vid") or "")
        name = str(v.get("vendorName") or "")
        if needle and needle not in vid.lower() and needle not in name.lower():
            continue
        out.append({"vid": vid, "vendorName": name, "vendorType": v.get("vendorType")})
        if len(out) >= limit:
            break
    return {"items": out}


@router.post("/surveys/{survey_id}/suppliers")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def add_suppliers(survey_id: str, request: Request, body: SupplierAdd, user: str = Depends(verify_session)):
    _ensure_indexes()
    survey = _get_survey(survey_id)
    link = _link_for_survey(survey_id)
    parent_id = link["parentProjectId"] if link else None
    vids = [str(v).strip() for v in body.vendorIds]
    if not vids or any(not v for v in vids):
        _bad("vendorIds must be a non-empty list of vendor ids")
    if len(set(vids)) != len(vids):
        _bad("vendorIds contains duplicates")
    price = None
    if body.buyPrice is not None or body.currency is not None:
        _require_pricing(user, "Setting a supplier price")
    if body.buyPrice is not None:
        price = _check_price(body.buyPrice)
    currency = _check_currency(body.currency or "INR")

    existing = {str(s["vendorId"]): s for s in _col(COL_SUPPLIERS).find({"surveyId": str(survey_id)})}
    for vid in vids:
        if vid in existing and not existing[vid].get("removed"):
            raise HTTPException(status_code=409, detail=f"Vendor {vid} is already a supplier of this survey")

    vendors = {}
    unknown = []
    for vid in vids:
        v = _col(COL_VENDORS).find_one({"vid": vid})
        if not v or not _is_active_vendor(v):
            unknown.append(vid)
        else:
            vendors[vid] = v
    if unknown:
        _bad(f"Unknown or inactive vendor(s): {', '.join(unknown)}")

    out = []
    for vid in vids:
        v = vendors[vid]
        fields = {"surveyId": str(survey_id), "vendorId": vid,
                  "vendorName": v.get("vendorName"), "sourceName": v.get("vendorType"),
                  "buyPrice": str(price) if price is not None else None,
                  "currency": currency, "status": "live", "removed": False, "updatedAt": _now()}
        if vid in existing:  # previously removed: reactivate the same row
            _col(COL_SUPPLIERS).update_one({"_id": existing[vid]["_id"]}, {"$set": fields})
            sid = existing[vid]["_id"]
        else:
            sid = _col(COL_SUPPLIERS).insert_one({**fields, "createdAt": _now(), "createdBy": user}).inserted_id
        _log(user=user, action="supplier.add", project_id=parent_id, survey_id=str(survey_id),
             field="vendorId", new=vid, extra={"supplierId": str(sid)})
        out.append(_supplier_view({**fields, "_id": sid}))
    return {"items": out}


@router.put("/survey-suppliers/{sid}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def update_supplier(sid: str, request: Request, body: SupplierUpdate, user: str = Depends(verify_session)):
    _ensure_indexes()
    doc = _get_supplier(sid)
    data = body.model_dump(exclude_unset=True)
    changes: Dict[str, Any] = {}
    if "buyPrice" in data:
        new_price = _check_price(data["buyPrice"]) if data["buyPrice"] is not None else None
        old_price = Decimal(str(doc["buyPrice"])) if doc.get("buyPrice") not in (None, "") else None
        if new_price != old_price:
            _require_pricing(user, "Changing a supplier price")
            changes["buyPrice"] = str(new_price) if new_price is not None else None
    if data.get("currency") is not None:
        _require_pricing(user, "Changing a supplier currency")
        changes["currency"] = _check_currency(data["currency"])
    if data.get("status") is not None:
        if data["status"] not in SUPPLIER_STATUSES:
            _bad(f"status must be one of {', '.join(SUPPLIER_STATUSES)}")
        changes["status"] = data["status"]
    changes = {k: v for k, v in changes.items() if doc.get(k) != v}
    link = _link_for_survey(doc["surveyId"])
    parent_id = link["parentProjectId"] if link else None
    if changes:
        changes["updatedAt"] = _now()
        _col(COL_SUPPLIERS).update_one({"_id": doc["_id"]}, {"$set": changes})
        for k, v in changes.items():
            if k != "updatedAt":
                _log(user=user, action="supplier.update", project_id=parent_id,
                     survey_id=doc["surveyId"], field=k, old=doc.get(k), new=v,
                     extra={"supplierId": sid})
    return {"item": _supplier_view(_get_supplier(sid))}


@router.delete("/survey-suppliers/{sid}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def remove_supplier(sid: str, request: Request, user: str = Depends(verify_session)):
    """Soft remove. The vendor record is never touched."""
    _ensure_indexes()
    doc = _get_supplier(sid)
    _col(COL_SUPPLIERS).update_one({"_id": doc["_id"]},
                                   {"$set": {"removed": True, "removedAt": _now(), "removedBy": user}})
    link = _link_for_survey(doc["surveyId"])
    _log(user=user, action="supplier.remove", project_id=link["parentProjectId"] if link else None,
         survey_id=doc["surveyId"], field="vendorId", old=doc.get("vendorId"), extra={"supplierId": sid})
    return {"removed": True}


# ============================================================ traffic report

def _flatten(prefix: str, src: Any, row: Dict[str, Any]) -> None:
    if not isinstance(src, dict):
        return
    for k, v in src.items():
        key = f"{prefix}.{k}"
        if isinstance(v, dict):
            _flatten(key, v, row)
        elif isinstance(v, list):
            row[key] = json.dumps(v, default=str)
        else:
            row[key] = v


def _respondent_row(r: Dict[str, Any], include_answers: bool, pii: bool) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "respondentId": r.get("respondentId"),
        "surveyNo": (r.get("params") or {}).get("pid"),
        "vendor": str(r.get("vendorId")),
        "status": r.get("status"),
        "createdAt": _iso(r.get("createdAt")),
        "completedAt": _iso(r.get("completedAt")),
    }
    if pii:
        row["email"] = r.get("email")
        row["clientIp"] = r.get("clientIp")
    if include_answers:
        _flatten("qa", r.get("qualificationAnswers"), row)
        _flatten("profile", r.get("profilingData"), row)
    return row


_SUPPLIER_COLS = ["vendorId", "vendorName", "entrants", "terms", "defenderTerms", "oqs", "sqTerms", "abandons", "inFlights",
                  "completes", "completesWindow", "ir", "conversion", "loi", "buyPrice", "currency",
                  "expense", "expenseBasis", "status"]
_RESPONDENT_BASE = ["respondentId", "surveyNo", "vendor", "status", "createdAt", "completedAt"]


@router.get("/surveys/{survey_id}/traffic-report")
def traffic_report(
    survey_id: str,
    user: str = Depends(verify_session),
    supplierId: Optional[str] = None,
    format: str = Query("csv", pattern="^(csv|json)$"),
    includeAnswers: bool = False,
    window: Optional[str] = None,
):
    _ensure_indexes()
    cutoff = _window(window)
    survey = _get_survey(survey_id)
    link = _link_for_survey(survey_id)
    parent_id = link["parentProjectId"] if link else None
    sups = _active_suppliers(survey_id)
    if supplierId:
        sup = _get_supplier(supplierId)
        if str(sup.get("surveyId")) != str(survey_id):
            _not_found("Supplier not found on this survey")
        sups = [sup]
    pii = _is_admin(user)

    section_a = _supplier_rows(survey, sups, cutoff)
    if not _can_see_pricing(user):
        section_a = _strip_pricing(section_a)
    recs = _traffic_find([survey.get("surveyNo")],
                         vendor_ids=[s["vendorId"] for s in sups] if supplierId else None,
                         projection=None)
    respondents = [_respondent_row(r, includeAnswers, pii) for r in recs]
    answer_cols: List[str] = []
    if includeAnswers:
        seen = set()
        for row in respondents:
            for k in row:
                if k not in _RESPONDENT_BASE and k not in ("email", "clientIp") and k not in seen:
                    seen.add(k)
                    answer_cols.append(k)
        answer_cols.sort()
    resp_cols = _RESPONDENT_BASE + (["email", "clientIp"] if pii else []) + answer_cols

    _log(user=user, action="traffic.export", project_id=parent_id, survey_id=survey_id,
         field="format", new=format,
         extra={"supplierId": supplierId, "includeAnswers": includeAnswers, "pii": pii,
                "respondentRows": len(respondents)})

    if format == "json":
        return {"survey": {"id": str(survey["_id"]), "surveyNo": survey.get("surveyNo")},
                "suppliers": section_a, "respondents": respondents,
                "respondentColumns": resp_cols, "pii": pii,
                "meta": {"sqTermsNote": SQ_TERMS_NOTE, "inflightMinutes": _inflight_minutes()}}

    def _stream():
        buf = io.StringIO()
        w = csv.writer(buf)

        def flush():
            data = buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            return data

        w.writerow(["# Section A: supplier performance"])
        w.writerow(_SUPPLIER_COLS)
        for row in section_a:
            w.writerow([row.get(c) for c in _SUPPLIER_COLS])
        w.writerow([])
        w.writerow(["# Section B: respondents"])
        w.writerow(resp_cols)
        yield flush()
        for row in respondents:
            w.writerow([row.get(c) for c in resp_cols])
            if buf.tell() > 65536:
                yield flush()
        yield flush()

    filename = f"survey_{survey.get('surveyNo')}_traffic.csv"
    return StreamingResponse(_stream(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ============================================================ search

@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=100), user: str = Depends(verify_session)):
    _ensure_indexes()
    rx = {"$regex": re.escape(q.strip()), "$options": "i"}
    projects = list(_col(COL_OPS_PROJECTS).find(
        {"is_deleted": {"$ne": True}, "$or": [{"projectName": rx}, {"projectNumber": rx}]}))[:10]
    surveys = list(_col(COL_PROJECTS).find(
        {"is_deleted": {"$ne": True}, "$or": [{"projectName": rx}, {"surveyNo": rx}]}))[:10]
    sups = list(_col(COL_SUPPLIERS).find(
        {"removed": {"$ne": True}, "$or": [{"vendorName": rx}, {"vendorId": rx}]}))[:10]
    # Supplier hits need their survey's number and parent too: resolve both in one read each.
    sup_sids = {str(s.get("surveyId")) for s in sups if ObjectId.is_valid(str(s.get("surveyId")))}
    sup_surveys = {str(d["_id"]): d for d in _col(COL_PROJECTS).find(
        {"_id": {"$in": [ObjectId(x) for x in sup_sids]}})} if sup_sids else {}
    all_sids = {str(s["_id"]) for s in surveys} | sup_sids
    link_of = {ln["surveyId"]: ln["parentProjectId"] for ln in
               _col(COL_LINKS).find({"surveyId": {"$in": list(all_sids)}})} if all_sids else {}
    return {
        "projects": [{"id": str(p["_id"]), "projectName": p.get("projectName"),
                      "projectNumber": p.get("projectNumber"), "status": p.get("status")} for p in projects],
        "surveys": [{"id": str(s["_id"]), "surveyName": s.get("projectName"), "surveyNo": s.get("surveyNo"),
                     "status": _survey_status(s.get("projectStatus")),
                     "parentProjectId": link_of.get(str(s["_id"]))} for s in surveys],
        "suppliers": [{"id": str(s["_id"]), "surveyId": s.get("surveyId"),
                       "surveyNo": (sup_surveys.get(str(s.get("surveyId"))) or {}).get("surveyNo"),
                       "parentProjectId": link_of.get(str(s.get("surveyId"))),
                       "vendorId": s.get("vendorId"), "vendorName": s.get("vendorName"),
                       "status": s.get("status")} for s in sups],
    }


@router.get("/surveys/{survey_id}/test-link")
def survey_test_link(survey_id: str, user: str = Depends(verify_session)):
    """The survey's stored liveLink, unchanged, if it is a valid http(s) URL.
    Read-only: writes nothing and records no traffic."""
    doc = _get_survey(survey_id)
    raw = doc.get("liveLink")
    if isinstance(raw, str):
        p = urlparse(raw)
        if p.scheme in ("http", "https") and p.netloc:
            return {"url": raw}
    _not_found("No survey URL set")
