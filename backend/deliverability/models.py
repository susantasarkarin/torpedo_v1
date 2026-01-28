from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime

class DomainHealth(BaseModel):
    """Domain health check results"""
    domain: str
    spf_status: str = "unknown"  # pass | fail | unknown
    dkim_status: str = "unknown"
    dmarc_status: str = "unknown"
    mx_records: List[str] = []
    health_score: float = 0.0  # 0-100
    last_checked: datetime
    issues: List[str] = []

class GmailAccountUsage(BaseModel):
    """Track Gmail account send limits (2000/day)"""
    account_id: str
    account_email: str
    sends_today: int = 0
    send_limit: int = 2000
    last_reset: datetime
    last_send: Optional[datetime] = None
    status: str = "active"  # active | quota_exceeded | disabled

class ReputationMetrics(BaseModel):
    """Email reputation tracking"""
    domain: str
    date: str  # YYYY-MM-DD
    bounce_rate: float = 0.0
    complaint_rate: float = 0.0
    open_rate: float = 0.0
    calculated_score: float = 0.0  # 0-100
    total_sent: int = 0
