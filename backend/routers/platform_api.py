"""Shared-platform API (CRM plan 3.1): config, the one Review Queue, failed AI jobs.

Every endpoint requires a logged-in session (session_state.verify_session as a
dependency, so it is enforced whatever AUTH_GUARD_MODE says) and every change
is audit-logged under the user's name.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from session_state import verify_session
from app.security import require

require_approve = require("approve")

try:      # confirmed Zoho customer -> account alias applies to all that customer's invoices
    from backfill.zoho_link import apply_confirmed_alias
    review_queue.register_handler("zoho_alias", apply_confirmed_alias)
except Exception:   # pragma: no cover
    pass
from platform_core import config_store, qwen_gateway, review_queue

router = APIRouter(prefix="/api/platform", tags=["platform"])


# ------------------------------------------------------------------ config
@router.get("/config")
async def list_config(user: str = Depends(verify_session)) -> Dict[str, Any]:
    return {name: config_store.get(name) for name in config_store.SECTIONS}


@router.get("/config/{section}")
async def get_config(section: str, user: str = Depends(verify_session)) -> Dict[str, Any]:
    try:
        return {"section": section, "values": config_store.get(section), "defaults": config_store.defaults(section)}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.put("/config/{section}")
async def put_config(section: str, values: Dict[str, Any] = Body(...), user: str = Depends(require_approve)):
    """Config changes -- including a module's mode (sandbox/shadow/live) -- need
    the approve capability (owner/admin) once RBAC is on; audit-logged."""
    try:
        return {"section": section, "values": config_store.set(section, values, actor=user)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/shadow-report")
async def shadow_report(hours: int = Query(24, ge=1, le=24 * 14), user: str = Depends(verify_session)):
    """Phase 5: what every module would have done in the window (masked)."""
    from database import get_database
    from platform_core import shadow_report as sr
    return sr.build(get_database, hours)


# ------------------------------------------------------------ review queue
@router.get("/review-queue")
async def review_items(status: str = "pending", module: Optional[str] = None, type: Optional[str] = None,
                       bu: Optional[str] = None, limit: int = Query(200, le=1000),
                       user: str = Depends(verify_session)):
    return {"items": review_queue.list_items(status, module, type, bu, limit), "counts": review_queue.counts()}


@router.post("/review-queue/{item_id}/{action}")
async def review_resolve(item_id: str, action: str, body: Dict[str, Any] = Body(default={}),
                         user: str = Depends(verify_session)):
    try:
        return review_queue.resolve(item_id, action, actor=user, correction=body.get("correction"),
                                    assignee=body.get("assignee"), note=body.get("note", ""))
    except KeyError:
        raise HTTPException(404, "review item not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------- AI jobs
@router.get("/ai/failed-jobs")
async def ai_failed_jobs(limit: int = Query(100, le=500), user: str = Depends(verify_session)):
    return {"jobs": qwen_gateway.failed_jobs(limit)}


@router.post("/ai/failed-jobs/{job_id}/retry")
async def ai_retry(job_id: str, user: str = Depends(verify_session)):
    return qwen_gateway.retry_failed(job_id)
