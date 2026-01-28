"""
TEAM COLLABORATION API ROUTER
==============================

REST API endpoints for team management, lead assignment, and activity tracking.

Features:
- Team lead management
- Lead assignment
- Team activity feed
- Team performance dashboard
- Collaboration features

Endpoints:
- GET /team/leads - Get team's leads
- POST /team/leads/{id}/assign - Assign lead to user
- GET /team/activity - Team activity feed
- GET /team/dashboard - Team performance metrics
- GET /team/members - Team member list
- POST /team/members - Add team member
- DELETE /team/members/{id} - Remove team member
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
import os

from ..activity.feed import ActivityFeed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/team", tags=["Team Collaboration"])


# ============== MODELS ==============

class AssignLeadRequest(BaseModel):
    """Request to assign lead to user"""
    assign_to: str = Field(..., description="User ID to assign to")
    notes: Optional[str] = None


class LeadFilterRequest(BaseModel):
    """Filter parameters for team leads"""
    assigned_to: Optional[str] = None
    team_id: Optional[str] = None
    status: Optional[str] = None
    seniority_level: Optional[str] = None
    department: Optional[str] = None
    skip: int = 0
    limit: int = 50


class TeamMemberRequest(BaseModel):
    """Request to add team member"""
    user_id: str
    role: str = "member"  # member | lead | admin
    email: str
    name: str


# ============== DATABASE ==============

def get_db():
    """Get MongoDB database instance"""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    return client['email_automation']


def get_activity_feed():
    """Get activity feed instance"""
    return ActivityFeed()


# ============== HELPER FUNCTIONS ==============

def get_current_user_id(request: Request) -> str:
    """
    Extract user ID from request
    
    In production, this would validate JWT token and extract user_id
    For now, we'll use a header or default value
    """
    user_id = request.headers.get("X-User-ID", "demo_user")
    return user_id


def get_user_team_id(user_id: str, db) -> Optional[str]:
    """Get team ID for a user"""
    user = db["users"].find_one({"user_id": user_id})
    if user:
        return user.get("team_id")
    return None


# ============== LEAD ENDPOINTS ==============

@router.get("/leads", response_model=Dict[str, Any])
async def get_team_leads(
    team_id: Optional[str] = Query(None, description="Team ID (defaults to current user's team)"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user"),
    status: Optional[str] = Query(None, description="Filter by engagement status"),
    seniority_level: Optional[str] = Query(None, description="Filter by seniority"),
    department: Optional[str] = Query(None, description="Filter by department"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    request: Request = None,
    db = Depends(get_db)
):
    """
    Get team's leads with filtering
    
    Returns list of leads assigned to team members
    """
    user_id = get_current_user_id(request)
    
    # If no team_id provided, use current user's team
    if not team_id:
        team_id = get_user_team_id(user_id, db)
        if not team_id:
            raise HTTPException(status_code=400, detail="User not assigned to a team")
    
    # Build query
    query = {"team_id": team_id}
    
    if assigned_to:
        query["assigned_to"] = assigned_to
    
    if status:
        query["engagement_status"] = status
    
    if seniority_level:
        query["seniority_level"] = seniority_level
    
    if department:
        query["department"] = department
    
    # Get total count
    total = db["leads_enriched"].count_documents(query)
    
    # Get leads
    leads = list(
        db["leads_enriched"]
        .find(query)
        .sort("updated_at", DESCENDING)
        .skip(skip)
        .limit(limit)
    )
    
    # Convert ObjectId to string
    for lead in leads:
        if "_id" in lead:
            lead["_id"] = str(lead["_id"])
    
    return {
        "success": True,
        "total": total,
        "skip": skip,
        "limit": limit,
        "leads": leads
    }


@router.post("/leads/{lead_id}/assign", response_model=Dict[str, Any])
async def assign_lead(
    lead_id: str,
    request_data: AssignLeadRequest,
    request: Request = None,
    db = Depends(get_db),
    activity_feed: ActivityFeed = Depends(get_activity_feed)
):
    """
    Assign lead to a team member
    
    Updates lead's assigned_to field and logs activity
    """
    user_id = get_current_user_id(request)
    
    # Get lead
    lead = db["leads_enriched"].find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Verify assignee exists
    assignee = db["users"].find_one({"user_id": request_data.assign_to})
    if not assignee:
        raise HTTPException(status_code=404, detail="Assignee not found")
    
    # Get team_id from assignee
    assignee_team_id = assignee.get("team_id")
    
    # Update lead
    previous_assignee = lead.get("assigned_to")
    
    update_result = db["leads_enriched"].update_one(
        {"_id": ObjectId(lead_id)},
        {
            "$set": {
                "assigned_to": request_data.assign_to,
                "last_touched_by": user_id,
                "team_id": assignee_team_id,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    if update_result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to assign lead")
    
    # Log activity
    activity_feed.log_action(
        user_id=user_id,
        action="lead_assigned",
        resource="lead",
        resource_id=lead_id,
        team_id=assignee_team_id,
        details={
            "assigned_to": request_data.assign_to,
            "assignee_name": assignee.get("name", "Unknown"),
            "previous_assignee": previous_assignee,
            "notes": request_data.notes,
            "lead_email": lead.get("email"),
            "lead_name": lead.get("name")
        }
    )
    
    return {
        "success": True,
        "lead_id": lead_id,
        "assigned_to": request_data.assign_to,
        "message": f"Lead assigned to {assignee.get('name', request_data.assign_to)}"
    }


@router.post("/leads/{lead_id}/unassign", response_model=Dict[str, Any])
async def unassign_lead(
    lead_id: str,
    request: Request = None,
    db = Depends(get_db),
    activity_feed: ActivityFeed = Depends(get_activity_feed)
):
    """
    Unassign lead from current assignee
    """
    user_id = get_current_user_id(request)
    
    # Get lead
    lead = db["leads_enriched"].find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    previous_assignee = lead.get("assigned_to")
    
    # Update lead
    update_result = db["leads_enriched"].update_one(
        {"_id": ObjectId(lead_id)},
        {
            "$set": {
                "assigned_to": None,
                "last_touched_by": user_id,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    if update_result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to unassign lead")
    
    # Log activity
    if previous_assignee:
        activity_feed.log_action(
            user_id=user_id,
            action="lead_updated",
            resource="lead",
            resource_id=lead_id,
            team_id=lead.get("team_id"),
            details={
                "action": "unassigned",
                "previous_assignee": previous_assignee,
                "lead_email": lead.get("email"),
                "lead_name": lead.get("name")
            }
        )
    
    return {
        "success": True,
        "lead_id": lead_id,
        "message": "Lead unassigned"
    }


# ============== ACTIVITY ENDPOINTS ==============

@router.get("/activity", response_model=Dict[str, Any])
async def get_team_activity(
    team_id: Optional[str] = Query(None, description="Team ID"),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    action_filter: Optional[str] = Query(None, description="Comma-separated action types"),
    resource_filter: Optional[str] = Query(None, description="Comma-separated resource types"),
    hours: Optional[int] = Query(None, description="Last N hours"),
    request: Request = None,
    activity_feed: ActivityFeed = Depends(get_activity_feed),
    db = Depends(get_db)
):
    """
    Get team activity feed
    
    Returns recent activity for the team
    """
    user_id = get_current_user_id(request)
    
    # If no team_id provided, use current user's team
    if not team_id:
        team_id = get_user_team_id(user_id, db)
        if not team_id:
            raise HTTPException(status_code=400, detail="User not assigned to a team")
    
    # Parse filters
    actions = action_filter.split(",") if action_filter else None
    resources = resource_filter.split(",") if resource_filter else None
    
    # Get date range
    start_date = None
    if hours:
        start_date = datetime.utcnow() - timedelta(hours=hours)
    
    # Get activity
    activities = activity_feed.get_team_activity(
        team_id=team_id,
        limit=limit,
        skip=skip,
        action_filter=actions,
        resource_filter=resources,
        start_date=start_date
    )
    
    return {
        "success": True,
        "team_id": team_id,
        "total": len(activities),
        "activities": activities
    }


@router.get("/activity/user/{user_id}", response_model=Dict[str, Any])
async def get_user_activity(
    user_id: str,
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    request: Request = None,
    activity_feed: ActivityFeed = Depends(get_activity_feed)
):
    """
    Get activity feed for a specific user
    """
    activities = activity_feed.get_user_activity(
        user_id=user_id,
        limit=limit,
        skip=skip
    )
    
    return {
        "success": True,
        "user_id": user_id,
        "total": len(activities),
        "activities": activities
    }


# ============== DASHBOARD ENDPOINTS ==============

@router.get("/dashboard", response_model=Dict[str, Any])
async def get_team_dashboard(
    team_id: Optional[str] = Query(None, description="Team ID"),
    days: int = Query(7, ge=1, le=90, description="Time period in days"),
    request: Request = None,
    db = Depends(get_db),
    activity_feed: ActivityFeed = Depends(get_activity_feed)
):
    """
    Get team performance dashboard
    
    Returns metrics, activity stats, and team member performance
    """
    user_id = get_current_user_id(request)
    
    # If no team_id provided, use current user's team
    if not team_id:
        team_id = get_user_team_id(user_id, db)
        if not team_id:
            raise HTTPException(status_code=400, detail="User not assigned to a team")
    
    # Date range
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Get team members
    members = list(db["users"].find({"team_id": team_id}))
    member_ids = [m["user_id"] for m in members]
    
    # Lead metrics
    total_leads = db["leads_enriched"].count_documents({"team_id": team_id})
    assigned_leads = db["leads_enriched"].count_documents({
        "team_id": team_id,
        "assigned_to": {"$ne": None}
    })
    unassigned_leads = total_leads - assigned_leads
    
    # Lead status breakdown
    status_pipeline = [
        {"$match": {"team_id": team_id}},
        {"$group": {"_id": "$engagement_status", "count": {"$sum": 1}}}
    ]
    status_breakdown = {
        item["_id"]: item["count"]
        for item in db["leads_enriched"].aggregate(status_pipeline)
    }
    
    # Activity stats
    activity_stats = activity_feed.get_activity_stats(
        team_id=team_id,
        start_date=start_date
    )
    
    # Member performance
    member_stats = []
    for member in members:
        member_id = member["user_id"]
        
        # Assigned leads
        assigned_count = db["leads_enriched"].count_documents({
            "assigned_to": member_id
        })
        
        # Activity count
        activity_count = activity_stats.get("by_user", {}).get(member_id, 0)
        
        # Recent leads contacted
        recent_contacted = db["leads_enriched"].count_documents({
            "assigned_to": member_id,
            "last_outreach_date": {"$gte": start_date}
        })
        
        member_stats.append({
            "user_id": member_id,
            "name": member.get("name", "Unknown"),
            "email": member.get("email", ""),
            "role": member.get("role", "member"),
            "assigned_leads": assigned_count,
            "activity_count": activity_count,
            "recent_contacted": recent_contacted
        })
    
    # Campaign stats
    team_campaigns = list(db["campaigns"].find({"team_id": team_id}))
    active_campaigns = len([c for c in team_campaigns if c.get("status") == "active"])
    
    return {
        "success": True,
        "team_id": team_id,
        "period_days": days,
        "leads": {
            "total": total_leads,
            "assigned": assigned_leads,
            "unassigned": unassigned_leads,
            "status_breakdown": status_breakdown
        },
        "campaigns": {
            "total": len(team_campaigns),
            "active": active_campaigns
        },
        "activity": activity_stats,
        "members": member_stats
    }


# ============== TEAM MEMBER ENDPOINTS ==============

@router.get("/members", response_model=Dict[str, Any])
async def get_team_members(
    team_id: Optional[str] = Query(None, description="Team ID"),
    request: Request = None,
    db = Depends(get_db)
):
    """
    Get team member list
    """
    user_id = get_current_user_id(request)
    
    # If no team_id provided, use current user's team
    if not team_id:
        team_id = get_user_team_id(user_id, db)
        if not team_id:
            raise HTTPException(status_code=400, detail="User not assigned to a team")
    
    members = list(db["users"].find({"team_id": team_id}))
    
    # Convert ObjectId to string
    for member in members:
        if "_id" in member:
            member["_id"] = str(member["_id"])
    
    return {
        "success": True,
        "team_id": team_id,
        "total": len(members),
        "members": members
    }


@router.post("/members", response_model=Dict[str, Any])
async def add_team_member(
    member: TeamMemberRequest,
    team_id: Optional[str] = Query(None, description="Team ID"),
    request: Request = None,
    db = Depends(get_db),
    activity_feed: ActivityFeed = Depends(get_activity_feed)
):
    """
    Add member to team
    """
    user_id = get_current_user_id(request)
    
    # If no team_id provided, use current user's team
    if not team_id:
        team_id = get_user_team_id(user_id, db)
        if not team_id:
            raise HTTPException(status_code=400, detail="User not assigned to a team")
    
    # Check if user already exists
    existing = db["users"].find_one({"user_id": member.user_id})
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    
    # Create user
    user_data = {
        "user_id": member.user_id,
        "email": member.email,
        "name": member.name,
        "role": member.role,
        "team_id": team_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = db["users"].insert_one(user_data)
    
    # Log activity
    activity_feed.log_action(
        user_id=user_id,
        action="team_member_added",
        resource="team",
        resource_id=team_id,
        team_id=team_id,
        details={
            "new_member_id": member.user_id,
            "new_member_name": member.name,
            "new_member_email": member.email,
            "role": member.role
        }
    )
    
    return {
        "success": True,
        "user_id": member.user_id,
        "message": f"Added {member.name} to team"
    }


@router.delete("/members/{member_user_id}", response_model=Dict[str, Any])
async def remove_team_member(
    member_user_id: str,
    team_id: Optional[str] = Query(None, description="Team ID"),
    request: Request = None,
    db = Depends(get_db),
    activity_feed: ActivityFeed = Depends(get_activity_feed)
):
    """
    Remove member from team
    """
    user_id = get_current_user_id(request)
    
    # If no team_id provided, use current user's team
    if not team_id:
        team_id = get_user_team_id(user_id, db)
        if not team_id:
            raise HTTPException(status_code=400, detail="User not assigned to a team")
    
    # Get member to remove
    member = db["users"].find_one({"user_id": member_user_id, "team_id": team_id})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found in this team")
    
    # Remove from team (set team_id to null)
    db["users"].update_one(
        {"user_id": member_user_id},
        {"$set": {"team_id": None, "updated_at": datetime.utcnow()}}
    )
    
    # Unassign their leads
    db["leads_enriched"].update_many(
        {"assigned_to": member_user_id},
        {"$set": {"assigned_to": None, "updated_at": datetime.utcnow()}}
    )
    
    # Log activity
    activity_feed.log_action(
        user_id=user_id,
        action="team_member_removed",
        resource="team",
        resource_id=team_id,
        team_id=team_id,
        details={
            "removed_member_id": member_user_id,
            "removed_member_name": member.get("name", "Unknown")
        }
    )
    
    return {
        "success": True,
        "message": f"Removed {member.get('name', member_user_id)} from team"
    }
