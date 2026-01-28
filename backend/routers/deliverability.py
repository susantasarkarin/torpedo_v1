"""
DELIVERABILITY API ROUTER
=========================

REST API endpoints for domain health monitoring, Gmail pool usage tracking,
and email deliverability reputation metrics.

Author: Agent 11
Date: 2026-01-28
"""

from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from ..deliverability.domain_health import DomainHealthService
from ..campaigns.rate_limiter import RateLimitService
from ..database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deliverability", tags=["Deliverability"])


# ============== REQUEST/RESPONSE MODELS ==============

class DomainHealthResponse(BaseModel):
    """Domain health check response"""
    domain: str
    spf: Dict[str, Any]
    dkim: Dict[str, Any]
    dmarc: Dict[str, Any]
    mx_records: List[str]
    health_score: int
    grade: str
    recommendations: List[str]
    timestamp: str


class GmailPoolUsageResponse(BaseModel):
    """Gmail pool usage statistics"""
    total_capacity: int
    used: int
    available: int
    percentage_used: float
    active_accounts: int
    total_accounts: int
    quota_exceeded: int
    accounts: List[Dict[str, Any]]


class ReputationMetricsResponse(BaseModel):
    """Aggregated reputation metrics"""
    date_range: str
    domains: List[Dict[str, Any]]
    overall_bounce_rate: float
    overall_complaint_rate: float
    overall_open_rate: float
    total_sent: int


class DeliverabilityAlert(BaseModel):
    """Deliverability alert"""
    alert_id: str
    severity: str  # critical | warning | info
    type: str  # spf_failure | dkim_missing | high_bounce_rate | quota_exceeded
    message: str
    domain: Optional[str] = None
    account_email: Optional[str] = None
    created_at: datetime
    resolved: bool = False


# ============== DEPENDENCIES ==============

def get_db():
    """Get database connection"""
    return get_database("email_automation")


def get_domain_health_service():
    """Get domain health service instance"""
    return DomainHealthService()


# ============== ENDPOINTS ==============

@router.get("/domains", response_model=Dict[str, Any])
async def list_monitored_domains(db=Depends(get_db)):
    """
    List all domains currently monitored for deliverability.
    
    Returns list of domains extracted from:
    - Gmail accounts
    - Campaign sender addresses
    - Custom domain configurations
    """
    try:
        domains = set()
        
        # Get domains from Gmail accounts
        gmail_accounts = db["gmail_accounts"].find({"status": "active"})
        for account in gmail_accounts:
            email = account.get("email", "")
            if "@" in email:
                domain = email.split("@")[1]
                domains.add(domain)
        
        # Get domains from campaigns
        campaigns = db["campaigns"].find({})
        for campaign in campaigns:
            from_email = campaign.get("from_email", "")
            if "@" in from_email:
                domain = from_email.split("@")[1]
                domains.add(domain)
        
        # Get explicitly configured domains
        domain_configs = db["domain_health"].find({})
        for config in domain_configs:
            domains.add(config.get("domain"))
        
        domain_list = sorted(list(domains))
        
        return {
            "success": True,
            "total": len(domain_list),
            "domains": domain_list
        }
    
    except Exception as e:
        logger.error(f"Error listing domains: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domains/{domain}/health", response_model=DomainHealthResponse)
async def get_domain_health(
    domain: str,
    service: DomainHealthService = Depends(get_domain_health_service),
    db=Depends(get_db)
):
    """
    Perform comprehensive health check for a domain.
    
    Checks:
    - SPF record validation
    - DKIM record detection
    - DMARC policy configuration
    - MX record availability
    
    Returns health score (0-100) and grade (A-F).
    """
    try:
        # Perform health check
        health_result = service.calculate_health_score(domain)
        
        # Get recommendations
        recommendations = service.get_recommendations(health_result)
        
        # Store result in database
        db["domain_health"].update_one(
            {"domain": domain},
            {
                "$set": {
                    "domain": domain,
                    "spf_status": health_result["spf"]["status"],
                    "dkim_status": "pass" if len(health_result["dkim"].get("valid_selectors", [])) > 0 else "fail",
                    "dmarc_status": health_result["dmarc"]["status"],
                    "mx_records": health_result["mx"],
                    "health_score": health_result["score"],
                    "grade": health_result["grade"],
                    "last_checked": datetime.utcnow(),
                    "issues": [r for r in recommendations if "excellent" not in r.lower()]
                }
            },
            upsert=True
        )
        
        return DomainHealthResponse(
            domain=domain,
            spf=health_result["spf"],
            dkim=health_result["dkim"],
            dmarc=health_result["dmarc"],
            mx_records=health_result["mx"],
            health_score=health_result["score"],
            grade=health_result["grade"],
            recommendations=recommendations,
            timestamp=health_result["timestamp"]
        )
    
    except Exception as e:
        logger.error(f"Error checking domain health for {domain}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains/{domain}/check", response_model=Dict[str, Any])
