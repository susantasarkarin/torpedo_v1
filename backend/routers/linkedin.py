"""
LINKEDIN AUTOMATION API ROUTER
===============================

REST API endpoints for LinkedIn automation control.
Manages browser sessions, connection requests, and messaging.
"""

from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel, Field
from bson import ObjectId
from pymongo import MongoClient
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/linkedin", tags=["LinkedIn Automation"])


# ============== MODELS ==============

class LoginRequest(BaseModel):
    """LinkedIn login request"""
    email: str = Field(..., description="LinkedIn account email")
    password: str = Field(..., description="LinkedIn account password")
    headless: bool = Field(False, description="Run browser in headless mode (not recommended for first login)")


class ConnectionRequest(BaseModel):
    """Send connection request"""
    lead_id: str = Field(..., description="Lead ID from database")
    linkedin_url: str = Field(..., description="LinkedIn profile URL")
    connection_note: Optional[str] = Field(None, description="Personalized connection note (max 300 chars)")
    custom_variables: Dict[str, Any] = Field(default_factory=dict, description="Additional tracking variables")


class MessageRequest(BaseModel):
    """Send message to 1st-degree connection"""
    lead_id: str = Field(..., description="Lead ID from database")
    connection_id: str = Field(..., description="Connection ID from linkedin_connections")
    message_content: str = Field(..., description="Message content to send")


class BulkConnectionRequest(BaseModel):
    """Send multiple connection requests"""
    connections: List[ConnectionRequest] = Field(..., description="List of connection requests")
    delay_between_requests: int = Field(30, ge=10, le=300, description="Delay in seconds between requests")


# ============== DATABASE ==============

def get_db():
    """Get MongoDB database instance"""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    return client['email_automation']


def get_linkedin_service(db = Depends(get_db)):
    """Get LinkedIn automation service instance"""
    from ..linkedin.service import LinkedInAutomationService
    
    # Return the service class for manual instantiation
    # (sessions are per-account, not singleton)
    return LinkedInAutomationService


# ============== SESSION ENDPOINTS ==============

@router.post("/session/login", response_model=Dict[str, Any])
async def start_login_session(
    request: LoginRequest,
    db = Depends(get_db),
    service_class = Depends(get_linkedin_service)
):
    """
    Start LinkedIn login flow.
    
    For first-time login:
    - Runs in headed browser mode (headless=False)
    - Waits for manual 2FA completion
    - Saves session cookies for future use
    
    For subsequent logins:
    - Reuses saved session
    - Can run in headless mode
    """
    try:
        # Create service instance
        service = service_class(db)
        
        # Initialize and login
        async with service:
            await service.initialize_session(request.email, headless=request.headless)
            
            success = await service.login(
                email=request.email,
                password=request.password,
                headless=request.headless
            )
            
            if not success:
                raise HTTPException(status_code=401, detail="Login failed")
            
            session_id = service.session_id
            
            return {
                "success": True,
                "session_id": session_id,
                "email": request.email,
                "status": "logged_in",
                "message": "LinkedIn session established successfully"
            }
    
    except Exception as e:
        logger.error(f"LinkedIn login failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/status", response_model=Dict[str, Any])
