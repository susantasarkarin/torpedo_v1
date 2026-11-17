"""
Ops: Project -> Survey -> Supplier layer.

Schema (email_automation):
  ops_projects     one row per project (clientName, source are optional extras).
  ops_surveys      one row per survey: config + status. Owns surveyNumber (6-digit,
                   from the "counters" collection). Config edits touch only this doc.
  survey_suppliers one row per supplier participation in a survey. A participation
                   either points at one legacy email_automation.projects doc (the
                   traffic link: legacyProjectId + surveyNo = traffic pid) or, with
                   surveyNo null, is waiting for its link (needsLink).
  projects         legacy traffic link docs. Read for metrics and for linking. The
                   only write is the status write-through (projectStatus) on a linked
                   participation.

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
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.services.traffic_service import TrafficService
from database import get_email_automation_db, get_traffic_db
from db import crm as _crm_db  # crm_db.opportunities = RFQs (read-only here, except via the RFQ link)
from rbac.decorators import require_permission
from rbac.permissions import Permissions
from session_state import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops", tags=["Ops Surveys"])

# Collections (all in email_automation unless noted)
COL_PROJECTS = "projects"            # legacy: one doc per SUPPLIER LINK (traffic pid = surveyNo)
COL_OPS_PROJECTS = "ops_projects"
COL_OPS_SURVEYS = "ops_surveys"
COL_SUPPLIERS = "survey_suppliers"
COL_COUNTERS = "counters"
COL_CHANGE_LOG = "ops_change_log"
COL_VENDORS = "vendors"
COL_USERS = "users"
COL_TRAFFIC = "url_parameters"       # in traffic_flow_db

SURVEY_NUMBER_KEY = "ops_survey_number"
SURVEY_NUMBER_BASE = 100000          # first surveyNumber = 100000 + 1
PROJECT_NUMBER_KEY = "ops_project_number"   # counters doc; projectNumber is 'P' + 3+ digits
PROJECT_NUMBER_RE = re.compile(r"^P(\d+)$")
PROJECT_NUMBER_ATTEMPTS = 5          # retries on a unique-index clash
DEFAULT_TIMEZONE = "Asia/Kolkata"

PROJECT_STATUSES = ("live", "paused", "completed")
SURVEY_STATUSES = ("live", "paused", "completed", "draft", "cancelled", "auto_paused", "scheduled")
SUPPLIER_STATUSES = ("live", "paused", "completed")
DEAD_VENDOR_STATUSES = ("deleted", "inactive", "archived")
LEGACY_STATUS_WRITE = {"paused": "pause", "completed": "close"}  # supplier status -> legacy projectStatus
# Metrics whose definition is not yet confirmed. Empty: sqTerms is defined below.
UNVERIFIED_METRICS: List[str] = []
SQ_TERMS_NOTE = "Screened out by our qualification before reaching the client survey; counted separately from Terms."
# notRoutedReason values written with status NOT_ROUTED (routers/traffic.py):
#   prescreen_fail  -> traffic.py:3455, fails our project qualification (screener)
#   country         -> traffic.py:3455, fails our country check (screener)
#   (empty)         -> traffic.py:3560 falls back to prescreen_fail (screener)
#   router_link     -> traffic.py:3465/3560, no eligible survey in the country (capacity, NOT sqTerms)
#   panel_first     -> never written as NOT_ROUTED (traffic.py:3557)
# Only the screener reasons feed sqTerms. Their rows carry params.pid == supplier surveyNo
# (ADHOC flow, params.api "false"), so they are attributable per supplier link.
SCREENER_NOT_ROUTED_REASONS = ("prescreen_fail", "country")
WINDOWS = {"p24h": timedelta(hours=24), "p14d": timedelta(days=14)}

# Pure reuse of the traffic_service definitions (no collections bound).
_TS = TrafficService.__new__(TrafficService)
_TRACK_PROJECTION = {"status": 1, "createdAt": 1, "completedAt": 1, "params.pid": 1, "vendorId": 1,
                     "notRoutedReason": 1}

# Additive counts; everything else (ir, conversion, loi) is derived by _finish().
_ADDITIVE = ("entrants", "terms", "defenderTerms", "sqTerms", "oqs", "completes",
             "completesWindow", "abandons", "inFlights")
_SUPPLIER_METRICS = ("entrants", "terms", "defenderTerms", "oqs", "sqTerms", "abandons", "inFlights",
                     "completes", "completesWindow", "ir", "conversion", "loi")

_INDEXES_READY = False


# ============================================================ infrastructure

def _db():
    return get_email_automation_db()


def _col(name: str):
    return _db()[name]


def _traffic_col():
    return get_traffic_db()[COL_TRAFFIC]


def _ensure_indexes() -> None:
    """Idempotent, created lazily on first use (never at import).

    Note: a legacy unique index "ux_survey_suppliers_survey_vendor" (surveyId, vendorId) may
    still exist in a database created by the earlier schema. It blocks the same vendor being
    in one survey twice and must be dropped by hand; this function does not drop indexes."""
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        db = _db()
        try:  # superseded by (surveyId, legacyProjectId): one vendor may hold several links
            db[COL_SUPPLIERS].drop_index("ux_survey_suppliers_survey_vendor")
        except Exception:
            pass  # absent (fresh DB) or fake mongo
        db[COL_OPS_PROJECTS].create_index("projectNumber", unique=True, name="ux_ops_projects_number")
        db[COL_OPS_SURVEYS].create_index("surveyNumber", unique=True, name="ux_ops_surveys_number")
        db[COL_OPS_SURVEYS].create_index([("projectId", 1), ("is_deleted", 1)], name="ix_ops_surveys_project")
        db[COL_SUPPLIERS].create_index(
            [("surveyId", 1), ("legacyProjectId", 1)], unique=True,
            partialFilterExpression={"legacyProjectId": {"$type": "string"}},
            name="ux_survey_suppliers_survey_legacy")
        db[COL_SUPPLIERS].create_index("legacyProjectId", name="ix_survey_suppliers_legacy")
        db[COL_SUPPLIERS].create_index("surveyNo", name="ix_survey_suppliers_surveyno")
        db[COL_SUPPLIERS].create_index("surveyId", name="ix_survey_suppliers_survey")
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


def _conflict(msg: str):
    raise HTTPException(status_code=409, detail=msg)


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


# survey input key -> required on create. Stored field names are the same as the keys.
_SURVEY_FIELDS = {
    "surveyName": True,
    "surveyUrl": True,
    "targetN": True,
    "loi": True,
    "ir": True,
    "countryCode": True,
    "languageCode": True,
    "timezone": False,
    "devices": False,
    "piiEnabled": False,
    "outOfFieldAt": False,
}


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
    """Returns field -> value. Raises 422 on any invalid input."""
    out: Dict[str, Any] = {}
    for key, required in _SURVEY_FIELDS.items():
        if data.get(key) is not None:
            out[key] = _clean_survey_value(key, data[key])
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
    """Legacy projectStatus -> normalised status. Unknown/missing -> draft."""
    key = str(raw or "").strip().lower()
    return {"live": "live", "pause": "paused", "paused": "paused",
            "close": "completed", "completed": "completed"}.get(
        key, key if key in SURVEY_STATUSES else "draft")


def _supplier_status_from_legacy(raw: Any) -> str:
    """Legacy projectStatus of a linked traffic doc -> supplier status (live|paused|completed).
    Legacy states outside those three (draft, cancelled, ...) read as paused."""
    s = _survey_status(raw)
    return s if s in SUPPLIER_STATUSES else "paused"


# ============================================================ metrics

def _vid_variants(vids) -> List[Any]:
    out: List[Any] = []
    for v in vids:
        s = str(v).strip()
        for cand in (s, int(s) if s.isdigit() else None):
            if cand is not None and cand not in out:
                out.append(cand)
    return out


def _traffic_find(pids, projection=None) -> List[Dict[str, Any]]:
    """Traffic rows for supplier link numbers (params.pid), same filter as
    TrafficService project stats (params.api == "false")."""
    wanted = [str(p) for p in pids if p not in (None, "")]
    if not wanted:
        return []
    q: Dict[str, Any] = {"params.api": "false", "params.pid": {"$in": wanted}}
    return list(_traffic_col().find(q, projection))


def _group_by_pid(records) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        grouped[str((r.get("params") or {}).get("pid"))].append(r)
    return grouped


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


def _count(records: List[Dict[str, Any]], cutoff: Optional[datetime]) -> Tuple[Dict[str, int], List[float]]:
    """Additive counts for one set of traffic rows, plus the raw LOI durations (minutes).

    terms         = every row TrafficService normalises to Terminate.
    defenderTerms = subset of terms with a SECURITY status (client security terminate).
    sqTerms       = screener NOT_ROUTED rows (_is_screener_out). Separate from terms;
                    these rows are never counted as inFlights or abandons.
    inFlights     = non-final rows (normaliser "Incomplete") created within OPS_INFLIGHT_MINUTES.
    abandons      = non-final rows created earlier than that, or with no parseable createdAt.
    The LOI list is kept raw so that a parent can take the median over all its rows."""
    live_after = _now() - timedelta(minutes=_inflight_minutes())
    c = {k: 0 for k in _ADDITIVE}
    loi: List[float] = []
    for r in records:
        c["entrants"] += 1
        if _is_screener_out(r):
            c["sqTerms"] += 1
            continue
        norm = _TS._normalize_status(r.get("status", ""))
        if norm == "Complete":
            c["completes"] += 1
            created = _TS._safe_parse_datetime(r.get("createdAt"))
            done = _TS._safe_parse_datetime(r.get("completedAt"))
            if cutoff is not None and done is not None and done >= cutoff:
                c["completesWindow"] += 1
            if created and done:
                secs = (done - created).total_seconds()
                if secs > 0:
                    loi.append(secs / 60.0)
        elif norm == "Terminate":
            c["terms"] += 1
            if _is_defender_term(r.get("status")):
                c["defenderTerms"] += 1
        elif norm == "Quota Full":
            c["oqs"] += 1
        else:  # "Incomplete": the normaliser's default, i.e. every non-final status
            created = _TS._safe_parse_datetime(r.get("createdAt"))
            if created is not None and created >= live_after:
                c["inFlights"] += 1
            else:
                c["abandons"] += 1
    return c, loi


def _combine(parts: List[Tuple[Dict[str, int], List[float]]]) -> Tuple[Dict[str, int], List[float]]:
    total = {k: 0 for k in _ADDITIVE}
    loi: List[float] = []
    for c, lw in parts:
        for k in _ADDITIVE:
            total[k] += c[k]
        loi.extend(lw)
    return total, loi


def _finish(c: Dict[str, int], loi: List[float]) -> Dict[str, Any]:
    """Derived fields from summed counts. LOI is the median of all raw durations."""
    completes, terms, entrants = c["completes"], c["terms"], c["entrants"]
    return {**c,
            "ir": round(completes / (completes + terms) * 100, 1) if (completes + terms) else 0.0,
            "conversion": round(completes / entrants * 100, 1) if entrants else 0.0,
            "loi": round(statistics.median(loi), 1) if loi else None}


def _agg(records: List[Dict[str, Any]], cutoff: Optional[datetime]) -> Dict[str, Any]:
    return _finish(*_count(records, cutoff))


def _expense(completes: int, buy_price: Any) -> Dict[str, Any]:
    if buy_price in (None, ""):
        return {"expense": None, "expenseBasis": None}
    amount = (Decimal(completes) * Decimal(str(buy_price))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"expense": float(amount), "expenseBasis": "completes*buyPrice"}


def _pids(rows: List[Dict[str, Any]]) -> List[str]:
    """Distinct traffic pids (supplier surveyNo) of supplier rows, order kept. Unlinked rows skipped."""
    out: List[str] = []
    for r in rows:
        no = r.get("surveyNo")
        if no and str(no) not in out:
            out.append(str(no))
    return out


def _read_grouped(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """One traffic read for every linked row's pid -> pid -> records."""
    return _group_by_pid(_traffic_find(_pids(rows), projection=_TRACK_PROJECTION))


