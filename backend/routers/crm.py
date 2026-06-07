"""
CRM SPINE ROUTER  (/api/crm/*)

Clean canonical CRM API layer. Does NOT replace legacy routes (sales_accounts,
leads, finance, ...) — those stay untouched. This is the new unified surface
that modules and AI agents link through.

Generic CRUD is exposed per canonical collection, plus the cross-object flows
(timeline, RFQ, opportunity-won). Create payloads are validated against the
canonical Pydantic models in app/models/crm_objects.py.
"""

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from typing import Optional, Dict, Any

try:
    from ..app.services import crm_service
    from ..app.models import crm_objects
    from ..app.security import require
except ImportError:  # pragma: no cover - absolute import fallback
    from app.services import crm_service
    from app.models import crm_objects
    from app.security import require

router = APIRouter(prefix="/api/crm", tags=["CRM Spine"])

# Coarse capability gates (enforced only when RBAC_ENABLED=true).
require_read = require("read")
require_write = require("write")

# Map a URL resource to its canonical Pydantic model for create-time validation.
_MODELS = {
    "accounts": crm_objects.Account,
    "contacts": crm_objects.Contact,
    "leads": crm_objects.Lead,
    "opportunities": crm_objects.Opportunity,
    "activities": crm_objects.Activity,
    "tasks": crm_objects.Task,
    "projects": crm_objects.Project,
    "invoices": crm_objects.Invoice,
    "ai_decisions": crm_objects.AIDecision,
}


def _check_resource(resource: str):
    if resource not in crm_service.COLLECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown CRM resource: {resource}")


# ----------------------- cross-object flows (specific first) -----------------------

@router.get("/timeline/{object_type}/{object_id}")
async def get_timeline(object_type: str, object_id: str, _user: str = Depends(require_read)):
    """Activities + tasks linked to one canonical object (account/contact/opportunity/project)."""
    try:
        return crm_service.timeline(object_type, object_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rfq")
async def create_rfq(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_write)):
    """RFQ -> creates an Opportunity and a Project stub, cross-linked."""
    return crm_service.create_rfq(payload)


@router.post("/opportunities/{opp_id}/win")
async def win_opportunity(opp_id: str, _user: str = Depends(require_write)):
    """Mark Opportunity Won -> activate Project and create Invoice stub."""
    result = crm_service.mark_opportunity_won(opp_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return result


# ------------------------------- generic CRUD -------------------------------

@router.get("/{resource}")
async def list_resource(
    resource: str,
    limit: int = Query(200, le=1000),
    skip: int = Query(0, ge=0),
    _user: str = Depends(require_read),
):
    _check_resource(resource)
    return crm_service.list_docs(resource, limit=limit, skip=skip)


@router.post("/{resource}")
async def create_resource(
    resource: str,
    payload: Dict[str, Any] = Body(...),
    _user: str = Depends(require_write),
):
    _check_resource(resource)
    model = _MODELS.get(resource)
    try:
        # Validate + coerce against the canonical schema, dropping unset fields.
        data = model(**payload).model_dump(exclude_none=True) if model else payload
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return crm_service.create(resource, data)


@router.get("/{resource}/{doc_id}")
async def get_resource(resource: str, doc_id: str, _user: str = Depends(require_read)):
    _check_resource(resource)
    try:
        doc = crm_service.get(resource, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not doc:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return doc


@router.put("/{resource}/{doc_id}")
async def update_resource(
    resource: str,
    doc_id: str,
    payload: Dict[str, Any] = Body(...),
    _user: str = Depends(require_write),
):
    _check_resource(resource)
    try:
        doc = crm_service.update(resource, doc_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not doc:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return doc


@router.delete("/{resource}/{doc_id}")
async def delete_resource(resource: str, doc_id: str, _user: str = Depends(require_write)):
    _check_resource(resource)
    try:
        ok = crm_service.delete(resource, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return {"message": "deleted"}
