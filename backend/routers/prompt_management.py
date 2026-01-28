"""
Prompt Management Router - Endpoints for managing AI agent prompts

Provides API endpoints for:
- Create, read, update, delete prompts
- Manage prompt versions
- Test prompts
- Deploy prompts to agents
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/prompts",
    tags=["prompts"]
)

# MongoDB connection
MONGO_URI = __import__("os").getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)
prompt_db = mongo_client["prompt_management"]
prompts_collection = prompt_db["prompts"]
prompt_versions_collection = prompt_db["versions"]
prompt_templates_collection = prompt_db["templates"]


# ============================================
# Pydantic Models
# ============================================

class PromptCreate(BaseModel):
    """Create new prompt"""
    name: str = Field(..., min_length=1, description="Prompt name")
    description: str = Field("", description="Prompt description")
    content: str = Field(..., min_length=10, description="Prompt content/template")
    agent_type: str = Field(default="mail_segregation", description="Agent type this prompt is for")
    is_active: bool = Field(default=True, description="Is prompt active")
    tags: List[str] = Field(default_factory=list, description="Tags for organization")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Prompt parameters")


class PromptUpdate(BaseModel):
    """Update existing prompt"""
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[List[str]] = None
    parameters: Optional[Dict[str, Any]] = None


class PromptTestRequest(BaseModel):
    """Test a prompt"""
    content: str = Field(..., description="Prompt content to test")
    test_input: str = Field(..., description="Test input/data")
    agent_type: str = Field(default="mail_segregation", description="Agent type")


class PromptResponse(BaseModel):
    """Prompt response model"""
    id: str
    name: str
    description: str
    content: str
    agent_type: str
    is_active: bool
    tags: List[str]
    parameters: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


# ============================================
# Helper Functions
# ============================================

def _prompt_to_response(prompt: Dict[str, Any]) -> PromptResponse:
    """Convert database prompt to response model"""
    return PromptResponse(
        id=str(prompt.get("_id", "")),
        name=prompt.get("name", ""),
        description=prompt.get("description", ""),
        content=prompt.get("content", ""),
        agent_type=prompt.get("agent_type", ""),
        is_active=prompt.get("is_active", True),
        tags=prompt.get("tags", []),
        parameters=prompt.get("parameters", {}),
        created_at=prompt.get("created_at", ""),
        updated_at=prompt.get("updated_at", ""),
        version=prompt.get("version", 1)
    )


# ============================================
# Endpoints
# ============================================

@router.post("/create")
async def create_prompt(
    request: Request,
    payload: PromptCreate
) -> Dict[str, Any]:
    """
    Create a new prompt
    
    Prompts are versioned - each update creates a new version
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Check if prompt name already exists
        existing = prompts_collection.find_one({"name": payload.name})
        if existing:
            raise HTTPException(status_code=400, detail="Prompt name already exists")
        
        now = datetime.utcnow().isoformat()
        
        prompt_doc = {
            "name": payload.name,
            "description": payload.description,
            "content": payload.content,
            "agent_type": payload.agent_type,
            "is_active": payload.is_active,
            "tags": payload.tags,
            "parameters": payload.parameters,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "created_by": session_id,
            "updated_by": session_id
        }
        
        result = prompts_collection.insert_one(prompt_doc)
        prompt_doc["_id"] = result.inserted_id
        
        # Create version record
        version_doc = {
            "prompt_id": result.inserted_id,
            "version": 1,
            "content": payload.content,
            "parameters": payload.parameters,
            "created_at": now,
            "created_by": session_id,
            "notes": "Initial version"
        }
        prompt_versions_collection.insert_one(version_doc)
        
        return {
            "success": True,
            "prompt": _prompt_to_response(prompt_doc)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{prompt_id}")
async def get_prompt(
    request: Request,
    prompt_id: str
) -> Dict[str, Any]:
    """Get a single prompt by ID"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        
        return {
            "success": True,
            "prompt": _prompt_to_response(prompt)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_prompts(
    request: Request,
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    active_only: bool = Query(False, description="Show only active prompts"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(50, description="Limit results"),
    skip: int = Query(0, description="Skip N results")
) -> Dict[str, Any]:
    """
    List prompts with optional filtering
    
    Can filter by:
    - agent_type: Filter by specific agent type
    - active_only: Only show active prompts
    - tag: Filter by tag
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Build query
        query = {}
        if agent_type:
            query["agent_type"] = agent_type
        if active_only:
            query["is_active"] = True
        if tag:
            query["tags"] = tag
        
        # Get prompts
        prompts = list(prompts_collection.find(query).skip(skip).limit(limit))
        total = prompts_collection.count_documents(query)
        
        return {
            "success": True,
            "total": total,
            "prompts": [_prompt_to_response(p) for p in prompts]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{prompt_id}")
async def update_prompt(
    request: Request,
    prompt_id: str,
    payload: PromptUpdate
) -> Dict[str, Any]:
    """
    Update a prompt
    
    Creates new version automatically when content or parameters change
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        
        now = datetime.utcnow().isoformat()
        
        # Check if we need to create a new version
        create_new_version = False
        if payload.content and payload.content != prompt.get("content"):
            create_new_version = True
        if payload.parameters and payload.parameters != prompt.get("parameters", {}):
            create_new_version = True
        
        # Build update doc
        update_doc = {"updated_at": now, "updated_by": session_id}
        
        if payload.name is not None:
            update_doc["name"] = payload.name
        if payload.description is not None:
            update_doc["description"] = payload.description
        if payload.content is not None:
            update_doc["content"] = payload.content
        if payload.is_active is not None:
            update_doc["is_active"] = payload.is_active
        if payload.tags is not None:
            update_doc["tags"] = payload.tags
        if payload.parameters is not None:
            update_doc["parameters"] = payload.parameters
        
        # Update prompt
        prompts_collection.update_one(
            {"_id": ObjectId(prompt_id)},
            {"$set": update_doc}
        )
        
        # Create new version if content changed
        if create_new_version:
            new_version = prompt.get("version", 1) + 1
            version_doc = {
                "prompt_id": ObjectId(prompt_id),
                "version": new_version,
                "content": payload.content or prompt.get("content"),
                "parameters": payload.parameters or prompt.get("parameters", {}),
                "created_at": now,
                "created_by": session_id,
                "notes": "Updated version"
            }
            prompt_versions_collection.insert_one(version_doc)
            
            # Update version in main prompt doc
            prompts_collection.update_one(
                {"_id": ObjectId(prompt_id)},
                {"$set": {"version": new_version}}
            )
        
        # Get updated prompt
        updated_prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        
        return {
            "success": True,
            "prompt": _prompt_to_response(updated_prompt),
            "version_created": create_new_version
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{prompt_id}")
async def delete_prompt(
    request: Request,
    prompt_id: str
) -> Dict[str, Any]:
    """
    Delete a prompt (soft delete - marks as inactive)
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        
        # Soft delete - mark as inactive
        prompts_collection.update_one(
            {"_id": ObjectId(prompt_id)},
            {"$set": {
                "is_active": False,
                "deleted_at": datetime.utcnow().isoformat(),
                "deleted_by": session_id
            }}
        )
        
        return {"success": True, "message": "Prompt deleted"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{prompt_id}/versions")
async def get_prompt_versions(
    request: Request,
    prompt_id: str
) -> Dict[str, Any]:
    """Get all versions of a prompt"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        versions = list(prompt_versions_collection.find(
            {"prompt_id": ObjectId(prompt_id)}
        ).sort("version", -1))
        
        return {
            "success": True,
            "versions": [
                {
                    "version": v.get("version"),
                    "content": v.get("content", ""),
                    "parameters": v.get("parameters", {}),
                    "created_at": v.get("created_at"),
                    "created_by": v.get("created_by"),
                    "notes": v.get("notes", "")
                }
                for v in versions
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting versions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{prompt_id}/rollback/{version}")
async def rollback_prompt_version(
    request: Request,
    prompt_id: str,
    version: int
) -> Dict[str, Any]:
    """
    Rollback to a previous version of a prompt
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Get the version to rollback to
        version_doc = prompt_versions_collection.find_one({
            "prompt_id": ObjectId(prompt_id),
            "version": version
        })
        
        if not version_doc:
            raise HTTPException(status_code=404, detail="Version not found")
        
        prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        
        now = datetime.utcnow().isoformat()
        new_version = prompt.get("version", 1) + 1
        
        # Create new version with rolled back content
        new_version_doc = {
            "prompt_id": ObjectId(prompt_id),
            "version": new_version,
            "content": version_doc.get("content"),
            "parameters": version_doc.get("parameters", {}),
            "created_at": now,
            "created_by": session_id,
            "notes": f"Rollback to version {version}"
        }
        prompt_versions_collection.insert_one(new_version_doc)
        
        # Update main prompt
        prompts_collection.update_one(
            {"_id": ObjectId(prompt_id)},
            {"$set": {
                "content": version_doc.get("content"),
                "parameters": version_doc.get("parameters", {}),
                "version": new_version,
                "updated_at": now,
                "updated_by": session_id
            }}
        )
        
        updated_prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        
        return {
            "success": True,
            "message": f"Rolled back to version {version}",
            "prompt": _prompt_to_response(updated_prompt),
            "new_version": new_version
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rolling back version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test")
async def test_prompt(
    request: Request,
    payload: PromptTestRequest
) -> Dict[str, Any]:
    """
    Test a prompt with sample input
    
    Returns result from running the prompt with test data
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # This is a placeholder - actual implementation would run the prompt
        # through the appropriate agent
        
        import google.generativeai as genai
        api_key = __import__("os").getenv("GEMINI_API_KEY")
        
        if not api_key:
            raise HTTPException(status_code=400, detail="Gemini API not configured")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        
        # Combine prompt with test input
        full_prompt = f"{payload.content}\n\n--- TEST INPUT ---\n{payload.test_input}"
        
        response = model.generate_content(full_prompt)
        
        return {
            "success": True,
            "agent_type": payload.agent_type,
            "input": payload.test_input,
            "output": response.text,
            "tested_at": datetime.utcnow().isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))