def _survey_metrics(surveys: List[Dict[str, Any]], cutoff: datetime) -> Dict[str, Dict[str, Any]]:
    """survey id -> metrics. Sum of the survey's active supplier pids (each pid once).
    One traffic read for all surveys."""
    sups = _suppliers_by_survey([str(s["_id"]) for s in surveys])
    grouped = _read_grouped([r for rows in sups.values() for r in rows])
    out = {}
    for s in surveys:
        sid = str(s["_id"])
        out[sid] = _finish(*_combine([_count(grouped.get(p, []), cutoff) for p in _pids(sups.get(sid, []))]))
    return out


def _survey_row(survey: Dict[str, Any], m: Dict[str, Any]) -> Dict[str, Any]:
    number = survey.get("surveyNumber")
    return {
        "id": str(survey["_id"]),
        "surveyName": survey.get("surveyName"),
        "surveyNo": number,
        "surveyNumber": number,
        "status": survey.get("status") or "draft",
        "target": int(survey.get("targetN") or 0),
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


# ============================================================ lookups

def _get_project(project_id: str) -> Dict[str, Any]:
    doc = _col(COL_OPS_PROJECTS).find_one({"_id": _oid(project_id, "Project"), "is_deleted": {"$ne": True}})
    if not doc:
        _not_found("Project not found")
    return doc


def _find_survey(survey_id: str) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(str(survey_id)):
        return None
    return _col(COL_OPS_SURVEYS).find_one({"_id": ObjectId(str(survey_id)), "is_deleted": {"$ne": True}})


def _get_survey(survey_id: str) -> Dict[str, Any]:
    doc = _find_survey(survey_id)
    if not doc:
        _not_found("Survey not found")
    return doc


def _project_of_survey(survey_id: str) -> Optional[str]:
    doc = _find_survey(survey_id)
    return doc.get("projectId") if doc else None


def _get_supplier(sid: str) -> Dict[str, Any]:
    doc = _col(COL_SUPPLIERS).find_one({"_id": _oid(sid, "Supplier"), "removed": {"$ne": True}})
    if not doc:
        _not_found("Supplier not found")
    return doc


def _surveys_of(project_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """parent project id -> live survey docs. One read."""
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    ids = [str(p) for p in project_ids]
    if not ids:
        return out
    for d in _col(COL_OPS_SURVEYS).find({"projectId": {"$in": ids}, "is_deleted": {"$ne": True}}):
        out[str(d.get("projectId"))].append(d)
    return out


def _suppliers_by_survey(survey_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """survey id -> active supplier rows (oldest first). One read."""
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    ids = [str(s) for s in survey_ids]
    if not ids:
        return out
    for r in _col(COL_SUPPLIERS).find({"surveyId": {"$in": ids}, "removed": {"$ne": True}}):
        out[str(r.get("surveyId"))].append(r)
    for sid in out:
        out[sid].sort(key=lambda r: (r.get("createdAt") or datetime.min, str(r["_id"])))
    return out


def _active_suppliers(survey_id: str) -> List[Dict[str, Any]]:
    return _suppliers_by_survey([str(survey_id)]).get(str(survey_id), [])


def _legacy_docs(ids) -> Dict[str, Dict[str, Any]]:
    """str legacy id -> live legacy traffic doc. One read."""
    oids = [ObjectId(i) for i in {str(x) for x in ids if x} if ObjectId.is_valid(i)]
    if not oids:
        return {}
    return {str(d["_id"]): d for d in _col(COL_PROJECTS).find(
        {"_id": {"$in": oids}, "is_deleted": {"$ne": True}})}


def _effective_status(row: Dict[str, Any], legacy_doc: Optional[Dict[str, Any]]) -> str:
    """Linked and legacy doc live -> derived from projectStatus. Otherwise the stored status."""
    if legacy_doc is not None:
        return _supplier_status_from_legacy(legacy_doc.get("projectStatus"))
    return row.get("status") or "live"


def _project_rows(projects: List[Dict[str, Any]], username: str, cutoff: datetime) -> List[Dict[str, Any]]:
    surveys_by_parent = _surveys_of([str(p["_id"]) for p in projects])
    all_sids = [str(s["_id"]) for v in surveys_by_parent.values() for s in v]
    sups = _suppliers_by_survey(all_sids)
    grouped = _read_grouped([r for sid in all_sids for r in sups.get(sid, [])])
    rows = []
    for p in projects:
        pid = str(p["_id"])
        surveys = surveys_by_parent.get(pid, [])
        member = [r for s in surveys for r in sups.get(str(s["_id"]), [])]
        m = _finish(*_combine([_count(grouped.get(no, []), cutoff) for no in _pids(member)]))
        rows.append({
            "id": pid,
            "projectName": p.get("projectName"),
            "projectNumber": p.get("projectNumber"),
            "clientName": p.get("clientName"),
            "managerId": p.get("managerId"),
            "managerName": p.get("managerName"),
            "status": p.get("status"),
            "isFavorite": username in (p.get("favoriteBy") or []),
            "surveyCount": len(surveys),
            "completes": m["completes"],
            "target": sum(int(s.get("targetN") or 0) for s in surveys),
            "ir": m["ir"],
            "conversion": m["conversion"],
            "loi": m["loi"],
            "rfq": _rfq_view(p),
            "rfqCandidates": _rfq_candidates(p),
        })
    return rows


def _project_view(doc: Dict[str, Any], username: str) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "projectName": doc.get("projectName"),
        "projectNumber": doc.get("projectNumber"),
        "clientName": doc.get("clientName"),
        "source": doc.get("source"),
        "managerId": doc.get("managerId"),
        "managerName": doc.get("managerName"),
        "fieldworkDatetime": doc.get("fieldworkDatetime"),
        "timezone": doc.get("timezone"),
        "status": doc.get("status"),
        "isFavorite": username in (doc.get("favoriteBy") or []),
        "rfq": _rfq_view(doc),
        "rfqCandidates": _rfq_candidates(doc),
        "createdAt": _iso(doc.get("createdAt")),
        "updatedAt": _iso(doc.get("updatedAt")),
    }


def _survey_detail(doc: Dict[str, Any]) -> Dict[str, Any]:
    number = doc.get("surveyNumber")
    out = {
        "id": str(doc["_id"]),
        "surveyName": doc.get("surveyName"),
        "surveyNo": number,            # compatibility: same value as surveyNumber
        "surveyNumber": number,
        "status": doc.get("status") or "draft",
        "parentProjectId": doc.get("projectId"),
        "createdAt": _iso(doc.get("createdAt")),
        "updatedAt": _iso(doc.get("updatedAt")),
    }
    for key in _SURVEY_FIELDS:
        out[key] = doc.get(key)
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


def _next_survey_number() -> str:
    """Atomic: counters doc "ops_survey_number" is $inc'd; first value is 100001."""
    doc = _col(COL_COUNTERS).find_one_and_update(
        {"_id": SURVEY_NUMBER_KEY}, {"$inc": {"seq": 1}},
        upsert=True, return_document=ReturnDocument.AFTER)
    return str(SURVEY_NUMBER_BASE + int(doc["seq"]))


def _seed_project_number() -> int:
    """Highest numeric suffix among existing P<digits> project numbers (0 when none)."""
    top = 0
    for p in _col(COL_OPS_PROJECTS).find({}):
        m = PROJECT_NUMBER_RE.match(str(p.get("projectNumber") or ""))
        if m:
            top = max(top, int(m.group(1)))
    return top


def _next_project_number() -> str:
    """Atomic: counters doc "ops_project_number" is $inc'd. Seeded lazily from the highest
    existing P<digits> number, so the first allocation is max + 1 (P224 when P223 exists)."""
    counters = _col(COL_COUNTERS)
    if counters.find_one({"_id": PROJECT_NUMBER_KEY}) is None:
        try:
            counters.insert_one({"_id": PROJECT_NUMBER_KEY, "seq": _seed_project_number()})
        except DuplicateKeyError:
            pass  # another request seeded it first
    doc = counters.find_one_and_update(
        {"_id": PROJECT_NUMBER_KEY}, {"$inc": {"seq": 1}},
        upsert=True, return_document=ReturnDocument.AFTER)
    return f"P{int(doc['seq']):03d}"


def _default_manager() -> Tuple[str, str]:
    """(username, display name) of the manager every new project gets."""
    return (os.getenv("OPS_DEFAULT_MANAGER_ID") or "susanta.sarkar",
            os.getenv("OPS_DEFAULT_MANAGER_NAME") or "Susanta Sarkar")


def _now_ist_iso() -> str:
    """Current India time, whole seconds, as an offset-aware ISO string."""
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).replace(microsecond=0).isoformat()


# ============================================================ RFQ link (crm_db.opportunities)

RFQ_FILTERS = ("matched", "unmatched", "ambiguous")
RFQ_LOOKUP_LIMIT = 20
RFQ_CANDIDATE_LIMIT = 5


def _opps_col():
    return _crm_db()["opportunities"]


def _opp_by_id(rid: str) -> Optional[Dict[str, Any]]:
    doc = _opps_col().find_one({"_id": str(rid)})
    if not doc and ObjectId.is_valid(str(rid)):
        doc = _opps_col().find_one({"_id": ObjectId(str(rid))})
    return doc


def _rfq_state(doc: Dict[str, Any]) -> str:
    if doc.get("rfqId"):
        return "matched"
    return "ambiguous" if doc.get("rfqCandidates") else "unmatched"


def _rfq_view(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rid = doc.get("rfqId")
    if not rid:
        return None
    return {"id": str(rid), "title": doc.get("rfqTitle"), "stage": doc.get("rfqStage"),
            "method": (doc.get("rfqMatch") or {}).get("method")}


def _rfq_candidates(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Candidates only while unresolved; a matched project reports none."""
    if doc.get("rfqId"):
        return []
    return list(doc.get("rfqCandidates") or [])


# ============================================================ request models

class ProjectCreate(BaseModel):
    projectName: str
    projectNumber: Optional[str] = None      # ignored: the system allocates the number
    managerId: Optional[str] = None          # default: OPS_DEFAULT_MANAGER_ID
    managerName: Optional[str] = None        # display fallback for a non-default manager
    fieldworkDatetime: Optional[str] = None  # default: now (India time)
    timezone: Optional[str] = None           # default: Asia/Kolkata
    clientName: Optional[str] = None


class ProjectUpdate(BaseModel):
    projectName: Optional[str] = None
    clientName: Optional[str] = None
    managerId: Optional[str] = None
    managerName: Optional[str] = None
    fieldworkDatetime: Optional[str] = None
    timezone: Optional[str] = None


class StatusBody(BaseModel):
    status: str


class SupplierLink(BaseModel):
    vendorId: str
    surveyNo: str


class SupplierAdd(BaseModel):
    vendorIds: Optional[List[str]] = None
    links: Optional[List[SupplierLink]] = None
    buyPrice: Optional[str] = None
    currency: Optional[str] = None


class SupplierUpdate(BaseModel):
    buyPrice: Optional[str] = None
    currency: Optional[str] = None
    status: Optional[str] = None


class SupplierLinkBody(BaseModel):
    surveyNo: str


class RfqBody(BaseModel):
    rfqId: Optional[str] = None


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
    rfq: Optional[str] = None,
):
    _ensure_indexes()
    _check_order(order)
    COMPUTED = {"completes", "target", "ir", "conversion", "loi", "surveyCount"}
    if sort not in COMPUTED | {"projectName", "projectNumber", "status", "managerName"}:
        _bad("unknown sort field")
    if rfq and rfq not in RFQ_FILTERS:
        _bad("rfq must be matched, unmatched or ambiguous")
    cutoff = _now()  # list does not show window metrics

    everything = list(_col(COL_OPS_PROJECTS).find({"is_deleted": {"$ne": True}}))
    counts = {"all": len(everything)}
    for s in PROJECT_STATUSES:
        counts[s] = sum(1 for p in everything if p.get("status") == s)

    needle = (q or "").strip().lower()
    matched = [p for p in everything
               if (not status or p.get("status") == status)
               and (not rfq or _rfq_state(p) == rfq)
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
    # projectNumber in the body is ignored: the number is allocated below.
    name = _check_name(body.projectName, "projectName")
    manager_id, manager_name = _create_manager(body)
    raw_fieldwork = (body.fieldworkDatetime or "").strip()
    fieldwork = _check_dt(raw_fieldwork, "fieldworkDatetime") if raw_fieldwork else _now_ist_iso()
    raw_tz = (body.timezone or "").strip()
    tz = _check_tz(raw_tz) if raw_tz else DEFAULT_TIMEZONE
    client = (body.clientName or "").strip()
    if len(client) > 200:
        _bad("clientName is too long")

    col = _col(COL_OPS_PROJECTS)
    for _ in range(PROJECT_NUMBER_ATTEMPTS):
        number = _next_project_number()
        doc = {
            "projectName": name, "projectNumber": number, "managerId": manager_id,
            "managerName": manager_name,
            "clientName": client or None, "source": "manual",
            "fieldworkDatetime": fieldwork, "timezone": tz, "status": "live",
            "favoriteBy": [], "is_deleted": False,
            "createdAt": _now(), "updatedAt": _now(), "createdBy": user,
        }
        try:
            inserted = col.insert_one(doc)
        except DuplicateKeyError:
            continue  # number already taken (counter behind the data): allocate again
        pid = str(inserted.inserted_id)
        _log(user=user, action="project.create", project_id=pid, new=number)
        return {"project": _project_view({**doc, "_id": inserted.inserted_id}, user)}
    raise HTTPException(status_code=409, detail="Could not allocate a project number, try again")


def _create_manager(body: "ProjectCreate") -> Tuple[str, str]:
    """Default manager unless a different managerId is supplied (only then is users read)."""
    default_id, default_name = _default_manager()
    mid = (body.managerId or "").strip()
    if not mid or mid == default_id:
        return default_id, default_name
    mid = _check_name(mid, "managerId")
    mdoc = _col(COL_USERS).find_one({"username": mid}) or {}
    name = (mdoc.get("name") or mdoc.get("username") or (body.managerName or "").strip() or mid)
    return mid, name


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
    if "clientName" in data:
        client = (data["clientName"] or "").strip()
        if len(client) > 200:
            _bad("clientName is too long")
        changes["clientName"] = client or None
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


@router.put("/projects/{project_id}/rfq")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def set_project_rfq(project_id: str, request: Request, body: RfqBody,
                    user: str = Depends(verify_session)):
    """Manual RFQ link. rfqId None clears it; either way the method is 'manual', so the
    matcher script never overwrites this decision."""
    _ensure_indexes()
    doc = _get_project(project_id)
    rid = (body.rfqId or "").strip() or None
    opp = None
    if rid:
        opp = _opp_by_id(rid)
        if not opp:
            _bad("rfqId is not a known RFQ")
    now = _now()
    changes = {
        "rfqId": str(opp["_id"]) if opp else None,
        "rfqTitle": opp.get("title") if opp else None,
        "rfqStage": opp.get("stage") if opp else None,
        "rfqMatch": {"method": "manual", "matchedAt": now, "by": user},
        "rfqCandidates": [],
        "updatedAt": now,
    }
    _col(COL_OPS_PROJECTS).update_one({"_id": doc["_id"]}, {"$set": changes})
    _log(user=user, action="project.rfq_match", project_id=str(doc["_id"]), field="rfqId",
         old=doc.get("rfqId"), new=changes["rfqId"], extra={"method": "manual"})
    return {"project": _project_view(_get_project(project_id), user)}


@router.get("/rfq/lookup")
def rfq_lookup(q: Optional[str] = None, user: str = Depends(verify_session)):
    """Title search over crm_db.opportunities for the RFQ picker."""
    needle = (q or "").strip()
    flt = {"title": {"$regex": re.escape(needle), "$options": "i"}} if needle else {}
    # Python-side check keeps results right even where the regex is ignored (fake mongo).
    hits = [o for o in _opps_col().find(flt).limit(200)
            if needle.casefold() in str(o.get("title") or "").casefold()]
    return {"items": [{"id": str(o["_id"]), "title": o.get("title"), "stage": o.get("stage")}
                      for o in hits[:RFQ_LOOKUP_LIMIT]]}


@router.get("/rfq/{rfqId}/projects")
def rfq_projects(rfqId: str, user: str = Depends(verify_session)):
    docs = _col(COL_OPS_PROJECTS).find({"rfqId": str(rfqId), "is_deleted": {"$ne": True}})
    return {"items": [{"id": str(d["_id"]), "projectName": d.get("projectName"),
                       "projectNumber": d.get("projectNumber")} for d in docs]}


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
    pid = str(project["_id"])
    survey_docs = _surveys_of([pid]).get(pid, [])
    metrics = _survey_metrics(survey_docs, cutoff)
    rows = [_survey_row(s, metrics[str(s["_id"])]) for s in survey_docs]

    counts = {"all": len(rows)}
    for s in SURVEY_STATUSES:
        counts[s] = sum(1 for r in rows if r["status"] == s)
    needle = (q or "").strip().lower()
    rows = [r for r in rows if (not status or r["status"] == status)
            and (not needle or needle in str(r["surveyName"] or "").lower()
                 or needle in str(r["surveyNo"] or "").lower())]
    if sort not in {"surveyName", "surveyNo", "status", "target", "entrants", "terms", "oqs", "completes",
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
    pid = str(project["_id"])
    no = _next_survey_number()
    doc = {**fields, "projectId": pid, "surveyNumber": no, "status": "draft", "source": "manual",
           "createdAt": _now(), "updatedAt": _now(), "is_deleted": False, "createdBy": user}
    doc.setdefault("devices", {})
    inserted = _col(COL_OPS_SURVEYS).insert_one(doc)
    sid = str(inserted.inserted_id)
    _log(user=user, action="survey.create", project_id=pid, survey_id=sid, new=no)
    return {"survey": _survey_detail({**doc, "_id": inserted.inserted_id})}


@router.get("/projects/{project_id}/change-log")
def project_change_log(project_id: str, user: str = Depends(verify_session),
                       page: int = Query(1, ge=1), pageSize: int = Query(100, ge=1, le=500)):
    _get_project(project_id)
    return _change_log_page({"projectId": str(project_id)}, page, pageSize)


# ============================================================ surveys

@router.get("/surveys/{survey_id}")
def get_survey(survey_id: str, user: str = Depends(verify_session)):
    return {"survey": _survey_detail(_get_survey(survey_id))}


@router.put("/surveys/{survey_id}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def update_survey(survey_id: str, request: Request, body: Dict[str, Any] = Body(...),
                  user: str = Depends(verify_session)):
    """Config edits touch only the ops_surveys doc, never the legacy traffic docs."""
    _ensure_indexes()
    doc = _get_survey(survey_id)
    fields = _clean_survey(body, partial=True)
    changes = {k: v for k, v in fields.items() if doc.get(k) != v}
    if changes:
        changes["updatedAt"] = _now()
        _col(COL_OPS_SURVEYS).update_one({"_id": doc["_id"]}, {"$set": changes})
        for key, v in changes.items():
            if key == "updatedAt":
                continue
            _log(user=user, action="survey.update", project_id=doc.get("projectId"), survey_id=survey_id,
                 field=key, old=doc.get(key), new=v)
    return {"survey": _survey_detail(_get_survey(survey_id))}


@router.post("/surveys/{survey_id}/status")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def set_survey_status(survey_id: str, request: Request, body: StatusBody,
                      user: str = Depends(verify_session)):
    """Survey status lives on the survey. Supplier and legacy docs are not touched."""
    _ensure_indexes()
    if body.status not in SURVEY_STATUSES:
        _bad(f"status must be one of {', '.join(SURVEY_STATUSES)}")
    doc = _get_survey(survey_id)
    old = doc.get("status") or "draft"
    _col(COL_OPS_SURVEYS).update_one({"_id": doc["_id"]},
                                     {"$set": {"status": body.status, "updatedAt": _now()}})
    _log(user=user, action="survey.status", project_id=doc.get("projectId"), survey_id=survey_id,
         field="status", old=old, new=body.status)
    return {"survey": _survey_detail(_get_survey(survey_id))}


@router.post("/surveys/{survey_id}/duplicate")
@require_permission(Permissions.OPS_PROJECT_CREATE)
def duplicate_survey(survey_id: str, request: Request, user: str = Depends(verify_session)):
    """Copies survey configuration only: new surveyNumber, status draft, NO suppliers."""
    _ensure_indexes()
    src = _get_survey(survey_id)
    skip = {"_id", "surveyNumber", "status", "createdAt", "updatedAt", "createdBy", "is_deleted",
            "deleted_at", "duplicatedFromSurveyId", "source"}
    new_doc = {k: v for k, v in src.items() if k not in skip}
    new_no = _next_survey_number()
    new_doc.update({"surveyNumber": new_no, "status": "draft", "source": "duplicate",
                    "createdAt": _now(), "updatedAt": _now(), "is_deleted": False, "createdBy": user,
                    "duplicatedFromSurveyId": str(survey_id)})
    inserted = _col(COL_OPS_SURVEYS).insert_one(new_doc)
    new_id = str(inserted.inserted_id)
    _log(user=user, action="survey.duplicate", project_id=src.get("projectId"), survey_id=new_id,
         field="duplicatedFrom", old=survey_id, new=new_id)
    return {"survey": _survey_detail({**new_doc, "_id": inserted.inserted_id})}


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

def _supplier_view(s: Dict[str, Any], status: str) -> Dict[str, Any]:
    no = s.get("surveyNo")
    return {
        "id": str(s["_id"]),
        "surveyId": s.get("surveyId"),
        "legacyProjectId": s.get("legacyProjectId"),
        "surveyNo": no,
        "needsLink": not no,
        "vendorId": s.get("vendorId"),
        "vendorName": s.get("vendorName"),
        "sourceName": s.get("sourceName"),
        "buyPrice": float(s["buyPrice"]) if s.get("buyPrice") not in (None, "") else None,
        "currency": s.get("currency", "INR"),
        "status": status,
    }


def _supplier_out(row: Dict[str, Any]) -> Dict[str, Any]:
    legacy = _legacy_docs([row.get("legacyProjectId")])
    return _supplier_view(row, _effective_status(row, legacy.get(str(row.get("legacyProjectId")))))


def _supplier_rows(sups: List[Dict[str, Any]], cutoff: datetime) -> List[Dict[str, Any]]:
    """Each participation's metrics come from its own pid only. Unlinked: zeros, loi None."""
    if not sups:
        return []
    grouped = _read_grouped(sups)
    legacy = _legacy_docs([s.get("legacyProjectId") for s in sups])
    rows = []
    for s in sups:
        no = s.get("surveyNo")
        m = _agg(grouped.get(str(no), []) if no else [], cutoff)
        view = _supplier_view(s, _effective_status(s, legacy.get(str(s.get("legacyProjectId")))))
        rows.append({**view, **{k: m[k] for k in _SUPPLIER_METRICS},
                     **_expense(m["completes"], s.get("buyPrice"))})
    return rows


def _is_active_vendor(v: Dict[str, Any]) -> bool:
    return not v.get("is_deleted") and str(v.get("status") or "").lower() not in DEAD_VENDOR_STATUSES


def _active_vendor_map(vids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for vid in set(vids):
        v = _col(COL_VENDORS).find_one({"vid": vid})
        if v and _is_active_vendor(v):
            out[vid] = v
    return out


def _resolve_legacy(vid: str, surveyNo: str, own_sid: Optional[ObjectId] = None) -> Dict[str, Any]:
    """The legacy traffic doc a participation may link to, or 422/409.
    Checks in order: doc exists and is live; its vendorId equals vid; not already
    attached to another non-removed participation (own_sid is excluded)."""
    cands = [d for d in _col(COL_PROJECTS).find({"surveyNo": {"$in": _vid_variants([surveyNo])},
                                                 "is_deleted": {"$ne": True}})
             if str(d.get("projectStatus") or "").strip().lower() != "deleted"]
    if not cands:
        _bad(f"No traffic link with surveyNo {surveyNo}")
    same = [d for d in cands if str(d.get("vendorId") or "").strip() == vid]
    if not same:
        _bad(f"Traffic link {surveyNo} belongs to vendor {cands[0].get('vendorId')}, not {vid}")
    for d in same:
        q: Dict[str, Any] = {"legacyProjectId": str(d["_id"]), "removed": {"$ne": True}}
        if own_sid is not None:
            q["_id"] = {"$ne": own_sid}
        if not _col(COL_SUPPLIERS).find_one(q):
            return d
    _conflict(f"Traffic link {surveyNo} is already attached to a supplier")


@router.get("/surveys/{survey_id}/suppliers")
def list_suppliers(survey_id: str, user: str = Depends(verify_session), window: Optional[str] = None):
    _ensure_indexes()
    cutoff = _window(window)
    survey = _get_survey(survey_id)
    project = _get_project(survey["projectId"])
    rows = _supplier_rows(_active_suppliers(survey_id), cutoff)
    if not _can_see_pricing(user):
        rows = _strip_pricing(rows)
    return {
        "project": _project_view(project, user),
        "survey": {"id": str(survey["_id"]), "surveyName": survey.get("surveyName"),
                   "surveyNo": survey.get("surveyNumber"), "surveyNumber": survey.get("surveyNumber"),
                   "status": survey.get("status") or "draft"},
        "items": rows,
        "meta": {"window": window or "p24h", "unverifiedMetrics": UNVERIFIED_METRICS,
                 "sqTermsNote": SQ_TERMS_NOTE, "inflightMinutes": _inflight_minutes()},
    }


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


def _insert_participation(survey: Dict[str, Any], vendor: Dict[str, Any], vid: str,
                          no: Optional[str], legacy: Optional[Dict[str, Any]],
                          price: Optional[Decimal], currency: str, user: str) -> Dict[str, Any]:
    sid_str = str(survey["_id"])
    lid = str(legacy["_id"]) if legacy else None
    status = _supplier_status_from_legacy(legacy.get("projectStatus")) if legacy else "live"
    fields = {"surveyId": sid_str, "legacyProjectId": lid, "surveyNo": no, "vendorId": vid,
              "vendorName": vendor.get("vendorName"), "sourceName": vendor.get("vendorType"),
              "buyPrice": str(price) if price is not None else None, "currency": currency,
              "status": status, "removed": False, "updatedAt": _now()}
    existing = None
    if lid:
        existing = _col(COL_SUPPLIERS).find_one({"surveyId": sid_str, "legacyProjectId": lid, "removed": True})
    if existing:  # previously removed from this survey: reactivate the same row
        _col(COL_SUPPLIERS).update_one({"_id": existing["_id"]}, {"$set": fields})
        sup_id = existing["_id"]
    else:
        sup_id = _col(COL_SUPPLIERS).insert_one({**fields, "createdAt": _now(), "createdBy": user}).inserted_id
    _log(user=user, action="supplier.add", project_id=survey.get("projectId"), survey_id=sid_str,
         field="vendorId", new=vid, extra={"supplierId": str(sup_id), "surveyNo": no, "legacyProjectId": lid})
    return _supplier_view({**fields, "_id": sup_id}, status)


@router.post("/surveys/{survey_id}/suppliers")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def add_suppliers(survey_id: str, request: Request, body: SupplierAdd, user: str = Depends(verify_session)):
    """vendorIds -> participations waiting for a link (needsLink). links -> participations
    attached to an existing traffic doc. Everything is validated before anything is written."""
    _ensure_indexes()
    survey = _get_survey(survey_id)
    vids = [str(v).strip() for v in (body.vendorIds or [])]
    links = [(str(item.vendorId).strip(), str(item.surveyNo).strip()) for item in (body.links or [])]
    if not vids and not links:
        _bad("Add at least one vendorId or link")
    if any(not v for v in vids):
        _bad("vendorIds must not contain empty values")
    if len(set(vids)) != len(vids):
        _bad("vendorIds contains duplicates")
    if any(not v or not n for v, n in links):
        _bad("each link needs a vendorId and a surveyNo")
    nos = [n for _, n in links]
    if len(set(nos)) != len(nos):
        _bad("surveyNo appears more than once in this request")
    if body.buyPrice is not None or body.currency is not None:
        _require_pricing(user, "Setting a supplier price")
    price = _check_price(body.buyPrice) if body.buyPrice is not None else None
    currency = _check_currency(body.currency or "INR")

    all_vids = vids + [v for v, _ in links]
    vendors = _active_vendor_map(all_vids)
    unknown = sorted({v for v in all_vids if v not in vendors})
    if unknown:
        _bad(f"Unknown or inactive vendor(s): {', '.join(unknown)}")
    resolved = [(vid, no, _resolve_legacy(vid, no)) for vid, no in links]

    out = []
    for vid, no, legacy in resolved:
        out.append(_insert_participation(survey, vendors[vid], vid, no, legacy, price, currency, user))
    for vid in vids:
        out.append(_insert_participation(survey, vendors[vid], vid, None, None, price, currency, user))
    return {"items": out}


@router.put("/survey-suppliers/{sid}/link")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def attach_supplier_link(sid: str, request: Request, body: SupplierLinkBody, user: str = Depends(verify_session)):
    """Attach (or re-attach) a traffic link to an existing participation. Same checks as add."""
    _ensure_indexes()
    doc = _get_supplier(sid)
    no = _check_name(body.surveyNo, "surveyNo", limit=32)
    vid = str(doc.get("vendorId") or "").strip()
    if not _active_vendor_map([vid]):
        _bad(f"Unknown or inactive vendor(s): {vid}")
    legacy = _resolve_legacy(vid, no, own_sid=doc["_id"])
    fields = {"legacyProjectId": str(legacy["_id"]), "surveyNo": no,
              "status": _supplier_status_from_legacy(legacy.get("projectStatus")), "updatedAt": _now()}
    _col(COL_SUPPLIERS).update_one({"_id": doc["_id"]}, {"$set": fields})
    _log(user=user, action="supplier.link", project_id=_project_of_survey(doc["surveyId"]),
         survey_id=doc["surveyId"], field="surveyNo", old=doc.get("surveyNo"), new=no,
         extra={"supplierId": sid, "legacyProjectId": fields["legacyProjectId"]})
    return {"item": _supplier_out(_get_supplier(sid))}


@router.put("/survey-suppliers/{sid}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def update_supplier(sid: str, request: Request, body: SupplierUpdate, user: str = Depends(verify_session)):
    """Status on a linked row also writes projectStatus to its legacy doc (write-through)."""
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

    legacy_doc = _legacy_docs([doc.get("legacyProjectId")]).get(str(doc.get("legacyProjectId")))
    old_status = _effective_status(doc, legacy_doc)
    if data.get("status") is not None:
        new_status = data["status"]
        if new_status not in SUPPLIER_STATUSES:
            _bad(f"status must be one of {', '.join(SUPPLIER_STATUSES)}")
        if legacy_doc is not None:
            stored = LEGACY_STATUS_WRITE.get(new_status, new_status)
            if legacy_doc.get("projectStatus") != stored:
                _col(COL_PROJECTS).update_one({"_id": legacy_doc["_id"]},
                                              {"$set": {"projectStatus": stored}})
        changes["status"] = new_status
    changes = {k: v for k, v in changes.items() if doc.get(k) != v}

    if changes:
        changes["updatedAt"] = _now()
        _col(COL_SUPPLIERS).update_one({"_id": doc["_id"]}, {"$set": changes})
        project_id = _project_of_survey(doc["surveyId"])
        for k, v in changes.items():
            if k == "updatedAt":
                continue
            wrote_legacy = k == "status" and legacy_doc is not None
            _log(user=user, action="supplier.update", project_id=project_id, survey_id=doc["surveyId"],
                 field=k, old=old_status if k == "status" else doc.get(k), new=v,
                 extra={"supplierId": sid, "legacyProjectId": doc.get("legacyProjectId") if wrote_legacy else None,
                        "legacyWrite": wrote_legacy})
    return {"item": _supplier_out(_get_supplier(sid))}


@router.delete("/survey-suppliers/{sid}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
def remove_supplier(sid: str, request: Request, user: str = Depends(verify_session)):
    """Soft remove. The vendor record and the legacy traffic doc are never touched."""
    _ensure_indexes()
    doc = _get_supplier(sid)
    _col(COL_SUPPLIERS).update_one({"_id": doc["_id"]},
                                   {"$set": {"removed": True, "removedAt": _now(), "removedBy": user}})
    _log(user=user, action="supplier.remove", project_id=_project_of_survey(doc["surveyId"]),
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


def _respondent_row(r: Dict[str, Any], include_answers: bool, pii: bool,
                    sup_of_pid: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    pid = str((r.get("params") or {}).get("pid"))
    sup = sup_of_pid.get(pid)
    row: Dict[str, Any] = {
        "respondentId": r.get("respondentId"),
        "supplier": sup.get("vendorName") if sup else None,
        "supplierSurveyNo": pid if sup else None,
        "surveyNo": pid,
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


_SUPPLIER_COLS = ["vendorId", "vendorName", "surveyNo", "entrants", "terms", "defenderTerms", "oqs", "sqTerms",
                  "abandons", "inFlights", "completes", "completesWindow", "ir", "conversion", "loi",
                  "buyPrice", "currency", "expense", "expenseBasis", "status"]
_RESPONDENT_BASE = ["respondentId", "supplier", "supplierSurveyNo", "surveyNo", "vendor", "status",
                    "createdAt", "completedAt"]


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
    parent_id = survey.get("projectId")
    sups = _active_suppliers(survey_id)
    if supplierId:
        sup = _get_supplier(supplierId)
        if str(sup.get("surveyId")) != str(survey_id):
            _not_found("Supplier not found on this survey")
        sups = [sup]
    pii = _is_admin(user)

    section_a = _supplier_rows(sups, cutoff)
    if not _can_see_pricing(user):
        section_a = _strip_pricing(section_a)
    sup_of_pid = {str(s["surveyNo"]): s for s in sups if s.get("surveyNo")}
    recs = _traffic_find(list(sup_of_pid), projection=None)
    respondents = [_respondent_row(r, includeAnswers, pii, sup_of_pid) for r in recs]
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
        return {"survey": {"id": str(survey["_id"]), "surveyNo": survey.get("surveyNumber")},
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

    filename = f"survey_{survey.get('surveyNumber')}_traffic.csv"
    return StreamingResponse(_stream(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ============================================================ search

@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=100), user: str = Depends(verify_session)):
    _ensure_indexes()
    rx = {"$regex": re.escape(q.strip()), "$options": "i"}
    projects = list(_col(COL_OPS_PROJECTS).find(
        {"is_deleted": {"$ne": True}, "$or": [{"projectName": rx}, {"projectNumber": rx}]}))[:10]
    surveys = list(_col(COL_OPS_SURVEYS).find(
        {"is_deleted": {"$ne": True}, "$or": [{"surveyName": rx}, {"surveyNumber": rx}]}))[:10]
    sups = list(_col(COL_SUPPLIERS).find(
        {"removed": {"$ne": True}, "$or": [{"vendorName": rx}, {"surveyNo": rx}]}))[:10]
    # Supplier hits need their survey's number and project: resolve both in one read each.
    sup_sids = {str(s.get("surveyId")) for s in sups if ObjectId.is_valid(str(s.get("surveyId")))}
    sup_surveys = {str(d["_id"]): d for d in _col(COL_OPS_SURVEYS).find(
        {"_id": {"$in": [ObjectId(x) for x in sup_sids]}})} if sup_sids else {}
    legacy = _legacy_docs([s.get("legacyProjectId") for s in sups])
    return {
        "projects": [{"id": str(p["_id"]), "projectName": p.get("projectName"),
                      "projectNumber": p.get("projectNumber"), "status": p.get("status")} for p in projects],
        "surveys": [{"id": str(s["_id"]), "surveyName": s.get("surveyName"),
                     "surveyNo": s.get("surveyNumber"), "surveyNumber": s.get("surveyNumber"),
                     "status": s.get("status") or "draft", "parentProjectId": s.get("projectId")}
                    for s in surveys],
        "suppliers": [{"id": str(s["_id"]), "surveyId": s.get("surveyId"),
                       "surveyNo": s.get("surveyNo"),
                       "surveyNumber": (sup_surveys.get(str(s.get("surveyId"))) or {}).get("surveyNumber"),
                       "parentProjectId": (sup_surveys.get(str(s.get("surveyId"))) or {}).get("projectId"),
                       "vendorId": s.get("vendorId"), "vendorName": s.get("vendorName"),
                       "status": _effective_status(s, legacy.get(str(s.get("legacyProjectId"))))}
                      for s in sups],
    }


@router.get("/surveys/{survey_id}/test-link")
def survey_test_link(survey_id: str, user: str = Depends(verify_session)):
    """The survey's stored surveyUrl, unchanged, if it is a valid http(s) URL.
    Read-only: writes nothing and records no traffic."""
    doc = _get_survey(survey_id)
    raw = doc.get("surveyUrl")
    if isinstance(raw, str):
        p = urlparse(raw)
        if p.scheme in ("http", "https") and p.netloc:
            return {"url": raw}
    _not_found("No survey URL set")