async def trigger_manual_check(
    domain: str,
    service: DomainHealthService = Depends(get_domain_health_service),
    db=Depends(get_db)
):
    """
    Trigger a manual health check for a domain.
    
    This bypasses any caching and performs a fresh DNS lookup.
    Useful for verifying changes after DNS updates.
    """
    try:
        # Perform fresh health check
        health_result = service.calculate_health_score(domain)
        
        # Store in database
        db["domain_health"].update_one(
            {"domain": domain},
            {
                "$set": {
                    "domain": domain,
                    "spf_status": health_result["spf"]["status"],
                    "dkim_status": "pass" if len(health_result["dkim"].get("valid_selectors", [])) > 0 else "fail",
                    "dmarc_status": health_result["dmarc"]["status"],
                    "mx_records": health_result["mx"],
                    "health_score": health_result["score"],
                    "grade": health_result["grade"],
                    "last_checked": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        return {
            "success": True,
            "domain": domain,
            "health_score": health_result["score"],
            "grade": health_result["grade"],
            "timestamp": health_result["timestamp"],
            "message": f"Health check completed for {domain}"
        }
    
    except Exception as e:
        logger.error(f"Error during manual check for {domain}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail-accounts/usage", response_model=GmailPoolUsageResponse)
async def get_gmail_pool_usage(db=Depends(get_db)):
    """
    Get Gmail pool usage statistics.
    
    Shows:
    - Total sending capacity across all accounts
    - Current usage (X/2000 per account per day)
    - Available capacity
    - Per-account breakdown
    
    Gmail enforces 2000 emails/day per account limit.
    """
    try:
        rate_limiter = RateLimitService(db)
        stats = rate_limiter.get_pool_stats()
        
        return GmailPoolUsageResponse(
            total_capacity=stats["total_capacity"],
            used=stats["used"],
            available=stats["available"],
            percentage_used=stats["percentage_used"],
            active_accounts=stats["active_accounts"],
            total_accounts=stats["total_accounts"],
            quota_exceeded=stats["quota_exceeded"],
            accounts=stats["accounts"]
        )
    
    except Exception as e:
        logger.error(f"Error getting Gmail pool usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reputation", response_model=Dict[str, Any])
async def get_reputation_metrics(
    days: int = Query(7, description="Number of days to aggregate", ge=1, le=90),
    db=Depends(get_db)
):
    """
    Get aggregated reputation metrics across all domains.
    
    Calculates:
    - Bounce rates
    - Complaint rates  
    - Open rates
    - Overall reputation score
    
    Aggregated over the specified number of days.
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Get all campaigns sent in the date range
        campaigns = list(db["campaigns"].find({
            "created_at": {"$gte": start_date}
        }))
        
        domain_metrics = {}
        total_sent = 0
        total_bounced = 0
        total_complained = 0
        total_opened = 0
        
        for campaign in campaigns:
            campaign_id = campaign["_id"]
            
            # Get campaign sends
            sends = list(db["campaign_sends"].find({"campaign_id": campaign_id}))
            
            # Extract domain from sender
            from_email = campaign.get("from_email", "")
            domain = from_email.split("@")[1] if "@" in from_email else "unknown"
            
            if domain not in domain_metrics:
                domain_metrics[domain] = {
                    "domain": domain,
                    "sent": 0,
                    "bounced": 0,
                    "complained": 0,
                    "opened": 0,
                    "bounce_rate": 0.0,
                    "complaint_rate": 0.0,
                    "open_rate": 0.0
                }
            
            # Count metrics
            for send in sends:
                domain_metrics[domain]["sent"] += 1
                total_sent += 1
                
                status = send.get("status", "")
                if status == "bounced":
                    domain_metrics[domain]["bounced"] += 1
                    total_bounced += 1
                elif status == "complained":
                    domain_metrics[domain]["complained"] += 1
                    total_complained += 1
                elif send.get("opened", False):
                    domain_metrics[domain]["opened"] += 1
                    total_opened += 1
        
        # Calculate rates for each domain
        for domain, metrics in domain_metrics.items():
            if metrics["sent"] > 0:
                metrics["bounce_rate"] = round((metrics["bounced"] / metrics["sent"]) * 100, 2)
                metrics["complaint_rate"] = round((metrics["complained"] / metrics["sent"]) * 100, 2)
                metrics["open_rate"] = round((metrics["opened"] / metrics["sent"]) * 100, 2)
        
        # Calculate overall rates
        overall_bounce_rate = round((total_bounced / total_sent) * 100, 2) if total_sent > 0 else 0.0
        overall_complaint_rate = round((total_complained / total_sent) * 100, 2) if total_sent > 0 else 0.0
        overall_open_rate = round((total_opened / total_sent) * 100, 2) if total_sent > 0 else 0.0
        
        return {
            "success": True,
            "date_range": f"Last {days} days",
            "start_date": start_date.isoformat(),
            "end_date": datetime.utcnow().isoformat(),
            "domains": list(domain_metrics.values()),
            "overall_bounce_rate": overall_bounce_rate,
            "overall_complaint_rate": overall_complaint_rate,
            "overall_open_rate": overall_open_rate,
            "total_sent": total_sent
        }
    
    except Exception as e:
        logger.error(f"Error calculating reputation metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts", response_model=Dict[str, Any])
async def get_deliverability_alerts(
    resolved: Optional[bool] = Query(None, description="Filter by resolved status"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical, warning, info"),
    db=Depends(get_db)
):
    """
    Get active deliverability alerts.
    
    Alert types:
    - SPF failures
    - DKIM missing
    - High bounce rates (>5%)
    - Gmail quota exceeded
    - Domain reputation issues
    """
    try:
        # Build query
        query = {}
        if resolved is not None:
            query["resolved"] = resolved
        if severity:
            query["severity"] = severity
        
        # Get alerts from database
        alerts = list(db["deliverability_alerts"].find(query).sort("created_at", -1).limit(100))
        
        # Convert ObjectId to string
        for alert in alerts:
            alert["_id"] = str(alert["_id"])
            alert["alert_id"] = alert["_id"]
        
        # Generate alerts from current system state if no historical alerts
        if len(alerts) == 0:
            generated_alerts = []
            
            # Check domain health
            domains = db["domain_health"].find({})
            for domain_doc in domains:
                domain = domain_doc.get("domain")
                health_score = domain_doc.get("health_score", 0)
                
                if health_score < 50:
                    generated_alerts.append({
                        "alert_id": f"health_{domain}_{int(datetime.utcnow().timestamp())}",
                        "severity": "critical",
                        "type": "low_health_score",
                        "message": f"Domain {domain} has low health score: {health_score}/100",
                        "domain": domain,
                        "created_at": datetime.utcnow(),
                        "resolved": False
                    })
            
            # Check Gmail pool usage
            rate_limiter = RateLimitService(db)
            pool_stats = rate_limiter.get_pool_stats()
            
            if pool_stats["percentage_used"] > 90:
                generated_alerts.append({
                    "alert_id": f"pool_usage_{int(datetime.utcnow().timestamp())}",
                    "severity": "warning",
                    "type": "high_pool_usage",
                    "message": f"Gmail pool usage is at {pool_stats['percentage_used']}%",
                    "created_at": datetime.utcnow(),
                    "resolved": False
                })
            
            # Check for quota exceeded accounts
            for account in pool_stats["accounts"]:
                if account["status"] == "quota_exceeded":
                    generated_alerts.append({
                        "alert_id": f"quota_{account['account_id']}_{int(datetime.utcnow().timestamp())}",
                        "severity": "critical",
                        "type": "quota_exceeded",
                        "message": f"Gmail account {account['account_email']} has exceeded daily quota",
                        "account_email": account["account_email"],
                        "created_at": datetime.utcnow(),
                        "resolved": False
                    })
            
            alerts = generated_alerts
        
        return {
            "success": True,
            "total": len(alerts),
            "alerts": alerts
        }
    
    except Exception as e:
        logger.error(f"Error getting deliverability alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{alert_id}/resolve", response_model=Dict[str, Any])
async def resolve_alert(alert_id: str, db=Depends(get_db)):
    """
    Mark a deliverability alert as resolved.
    """
    try:
        from bson import ObjectId
        
        result = db["deliverability_alerts"].update_one(
            {"_id": ObjectId(alert_id)},
            {
                "$set": {
                    "resolved": True,
                    "resolved_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Alert not found")
        
        return {
            "success": True,
            "alert_id": alert_id,
            "message": "Alert resolved successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== BACKGROUND TASKS ==============

async def monitor_deliverability():
    """
    Background task to continuously monitor deliverability.
    Should be run periodically (e.g., every hour).
    """
    try:
        db = get_database("email_automation")
        service = DomainHealthService()
        
        # Get all monitored domains
        domains = set()
        gmail_accounts = db["gmail_accounts"].find({"status": "active"})
        for account in gmail_accounts:
            email = account.get("email", "")
            if "@" in email:
                domain = email.split("@")[1]
                domains.add(domain)
        
        # Check health for each domain
        for domain in domains:
            try:
                health_result = service.calculate_health_score(domain)
                
                # Store result
                db["domain_health"].update_one(
                    {"domain": domain},
                    {
                        "$set": {
                            "domain": domain,
                            "spf_status": health_result["spf"]["status"],
                            "dkim_status": "pass" if len(health_result["dkim"].get("valid_selectors", [])) > 0 else "fail",
                            "dmarc_status": health_result["dmarc"]["status"],
                            "health_score": health_result["score"],
                            "last_checked": datetime.utcnow()
                        }
                    },
                    upsert=True
                )
                
                # Create alert if health score is low
                if health_result["score"] < 50:
                    db["deliverability_alerts"].insert_one({
                        "severity": "critical",
                        "type": "low_health_score",
                        "message": f"Domain {domain} has low health score: {health_result['score']}/100",
                        "domain": domain,
                        "created_at": datetime.utcnow(),
                        "resolved": False
                    })
                
            except Exception as e:
                logger.error(f"Error checking health for {domain}: {e}")
        
        logger.info(f"Deliverability monitoring completed for {len(domains)} domains")
    
    except Exception as e:
        logger.error(f"Error in deliverability monitoring: {e}")
