"""
Legacy Leads Routes
===================
Basic leads CRUD (create, get-by-id, update, delete, bulk-delete,
move-to-contacts, CSV import).

The paginated GET /leads/ list endpoint lives in leads/router.py —
these routes are the individual-record and import operations.
Extracted from main.py to keep the app entry-point lean.
"""

import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile

try:
    from .session_state import verify_session
except ImportError:
    from session_state import verify_session

try:
    from .database import get_database
except ImportError:
    from database import get_database

try:
    from .services import lead_service
except ImportError:
    from services import lead_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-leads"])

# ---------------------------------------------------------------------------
# Lazy accessors
# ---------------------------------------------------------------------------
_db = None


def _get_db():
    global _db
    if _db is None:
        _db = get_database("email_automation")
    return _db


def _leads():
    return _get_db()["leads"]


def _contacts():
    return _get_db()["contacts"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/leads/")
async def create_lead(lead_data: Dict[str, Any] = Body(...)):
    try:
        if not lead_data.get("email") or not lead_data["email"].strip():
            raise HTTPException(status_code=400, detail="Email is required")
        lead_data["addedOn"] = datetime.utcnow()
        lead_data["createdAt"] = datetime.utcnow()
        lead_data["updatedAt"] = datetime.utcnow()
        result = _leads().insert_one(lead_data)
        lead_data["_id"] = str(result.inserted_id)
        return {"message": "Lead created successfully", "lead": lead_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lead creation error: {str(e)}")


@router.get("/leads/{lead_id}", dependencies=[Depends(verify_session)])
async def get_lead(lead_id: str):
    try:
        lead = _leads().find_one({"_id": ObjectId(lead_id)})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead["_id"] = str(lead["_id"])
        for date_field in ["createdAt", "updatedAt", "addedOn"]:
            if date_field in lead:
                lead[date_field] = lead[date_field].isoformat() if isinstance(lead[date_field], datetime) else str(lead[date_field])
        return {"lead": lead}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch lead error: {str(e)}")


@router.put("/leads/{lead_id}")
async def update_lead(lead_id: str, lead_data: Dict[str, Any] = Body(...)):
    try:
        lead_data = {k: v for k, v in lead_data.items() if k not in ["_id", "createdAt", "addedOn"]}
        if "email" in lead_data and (not lead_data["email"] or not lead_data["email"].strip()):
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        lead_data["updatedAt"] = datetime.utcnow()
        result = _leads().update_one({"_id": ObjectId(lead_id)}, {"$set": lead_data})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"message": "Lead updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lead update error: {str(e)}")


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: str):
    try:
        result = _leads().delete_one({"_id": ObjectId(lead_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"message": "Lead deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lead delete error: {str(e)}")


@router.post("/leads/bulk-delete")
async def bulk_delete_leads(data: Dict[str, Any] = Body(...)):
    try:
        ids = data.get("ids", [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        object_ids = [ObjectId(id) for id in ids]
        result = _leads().delete_many({"_id": {"$in": object_ids}})
        return {"message": f"Successfully deleted {result.deleted_count} leads", "deleted_count": result.deleted_count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk delete error: {str(e)}")


@router.post("/leads/{lead_id}/move-to-contacts")
async def move_lead_to_contacts(lead_id: str, stage_data: Dict[str, Any] = Body(...)):
    try:
        contact = lead_service.move_lead_to_contacts(
            lead_id,
            stage_data.get("stage", "RFQ"),
            _leads(),
            _contacts(),
        )
        if contact is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"message": "Lead moved to contacts successfully", "contact": contact}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Move lead error: {str(e)}")


@router.post("/leads/import/csv")
async def import_leads_csv(file: UploadFile = File(...)):
    """Import leads from a CSV file using the canonical ingestion pipeline."""
    try:
        from leads.canonical_ingestion import ingest_lead  # type: ignore

        content = await file.read()
        decoded = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))

        results: Dict[str, Any] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}

        for row_num, row in enumerate(reader, start=2):
            try:
                if not any(row.values()):
                    results["skipped"] += 1
                    continue
                payload = {
                    "email": row.get("email", "").strip(),
                    "name": row.get("name", "").strip() or f"{row.get('firstName', '')} {row.get('lastName', '')}".strip(),
                    "first_name": row.get("firstName", "").strip(),
                    "last_name": row.get("lastName", "").strip(),
                    "title": row.get("title", "").strip(),
                    "linkedin_url": row.get("linkedin", "").strip(),
                    "location": row.get("location", "").strip(),
                    "company": row.get("companyName", "").strip(),
                    "company_domain": row.get("companyDomain", "").strip(),
                    "phone": row.get("phone", "").strip(),
                }
                result = ingest_lead(payload=payload, source="csv", source_detail=f"csv_import:{file.filename}", skip_classification=True)
                if result["success"]:
                    if result["action"] == "inserted":
                        results["inserted"] += 1
                    elif result["action"] == "updated":
                        results["updated"] += 1
                    else:
                        results["skipped"] += 1
                else:
                    results["skipped"] += 1
                    if result.get("error"):
                        results["errors"].append(f"Row {row_num}: {result['error']}")
            except Exception as e:
                results["skipped"] += 1
                results["errors"].append(f"Row {row_num}: {str(e)}")

        return {
            "message": f"Import completed: {results['inserted']} inserted, {results['updated']} updated, {results['skipped']} skipped",
            "inserted": results["inserted"],
            "updated": results["updated"],
            "skipped": results["skipped"],
            "errors": results["errors"][:20],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV import error: {str(e)}")
