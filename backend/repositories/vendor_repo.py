"""
Vendor Repository
=================
All MongoDB access for vendors, projects, and related finance/traffic collections.
Services call these methods; they never touch PyMongo directly.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from database import get_client, get_database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy collection accessors
# ---------------------------------------------------------------------------

_db = None
_traffic_db = None
_url_parameters_col = None


def _get_db():
    global _db
    if _db is None:
        _db = get_database("email_automation")
    return _db


def _get_url_parameters_col():
    global _traffic_db, _url_parameters_col
    if _traffic_db is None:
        try:
            client = get_client()
            _traffic_db = client["traffic_flow_db"]
            _url_parameters_col = _traffic_db["url_parameters"]
        except Exception as e:
            logger.warning("traffic_flow_db not available: %s", e)
            _url_parameters_col = None
    return _url_parameters_col


def _vendors():
    return _get_db()["vendors"]


def _projects():
    return _get_db()["projects"]


def _finance_db():
    return get_client()["finance_db"]


# ---------------------------------------------------------------------------
# Vendor queries
# ---------------------------------------------------------------------------

def find_vendor_by_id(vendor_id: str) -> Optional[Dict[str, Any]]:
    return _vendors().find_one({"_id": ObjectId(vendor_id)})


def find_vendor_by_vid(vid: str) -> Optional[Dict[str, Any]]:
    return _vendors().find_one({"vid": vid})


def list_vendors() -> List[Dict[str, Any]]:
    docs = list(_vendors().find())
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def insert_vendor(vendor_data: Dict[str, Any]) -> Any:
    return _vendors().insert_one(vendor_data)


def update_vendor_by_id(vendor_id: str, update_data: Dict[str, Any]) -> Any:
    return _vendors().update_one({"_id": ObjectId(vendor_id)}, {"$set": update_data})


def soft_delete_vendor(vendor_id: str) -> None:
    _vendors().update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "status": "deleted"}},
    )


def count_traffic_for_vid(vid: str) -> int:
    col = _get_url_parameters_col()
    if col is None:
        return 0
    return col.count_documents({"vendorId": vid})


# ---------------------------------------------------------------------------
# Project queries
# ---------------------------------------------------------------------------

def find_project_by_id(project_id: str) -> Optional[Dict[str, Any]]:
    return _projects().find_one({"_id": ObjectId(project_id)})


def find_project_by_survey_no(survey_no: str) -> Optional[Dict[str, Any]]:
    return _projects().find_one({"surveyNo": survey_no})


def list_projects() -> List[Dict[str, Any]]:
    docs = list(_projects().find({"is_deleted": {"$ne": True}}))
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def insert_project(project_data: Dict[str, Any]) -> Any:
    return _projects().insert_one(project_data)


def update_project_by_id(project_id: str, update_data: Dict[str, Any]) -> Any:
    return _projects().update_one({"_id": ObjectId(project_id)}, {"$set": update_data})


def soft_delete_project(project_id: str) -> None:
    _projects().update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "projectStatus": "Deleted"}},
    )


# ---------------------------------------------------------------------------
# Finance linked-record queries (used by delete_project_safe)
# ---------------------------------------------------------------------------

def count_linked_finance_records(project_id: str, collection_name: str) -> int:
    live_filter = {"project_id": project_id, "is_deleted": {"$ne": True}}
    return _finance_db()[collection_name].count_documents(live_filter)