async def check_session_status(
    email: str = Query(..., description="LinkedIn account email"),
    db = Depends(get_db)
):
    """
    Check if LinkedIn session is valid and active.
    
    Returns:
    - Session status (active/expired/not_found)
    - Last activity timestamp
    - Daily usage stats
    """
    try:
        session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
        
        # Check session in database
        session = db["linkedin_sessions"].find_one({"session_id": session_id})
        
        if not session:
            return {
                "success": False,
                "status": "not_found",
                "message": "No session found for this email"
            }
        
        # Check if session is expired (>24 hours old)
        last_active = session.get("last_active")
        is_expired = False
        
        if last_active:
            age = datetime.utcnow() - last_active
            is_expired = age > timedelta(hours=24)
        
        status = "expired" if is_expired else session.get("status", "active")
        
        # Get today's activity
        today = datetime.utcnow().strftime("%Y-%m-%d")
        activity = db["linkedin_activity"].find_one({
            "session_id": session_id,
            "date": today
        })
        
        return {
            "success": True,
            "session_id": session_id,
            "email": email,
            "status": status,
            "last_active": last_active,
            "login_date": session.get("login_date"),
            "today_activity": {
                "connections_sent": activity.get("connections_sent", 0) if activity else 0,
                "messages_sent": activity.get("messages_sent", 0) if activity else 0,
                "daily_limits": {
                    "connections": f"{activity.get('connections_sent', 0) if activity else 0}/100",
                    "messages": f"{activity.get('messages_sent', 0) if activity else 0}/50"
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Session status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/logout", response_model=Dict[str, Any])
async def logout_session(
    email: str = Query(..., description="LinkedIn account email"),
    db = Depends(get_db)
):
    """
    Logout and invalidate LinkedIn session.
    
    Removes session cookies and marks session as logged_out.
    """
    try:
        session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
        
        # Update session status
        result = db["linkedin_sessions"].update_one(
            {"session_id": session_id},
            {"$set": {
                "status": "logged_out",
                "logged_out_at": datetime.utcnow()
            }}
        )
        
        if result.modified_count == 0:
            return {
                "success": False,
                "message": "No active session found"
            }
        
        return {
            "success": True,
            "session_id": session_id,
            "message": "Session logged out successfully"
        }
    
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== CONNECTION ENDPOINTS ==============

@router.post("/connections/send", response_model=Dict[str, Any])
async def send_connection_request(
    request: ConnectionRequest,
    email: str = Query(..., description="LinkedIn account email to use"),
    db = Depends(get_db),
    service_class = Depends(get_linkedin_service)
):
    """
    Send a LinkedIn connection request.
    
    Features:
    - Personalized connection notes
    - Rate limit checking (max 100/day)
    - Anti-detection delays
    - Activity tracking
    """
    try:
        # Check rate limits
        session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        activity = db["linkedin_activity"].find_one({
            "session_id": session_id,
            "date": today
        })
        
        if activity and activity.get("connections_sent", 0) >= 100:
            raise HTTPException(
                status_code=429,
                detail="Daily connection limit reached (100/day)"
            )
        
        # Create service instance
        service = service_class(db)
        
        # Send connection request
        async with service:
            await service.initialize_session(email, headless=True)
            
            success = await service.send_connection_request(
                profile_url=request.linkedin_url,
                note=request.connection_note
            )
            
            if not success:
                raise HTTPException(status_code=500, detail="Failed to send connection request")
        
        # Record in database
        connection_record = {
            "lead_id": request.lead_id,
            "linkedin_url": request.linkedin_url,
            "status": "pending",
            "connection_note": request.connection_note,
            "sent_at": datetime.utcnow(),
            "session_id": session_id,
            "custom_variables": request.custom_variables
        }
        
        result = db["linkedin_connections"].insert_one(connection_record)
        connection_id = str(result.inserted_id)
        
        # Update activity
        db["linkedin_activity"].update_one(
            {"session_id": session_id, "date": today},
            {
                "$inc": {"connections_sent": 1},
                "$set": {"last_updated": datetime.utcnow()}
            },
            upsert=True
        )
        
        return {
            "success": True,
            "connection_id": connection_id,
            "lead_id": request.lead_id,
            "linkedin_url": request.linkedin_url,
            "status": "pending",
            "message": "Connection request sent successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Send connection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connections/send-bulk", response_model=Dict[str, Any])
async def send_bulk_connections(
    request: BulkConnectionRequest,
    email: str = Query(..., description="LinkedIn account email to use"),
    db = Depends(get_db),
    service_class = Depends(get_linkedin_service)
):
    """
    Send multiple connection requests with delays.
    
    Useful for batch operations while respecting rate limits.
    """
    try:
        # Check rate limits
        session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        activity = db["linkedin_activity"].find_one({
            "session_id": session_id,
            "date": today
        })
        
        current_sent = activity.get("connections_sent", 0) if activity else 0
        remaining = 100 - current_sent
        
        if remaining <= 0:
            raise HTTPException(
                status_code=429,
                detail="Daily connection limit reached (100/day)"
            )
        
        # Limit to remaining quota
        connections_to_send = request.connections[:remaining]
        
        # Create service instance
        service = service_class(db)
        
        results = []
        
        async with service:
            await service.initialize_session(email, headless=True)
            
            for conn in connections_to_send:
                try:
                    success = await service.send_connection_request(
                        profile_url=conn.linkedin_url,
                        note=conn.connection_note
                    )
                    
                    if success:
                        # Record in database
                        connection_record = {
                            "lead_id": conn.lead_id,
                            "linkedin_url": conn.linkedin_url,
                            "status": "pending",
                            "connection_note": conn.connection_note,
                            "sent_at": datetime.utcnow(),
                            "session_id": session_id,
                            "custom_variables": conn.custom_variables
                        }
                        
                        result = db["linkedin_connections"].insert_one(connection_record)
                        
                        results.append({
                            "lead_id": conn.lead_id,
                            "connection_id": str(result.inserted_id),
                            "success": True
                        })
                        
                        # Update activity
                        db["linkedin_activity"].update_one(
                            {"session_id": session_id, "date": today},
                            {
                                "$inc": {"connections_sent": 1},
                                "$set": {"last_updated": datetime.utcnow()}
                            },
                            upsert=True
                        )
                    else:
                        results.append({
                            "lead_id": conn.lead_id,
                            "success": False,
                            "error": "Send failed"
                        })
                    
                    # Delay between requests
                    import asyncio
                    await asyncio.sleep(request.delay_between_requests)
                
                except Exception as e:
                    logger.error(f"Failed to send connection for lead {conn.lead_id}: {e}")
                    results.append({
                        "lead_id": conn.lead_id,
                        "success": False,
                        "error": str(e)
                    })
        
        successful = sum(1 for r in results if r.get("success"))
        
        return {
            "success": True,
            "total_attempted": len(connections_to_send),
            "successful": successful,
            "failed": len(connections_to_send) - successful,
            "results": results,
            "message": f"Sent {successful}/{len(connections_to_send)} connection requests"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk send failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections", response_model=Dict[str, Any])
async def list_connections(
    status: Optional[str] = Query(None, description="Filter by status: pending, accepted, rejected"),
    email: Optional[str] = Query(None, description="Filter by LinkedIn account email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db = Depends(get_db)
):
    """
    List LinkedIn connections with optional filtering.
    """
    try:
        query = {}
        
        if status:
            query["status"] = status
        
        if email:
            session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
            query["session_id"] = session_id
        
        total = db["linkedin_connections"].count_documents(query)
        skip = (page - 1) * page_size
        
        connections = list(
            db["linkedin_connections"]
            .find(query)
            .sort("sent_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        # Format connections
        for conn in connections:
            conn["id"] = str(conn.pop("_id"))
        
        return {
            "success": True,
            "connections": connections,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    
    except Exception as e:
        logger.error(f"List connections failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections/{connection_id}/status", response_model=Dict[str, Any])
async def check_connection_status(
    connection_id: str,
    db = Depends(get_db)
):
    """
    Check status of a specific connection request.
    
    Returns:
    - Current status (pending/accepted/rejected)
    - Timestamps
    - Lead information
    """
    try:
        connection = db["linkedin_connections"].find_one({"_id": ObjectId(connection_id)})
        
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        connection["id"] = str(connection.pop("_id"))
        
        return {
            "success": True,
            "connection": connection
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Check connection status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/connections/{connection_id}/status", response_model=Dict[str, Any])
async def update_connection_status(
    connection_id: str,
    new_status: str = Body(..., description="New status: accepted, rejected, withdrawn"),
    db = Depends(get_db)
):
    """
    Update connection status (usually done by webhook or manual check).
    """
    try:
        valid_statuses = ["pending", "accepted", "rejected", "withdrawn"]
        if new_status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )
        
        update_fields = {
            "status": new_status,
            "updated_at": datetime.utcnow()
        }
        
        if new_status == "accepted":
            update_fields["accepted_at"] = datetime.utcnow()
        elif new_status == "rejected":
            update_fields["rejected_at"] = datetime.utcnow()
        
        result = db["linkedin_connections"].update_one(
            {"_id": ObjectId(connection_id)},
            {"$set": update_fields}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        return {
            "success": True,
            "connection_id": connection_id,
            "new_status": new_status,
            "message": "Connection status updated"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update connection status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== MESSAGING ENDPOINTS ==============

@router.post("/messages/send", response_model=Dict[str, Any])
async def send_linkedin_message(
    request: MessageRequest,
    email: str = Query(..., description="LinkedIn account email to use"),
    db = Depends(get_db),
    service_class = Depends(get_linkedin_service)
):
    """
    Send a message to a 1st-degree LinkedIn connection.
    
    Requirements:
    - Connection must be accepted (status="accepted")
    - Rate limit: 50 messages/day
    """
    try:
        # Verify connection exists and is accepted
        connection = db["linkedin_connections"].find_one({"_id": ObjectId(request.connection_id)})
        
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        if connection.get("status") != "accepted":
            raise HTTPException(
                status_code=400,
                detail="Can only message accepted connections"
            )
        
        # Check rate limits
        session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        activity = db["linkedin_activity"].find_one({
            "session_id": session_id,
            "date": today
        })
        
        if activity and activity.get("messages_sent", 0) >= 50:
            raise HTTPException(
                status_code=429,
                detail="Daily message limit reached (50/day)"
            )
        
        # Create service instance
        service = service_class(db)
        
        # Send message
        async with service:
            await service.initialize_session(email, headless=True)
            
            success = await service.send_message(
                profile_url=connection.get("linkedin_url"),
                message=request.message_content
            )
            
            if not success:
                raise HTTPException(status_code=500, detail="Failed to send message")
        
        # Record in database
        message_record = {
            "lead_id": request.lead_id,
            "connection_id": request.connection_id,
            "message_content": request.message_content,
            "sent_at": datetime.utcnow(),
            "session_id": session_id
        }
        
        result = db["linkedin_messages"].insert_one(message_record)
        message_id = str(result.inserted_id)
        
        # Update activity
        db["linkedin_activity"].update_one(
            {"session_id": session_id, "date": today},
            {
                "$inc": {"messages_sent": 1},
                "$set": {"last_updated": datetime.utcnow()}
            },
            upsert=True
        )
        
        return {
            "success": True,
            "message_id": message_id,
            "connection_id": request.connection_id,
            "lead_id": request.lead_id,
            "message": "Message sent successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Send message failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== STATS ENDPOINTS ==============

@router.get("/stats", response_model=Dict[str, Any])
async def get_linkedin_stats(
    email: Optional[str] = Query(None, description="LinkedIn account email"),
    date_range: str = Query("today", description="Date range: today, week, month, all"),
    db = Depends(get_db)
):
    """
    Get LinkedIn activity statistics for dashboard.
    
    Returns:
    - Connections sent/accepted
    - Acceptance rate
    - Messages sent
    - Daily limits status
    """
    try:
        # Build date filter
        date_filter = {}
        
        if date_range == "today":
            today = datetime.utcnow().strftime("%Y-%m-%d")
            date_filter = {"date": today}
        elif date_range == "week":
            week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
            date_filter = {"date": {"$gte": week_ago}}
        elif date_range == "month":
            month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
            date_filter = {"date": {"$gte": month_ago}}
        
        # Filter by email if provided
        query = date_filter.copy()
        if email:
            session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
            query["session_id"] = session_id
        
        # Aggregate activity
        activities = list(db["linkedin_activity"].find(query))
        
        total_connections_sent = sum(a.get("connections_sent", 0) for a in activities)
        total_connections_accepted = sum(a.get("connections_accepted", 0) for a in activities)
        total_messages_sent = sum(a.get("messages_sent", 0) for a in activities)
        
        acceptance_rate = (
            total_connections_accepted / total_connections_sent
            if total_connections_sent > 0
            else 0
        )
        
        # Get today's limits
        today = datetime.utcnow().strftime("%Y-%m-%d")
        today_query = {"date": today}
        if email:
            today_query["session_id"] = session_id
        
        today_activity = db["linkedin_activity"].find_one(today_query)
        
        today_connections = today_activity.get("connections_sent", 0) if today_activity else 0
        today_messages = today_activity.get("messages_sent", 0) if today_activity else 0
        
        return {
            "success": True,
            "date_range": date_range,
            "email": email,
            "stats": {
                "connections_sent": total_connections_sent,
                "connections_accepted": total_connections_accepted,
                "acceptance_rate": round(acceptance_rate, 2),
                "messages_sent": total_messages_sent,
                "daily_limits": {
                    "connections": f"{today_connections}/100",
                    "messages": f"{today_messages}/50",
                    "connections_remaining": 100 - today_connections,
                    "messages_remaining": 50 - today_messages
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Get stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/daily-breakdown", response_model=Dict[str, Any])
async def get_daily_breakdown(
    email: Optional[str] = Query(None, description="LinkedIn account email"),
    days: int = Query(7, ge=1, le=90, description="Number of days to include"),
    db = Depends(get_db)
):
    """
    Get daily breakdown of LinkedIn activity for charts.
    """
    try:
        # Build query
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        query = {"date": {"$gte": start_date}}
        
        if email:
            session_id = f"linkedin_{email.replace('@', '_').replace('.', '_')}"
            query["session_id"] = session_id
        
        # Get activities
        activities = list(db["linkedin_activity"].find(query).sort("date", 1))
        
        # Format for charting
        daily_data = []
        for activity in activities:
            daily_data.append({
                "date": activity.get("date"),
                "connections_sent": activity.get("connections_sent", 0),
                "connections_accepted": activity.get("connections_accepted", 0),
                "messages_sent": activity.get("messages_sent", 0)
            })
        
        return {
            "success": True,
            "email": email,
            "days": days,
            "daily_breakdown": daily_data
        }
    
    except Exception as e:
        logger.error(f"Get daily breakdown failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
