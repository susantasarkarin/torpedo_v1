"""
Vendor Service
==============
Business logic for vendor and project lifecycle management,
including safety-gated soft-deletes and unique ID generation.

Extracted from routers/legacy_vendors_projects.py (Phase 10).
Updated Phase 13: all DB access delegated to vendor_repo.
"""

import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException

try:
    from .utils import validate_redirect_url
    from .repositories import vendor_repo
except ImportError:
    from utils import validate_redirect_url
    from repositories import vendor_repo

logger = logging.getLogger(__name__)


def generate_vid() -> str:
    """Generate a unique 4-digit vendor ID (VID)."""
    while True:
        vid = str(datetime.utcnow().microsecond % 10000).zfill(4)
        if not vendor_repo.find_vendor_by_vid(vid):
            return vid


def generate_survey_no() -> str:
    """Generate a unique 5-digit survey number."""
    while True:
        survey_no = str(datetime.utcnow().microsecond % 100000).zfill(5)
        if not vendor_repo.find_project_by_survey_no(survey_no):
            return survey_no


def validate_vendor_redirect_urls(vendor_data: Dict[str, Any]) -> None:
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


def create_vendor(vendor_data: Dict[str, Any]) -> Dict[str, Any]:
    validate_vendor_redirect_urls(vendor_data)
    vendor_data["vid"] = generate_vid()
    result = vendor_repo.insert_vendor(vendor_data)
    vendor_data["_id"] = str(result.inserted_id)
    logger.info("Vendor created: %s (vid=%s)", vendor_data.get("vendorName"), vendor_data["vid"])
    return vendor_data


def update_vendor(vendor_id: str, vendor_data: Dict[str, Any]) -> None:
    validate_vendor_redirect_urls(vendor_data)
    result = vendor_repo.update_vendor_by_id(vendor_id, vendor_data)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")


def delete_vendor_safe(vendor_id: str) -> None:
    vendor = vendor_repo.find_vendor_by_id(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    vid = vendor.get("vid")
    if vid:
        traffic_count = vendor_repo.count_traffic_for_vid(vid)
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
    vendor_repo.soft_delete_vendor(vendor_id)
    logger.info("Vendor %s soft-deleted", vendor_id)


def create_project(project_data: Dict[str, Any]) -> Dict[str, Any]:
    project_data["surveyNo"] = generate_survey_no()
    project_data["createdAt"] = datetime.utcnow()
    result = vendor_repo.insert_project(project_data)
    project_data["_id"] = str(result.inserted_id)
    logger.info("Project created: %s (surveyNo=%s)", project_data.get("projectName"), project_data["surveyNo"])
    return project_data


def update_project(project_id: str, project_data: Dict[str, Any]) -> None:
    result = vendor_repo.update_project_by_id(project_id, project_data)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")


def delete_project_safe(project_id: str) -> None:
    project = vendor_repo.find_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for collection_name in ("invoices", "bills", "expenses"):
        count = vendor_repo.count_linked_finance_records(project_id, collection_name)
        if count:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete project with {count} linked {collection_name}. Delete or unlink them first.",
            )
    vendor_repo.soft_delete_project(project_id)
    logger.info("Project %s soft-deleted", project_id)
