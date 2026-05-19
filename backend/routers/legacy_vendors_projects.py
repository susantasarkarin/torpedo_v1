"""
Legacy Vendors & Projects Routes
=================================
Vendor CRUD + Project CRUD without the /api/ prefix.
These routes pre-date the /api/vendors and /api/projects routers.
Extracted from main.py to keep the app entry-point lean.
"""

import asyncio
import logging
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

try:
    from .session_state import verify_session
except ImportError:
    from session_state import verify_session

try:
    from .services import vendor_service
except ImportError:
    from services import vendor_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-vendors-projects"])



# ---------------------------------------------------------------------------
# Vendor routes
# ---------------------------------------------------------------------------

@router.post("/vendors/")
async def create_vendor(vendor_data: Dict[str, Any] = Body(...)):
    try:
        if not vendor_data.get("vendorName") or not vendor_data["vendorName"].strip():
            raise HTTPException(status_code=400, detail="Vendor name is required")
        if not vendor_data.get("vendorVariable") or not vendor_data["vendorVariable"].strip():
            raise HTTPException(status_code=400, detail="Vendor Variable is required")
        if not vendor_data.get("vendorType") or not vendor_data["vendorType"].strip():
            raise HTTPException(status_code=400, detail="Vendor Type is required")
        if not vendor_data.get("status") or not vendor_data["status"].strip():
            raise HTTPException(status_code=400, detail="Status is required")
        result = vendor_service.create_vendor(vendor_data)
        return {"message": "Vendor created successfully", "vendor": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor creation error: {str(e)}")


@router.get("/vendors/", dependencies=[Depends(verify_session)])
async def get_vendors():
    try:
        from repositories import vendor_repo
        vendors = vendor_repo.list_vendors()
        return {"vendors": vendors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch vendors error: {str(e)}")


@router.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, vendor_data: Dict[str, Any] = Body(...)):
    try:
        vendor_data = {k: v for k, v in vendor_data.items() if k not in ["_id", "vid"]}
        vendor_service.update_vendor(vendor_id, vendor_data)
        return {"message": "Vendor updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor update error: {str(e)}")


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(vendor_id: str):
    """Soft delete a panel vendor with safety checks."""
    try:
        vendor_service.delete_vendor_safe(vendor_id)
        return {"message": "Vendor deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vendor delete error: {str(e)}")


# ---------------------------------------------------------------------------
# Project routes
# ---------------------------------------------------------------------------

@router.post("/projects/")
async def create_project(project_data: Dict[str, Any] = Body(...)):
    try:
        if not project_data.get("projectName") or not project_data["projectName"].strip():
            raise HTTPException(status_code=400, detail="Project name is required")
        if not project_data.get("salesPerson") or not project_data["salesPerson"].strip():
            raise HTTPException(status_code=400, detail="Sales person is required")
        if not project_data.get("client") or not project_data["client"].strip():
            raise HTTPException(status_code=400, detail="Client is required")
        result = vendor_service.create_project(project_data)
        return {"message": "Project created successfully", "project": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project creation error: {str(e)}")


@router.get("/projects/", dependencies=[Depends(verify_session)])
async def get_projects():
    try:
        from repositories import vendor_repo
        projects = await asyncio.to_thread(vendor_repo.list_projects)
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch projects error: {str(e)}")


@router.get("/projects", dependencies=[Depends(verify_session)])
async def get_projects_no_slash():
    return await get_projects()


@router.post("/projects")
async def create_project_no_slash(project_data: Dict[str, Any] = Body(...)):
    return await create_project(project_data=project_data)


@router.put("/projects/{project_id}")
async def update_project(project_id: str, project_data: Dict[str, Any] = Body(...)):
    try:
        project_data = {k: v for k, v in project_data.items() if k not in ["_id", "surveyNo"]}
        vendor_service.update_project(project_id, project_data)
        return {"message": "Project updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project update error: {str(e)}")


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Soft delete a project with cascade validation."""
    try:
        vendor_service.delete_project_safe(project_id)
        return {"message": "Project deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project delete error: {str(e)}")
