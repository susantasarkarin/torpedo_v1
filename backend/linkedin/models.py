from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime

class LinkedInSession(BaseModel):
    """Browser session for LinkedIn automation"""
    session_id: str
    email: str
    status: str = "active"  # active | expired | logged_out
    browser_cookies: Optional[Dict] = None
    last_active: Optional[datetime] = None
    login_date: Optional[datetime] = None

class LinkedInConnection(BaseModel):
    """Tracks LinkedIn connection requests"""
    lead_id: str
    linkedin_url: str
    status: str = "pending"  # pending | accepted | rejected | withdrawn
    connection_note: Optional[str] = None
    sent_at: datetime
    accepted_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None

class LinkedInMessage(BaseModel):
    """LinkedIn messages sent to connections"""
    lead_id: str
    connection_id: str
    message_content: str
    sent_at: datetime
    read_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None

class LinkedInActivity(BaseModel):
    """Daily activity tracking for rate limiting"""
    date: str  # YYYY-MM-DD
    session_id: str
    connections_sent: int = 0
    connections_accepted: int = 0
    messages_sent: int = 0
    profile_views: int = 0
    daily_connection_limit: int = 100
    daily_message_limit: int = 50
