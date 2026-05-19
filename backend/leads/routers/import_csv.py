"""
CSV / Google Sheets / JSON import and Classification routes
extracted from leads/router.py (Phase 12c).
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from ..ingestion import import_from_google_sheet, parse_csv_leads
from ..models import (
    LeadClassifyRequest,
    LeadClassifyResponse,
    LeadImportRequest,
    LeadImportResponse,
    LeadInput,
)
from ..router_shared import (
    GoogleSheetRequest,
    JobStatus,
    _jobs_db,
    add_job_error,
    update_job,
    web_search_jobs_collection,
)
from ..service import (
    classify_pending_leads,
    classify_single_lead,
    import_leads,
)

# ---------------------------------------------------------------------------
# Module-level setup (runs once on import)
# ---------------------------------------------------------------------------

csv_mappings_collection = _jobs_db["csv_column_mappings"]
try:
    csv_mappings_collection.create_index("columns_hash", unique=True)
except Exception as e:
    print(f"Warning: Could not create csv mappings index: {e}")

_CSV_SYNC_THRESHOLD = 200  # rows — below this, process inline; above, run as background job


class CSVMappingSaveRequest(BaseModel):
    """Request to save a CSV column mapping"""
    filename: Optional[str] = None
    mapping: dict
    columns: List[str]


def _process_csv_import_bg(job_id: str, lead_dicts: list):
    """Background worker: import CSV leads in batches, updating job progress."""
    BATCH = 200
    total = len(lead_dicts)
    imported_count = 0
    duplicates_count = 0

    try:
        update_job(job_id, {"status": JobStatus.RUNNING, "started_at": datetime.utcnow()})

        for i in range(0, total, BATCH):
            batch_dicts = lead_dicts[i:i + BATCH]
            try:
                lead_inputs = [LeadInput(**d) for d in batch_dicts]
                result = import_leads(lead_inputs)
                imported_count += result.imported
                duplicates_count += result.duplicates
            except Exception as e:
                add_job_error(job_id, f"Batch {i // BATCH + 1} error: {str(e)}")

            web_search_jobs_collection.update_one(
                {"job_id": job_id},
                {"$set": {
                    "total_found": i + len(batch_dicts),
                    "total_imported": imported_count,
                    "total_duplicates": duplicates_count,
                    "last_update": datetime.utcnow()
                }}
            )

        update_job(job_id, {
            "status": JobStatus.COMPLETED,
            "total_imported": imported_count,
            "total_duplicates": duplicates_count,
            "completed_at": datetime.utcnow()
        })
    except Exception as e:
        update_job(job_id, {"status": "failed"})
        add_job_error(job_id, f"Fatal error: {str(e)}")


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_import_routes(router: APIRouter) -> None:

    # ── CSV mapping ────────────────────────────────────────────────────────

    @router.post("/import/csv/mapping")
    async def save_csv_mapping(request: CSVMappingSaveRequest):
        """
        POST /leads/import/csv/mapping
        Save a CSV column mapping for future use.
        The mapping is keyed by a hash of the sorted column names.
        """
        try:
            sorted_columns = sorted([c.lower().strip() for c in request.columns])
            columns_hash = hash(tuple(sorted_columns))

            mapping_doc = {
                "columns_hash": str(columns_hash),
                "columns": request.columns,
                "mapping": request.mapping,
                "filename": request.filename,
                "updated_at": datetime.utcnow()
            }

            csv_mappings_collection.update_one(
                {"columns_hash": str(columns_hash)},
                {"$set": mapping_doc},
                upsert=True
            )

            return {"success": True, "message": "Mapping saved for future use"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/import/csv/mapping")
    async def get_csv_mapping(columns: str = Query(..., description="Comma-separated list of CSV columns")):
        """
        GET /leads/import/csv/mapping?columns=col1,col2,col3
        Get a saved CSV column mapping based on the column names.
        Returns the best matching saved mapping.
        """
        try:
            column_list = [c.strip() for c in columns.split(",") if c.strip()]
            sorted_columns = sorted([c.lower() for c in column_list])
            columns_hash = hash(tuple(sorted_columns))

            mapping = csv_mappings_collection.find_one({"columns_hash": str(columns_hash)})

            if mapping:
                return {
                    "found": True,
                    "mapping": mapping.get("mapping", {}),
                    "filename": mapping.get("filename"),
                    "updated_at": mapping.get("updated_at")
                }

            all_mappings = list(csv_mappings_collection.find().sort("updated_at", -1).limit(10))

            best_match = None
            best_score = 0

            for m in all_mappings:
                saved_cols = set([c.lower() for c in m.get("columns", [])])
                current_cols = set(sorted_columns)
                overlap = len(saved_cols.intersection(current_cols))
                score = overlap / max(len(saved_cols), len(current_cols), 1)

                if score > 0.5 and score > best_score:
                    best_match = m
                    best_score = score

            if best_match:
                return {
                    "found": True,
                    "mapping": best_match.get("mapping", {}),
                    "filename": best_match.get("filename"),
                    "partial_match": True,
                    "match_score": best_score
                }

            return {"found": False, "mapping": None}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── CSV import ─────────────────────────────────────────────────────────

    @router.get("/import/csv/status/{job_id}")
    async def get_csv_import_status(job_id: str):
        """GET /leads/import/csv/status/{job_id} — poll progress of a CSV import job."""
        job = web_search_jobs_collection.find_one({"job_id": job_id, "job_type": "csv_import"})
        if not job:
            raise HTTPException(status_code=404, detail="CSV import job not found")
        target = max(job.get("target_count", 1), 1)
        processed = job.get("total_imported", 0) + job.get("total_duplicates", 0)
        return {
            "job_id": job_id,
            "status": job.get("status"),
            "total": job.get("target_count", 0),
            "total_imported": job.get("total_imported", 0),
            "total_duplicates": job.get("total_duplicates", 0),
            "progress_percent": round(processed / target * 100),
            "errors": job.get("errors", []),
        }

    @router.post("/import/csv")
    async def import_from_csv(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        delimiter: str = Form(",")
    ):
        """
        POST /leads/import/csv
        Upload a CSV file containing leads.
        Expected columns: name, title, linkedin_url, snippet
        Small files (≤200 rows) are processed synchronously.
        Larger files are processed as a background job; the response includes a job_id
        that the client can poll via GET /leads/import/csv/status/{job_id}.
        """
        try:
            content = await file.read()
            max_upload_bytes = 500 * 1024 * 1024
            if len(content) > max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="CSV file is too large. Max allowed size is 500MB."
                )
            csv_content = content.decode("utf-8")

            leads = parse_csv_leads(csv_content, delimiter)

            if not leads:
                return {"imported": 0, "message": "No valid leads found in CSV"}

            if len(leads) <= _CSV_SYNC_THRESHOLD:
                lead_inputs = [LeadInput(**lead) for lead in leads]
                result = import_leads(lead_inputs)
                return {
                    "parsed": len(leads),
                    "imported": result.imported,
                    "duplicates": result.duplicates,
                    "errors": result.errors,
                    "message": f"Parsed {len(leads)} leads from CSV, imported {result.imported}"
                }

            job_id = str(uuid.uuid4())[:8]
            job_doc = {
                "job_id": job_id,
                "job_type": "csv_import",
                "status": JobStatus.PENDING,
                "config": {"filename": file.filename or "upload.csv", "total": len(leads)},
                "target_count": len(leads),
                "total_found": len(leads),
                "total_imported": 0,
                "total_duplicates": 0,
                "total_classified": 0,
                "emails_found": 0,
                "leads_today": 0,
                "queries_used": 0,
                "current_query": "",
                "query_combinations": [],
                "seen_urls": [],
                "errors": [],
                "created_at": datetime.utcnow(),
                "started_at": None,
                "last_update": None,
                "completed_at": None,
                "day_started": datetime.utcnow().date().isoformat()
            }
            web_search_jobs_collection.insert_one(job_doc)
            background_tasks.add_task(_process_csv_import_bg, job_id, leads)

            return {
                "success": True,
                "job_id": job_id,
                "total": len(leads),
                "message": f"Processing {len(leads)} leads in background. Poll /leads/import/csv/status/{job_id} for progress."
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Google Sheets ──────────────────────────────────────────────────────

    @router.post("/import/google-sheets")
    async def import_from_google_sheets(request: GoogleSheetRequest):
        """
        POST /leads/import/google-sheets
        Import leads from a public Google Sheet.
        Sheet must be set to "Anyone with link can view".
        """
        try:
            leads = await import_from_google_sheet(
                spreadsheet_id=request.spreadsheet_id,
                sheet_name=request.sheet_name,
                range_notation=request.range_notation
            )

            if not leads:
                return {"imported": 0, "message": "No valid leads found in sheet"}

            lead_inputs = [LeadInput(**lead) for lead in leads]
            result = import_leads(lead_inputs)

            return {
                "parsed": len(leads),
                "imported": result.imported,
                "duplicates": result.duplicates,
                "message": f"Imported {result.imported} leads from Google Sheet"
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── JSON import ────────────────────────────────────────────────────────

    @router.post("/import", response_model=LeadImportResponse)
    async def import_leads_endpoint(request: LeadImportRequest):
        """
        POST /leads/import
        Import LinkedIn leads with idempotent behavior.
        Duplicates are detected by linkedin_url and skipped.
        """
        try:
            result = import_leads(request.leads)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Classification ─────────────────────────────────────────────────────

    @router.post("/classify", response_model=LeadClassifyResponse)
    async def classify_leads_endpoint(
        request: LeadClassifyRequest,
        background_tasks: BackgroundTasks
    ):
        """
        POST /leads/classify
        Queue leads for AI classification (async).
        If lead_ids not provided, classifies all pending leads.
        If batch_size is None, classifies ALL pending leads.
        """
        if request.lead_ids:
            for lead_id in request.lead_ids:
                background_tasks.add_task(classify_single_lead, lead_id)
            return LeadClassifyResponse(
                queued=len(request.lead_ids),
                message=f"Queued {len(request.lead_ids)} leads for classification"
            )
        else:
            background_tasks.add_task(classify_pending_leads, request.batch_size)
            if request.batch_size:
                return LeadClassifyResponse(
                    queued=request.batch_size,
                    message=f"Queued up to {request.batch_size} pending leads for classification"
                )
            else:
                return LeadClassifyResponse(
                    queued=0,
                    message="Queued ALL pending leads for classification"
                )

    @router.post("/classify/{lead_id}")
    async def classify_single_lead_endpoint(lead_id: str):
        """
        POST /leads/classify/{lead_id}
        Classify a single lead synchronously.
        """
        success, error = classify_single_lead(lead_id)
        if success:
            return {"status": "classified", "lead_id": lead_id}
        else:
            raise HTTPException(status_code=400, detail=error or "Classification failed")
