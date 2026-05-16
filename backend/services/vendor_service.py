"""
Vendor Service
==============
Business logic for vendor and project lifecycle management,
including safety-gated soft-deletes and unique ID generation.

Extracted from routers/legacy_vendors_projects.py (Phase 10).
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import HTTPException

try:
    from .utils import validate_redirect_url
except ImportError:
    from utils import validate_redirect_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unique ID generation
# ---------------------------------------------------------------------------

def generate_vid(vendors_col: Any) -> str:
    """
    Generate a unique 4-digit vendor ID (VID).
    Poll-loops until a non-colliding value is found.
    Thread-safe at the DB level (find_one is atomic).

    WARNING: Under high concurrent load (many simultaneous vendor creations)
    this may loop longer. Acceptable at current scale.
    """
    while True:
        vid = str(datetime.utcnow().microsecond % 10000).zfill(4)
        if not vendors_col.find_one({"vid": vid}):
            return vid


def generate_survey_no(projects_col: Any) -> str:
    """
    Generate a unique 5-digit survey number.
    Same loop pattern as generate_vid.
    """
    while True:
        survey_no = str(datetime.utcnow().microsecond % 100000).zfill(5)
        if not projects_col.find_one({"surveyNo": survey_no}):
            return survey_no


# ---------------------------------------------------------------------------
# Redirect URL validation
# ---------------------------------------------------------------------------

def validate_vendor_redirect_urls(vendor_data: Dict[str, Any]) -> None:
    """
    Validate completeRD / terminateRD / quotaRD redirect URLs.
    Raises HTTP 400 on the first invalid URL.
    """
    for url_field in ["completeRD", "terminateRD", "quotaRD"]:
        urls = vendor_data.get(url_field, [])
        if not urls:
            continue
        url_list = urls if isinstance(urls, list) else [urls]
        for url in url_list:
            if url and url.strip():
                is_valid, error_msg = validate_redirect_url(url.strip(), require_https=False)
                if not is_valid:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid {url_field} URL: {error_msg}",
                    )


# ---------------------------------------------------------------------------
# Vendor operations
# ---------------------------------------------------------------------------

def create_vendor(
    vendor_data: Dict[str, Any],
    vendors_col: Any,
) -> Dict[str, Any]:
    """
    Validate, assign VID, and persist a new vendor.
    Returns the inserted vendor dict with _id as string.
    """
    validate_vendor_redirect_urls(vendor_data)
    vendor_data["vid"] = generate_vid(vendors_col)
    result = vendors_col.insert_one(vendor_data)
    vendor_data["_id"] = str(result.inserted_id)
    logger.info("Vendor created: %s (vid=%s)", vendor_data.get("vendorName"), vendor_data["vid"])
    return vendor_data


def delete_vendor_safe(
    vendor_id: str,
    vendors_col: Any,
    url_parameters_col: Optional[Any],
) -> None:
    """
    Safety-gated soft delete for a vendor.

    Blocks if:
      - vendor has live traffic records in traffic_flow_db.url_parameters
      - vendor is linked to a billing vendor

    Raises HTTP 404/400 on guard failures.
    """
    vendor = vendors_col.find_one({"_id": ObjectId(vendor_id)})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    if url_parameters_col is not None:
        vid = vendor.get("vid")
        if vid:
            traffic_count = url_parameters_col.count_documents({"vendorId": vid})
            if traffic_count > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete vendor with {traffic_count} traffic records. Archive instead.",
                )

    if vendor.get("linked_billing_vendor_id"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete vendor linked to billing vendor (ID: {vendor['linked_billing_vendor_id']}). Unlink first.",
        )

    vendors_col.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "status": "deleted"}},
    )
    logger.info("Vendor %s soft-deleted", vendor_id)


# ---------------------------------------------------------------------------
# Project operations
# ---------------------------------------------------------------------------

def create_project(
    project_data: Dict[str, Any],
    projects_col: Any,
) -> Dict[str, Any]:
    """
    Assign a unique surveyNo and persist a new project.
    Returns the inserted project dict with _id as string.
    """
    project_data["surveyNo"] = generate_survey_no(projects_col)
    project_data["createdAt"] = datetime.utcnow()
    result = projects_col.insert_one(project_data)
    project_data["_id"] = str(result.inserted_id)
    logger.info("Project created: %s (surveyNo=%s)", project_data.get("projectName"), project_data["surveyNo"])
    return project_data


def delete_project_safe(
    project_id: str,
    projects_col: Any,
    finance_client: Any,
) -> None:
    """
    Cascade-validate and soft-delete a project.

    Blocks if any non-deleted invoices/bills/expenses are linked.
    Raises HTTP 404/400 on guard failures.

    finance_client is a MongoClient instance used to access finance_db.
    """
    project = projects_col.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    finance_db = finance_client["finance_db"]
    live_filter = {"project_id": project_id, "is_deleted": {"$ne": True}}

    linked_invoices = finance_db["invoices"].count_documents(live_filter)
    if linked_invoices:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete project with {linked_invoices} linked invoice(s). Delete or unlink invoices first.",
        )

    linked_bills = finance_db["bills"].count_documents(live_filter)
    if linked_bills:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete project with {linked_bills} linked bill(s). Delete or unlink bills first.",
        )

    linked_expenses = finance_db["expenses"].count_documents(live_filter)
    if linked_expenses:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete project with {linked_expenses} linked expense(s). Delete or unlink expenses first.",
        )

    projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "projectStatus": "Deleted"}},
    )
    logger.info("Project %s soft-deleted", project_id)
