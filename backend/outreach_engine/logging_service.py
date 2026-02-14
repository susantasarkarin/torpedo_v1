"""
OUTREACH LOGGING SERVICE
========================

Comprehensive logging and observability for the outreach engine.

Logs per email send:
- Personalization level
- Mailbox used
- AI tokens used
- Message ID
- Thread ID
- Workflow step
- Status (sent, bounced, failed)

Logs errors:
- Bounce events
- Delivery failures
- Mailbox suspensions
- API errors

Provides:
- Real-time metrics
- Campaign analytics
- Error tracking
- AI usage tracking
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pymongo.database import Database
from collections import defaultdict

from .models import SendLogEntry, PersonalizationLevel, SendStatus

logger = logging.getLogger(__name__)


class OutreachLogger:
    """
    Logging service for outreach operations.
    
    Responsibilities:
    - Log all email sends with full context
    - Log errors and bounces
    - Track AI token usage
    - Provide analytics queries
    - Export for monitoring systems
    """
    
    def __init__(self, db: Database):
        """
        Initialize outreach logger.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.send_logs = db["outreach_send_logs"]
        self.error_logs = db["outreach_error_logs"]
        self.metrics = db["outreach_metrics"]
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            # Send logs indexes
            self.send_logs.create_index([("logged_at", -1)])
            self.send_logs.create_index([("campaign_id", 1), ("logged_at", -1)])
            self.send_logs.create_index([("mailbox_used", 1), ("logged_at", -1)])
            self.send_logs.create_index([("status", 1)])
            
            # Error logs indexes
            self.error_logs.create_index([("logged_at", -1)])
            self.error_logs.create_index([("error_type", 1)])
            
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    # ============== SEND LOGGING ==============
    
    def log_send(
        self,
        send_id: str,
        campaign_id: str,
        lead_id: str,
        personalization_level: PersonalizationLevel,
        mailbox_id: str,
        ai_tokens_used: int,
        message_id: str,
        thread_id: Optional[str],
        workflow_step: int,
        status: str,
        render_time_ms: int = 0,
        send_time_ms: int = 0,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> str:
        """
        Log an email send with full context.
        
        Returns:
            Log entry ID
        """
        from bson import ObjectId
        log_id = str(ObjectId())
        
        entry = {
            "log_id": log_id,
            "send_id": send_id,
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "personalization_level": personalization_level.value if isinstance(personalization_level, PersonalizationLevel) else personalization_level,
            "mailbox_used": mailbox_id,
            "ai_tokens_used": ai_tokens_used,
            "message_id": message_id,
            "thread_id": thread_id,
            "workflow_step": workflow_step,
            "status": status,
            "error_type": error_type,
            "error_message": error_message,
            "render_time_ms": render_time_ms,
            "send_time_ms": send_time_ms,
            "logged_at": datetime.utcnow()
        }
        
        self.send_logs.insert_one(entry)
        
        # Update metrics
        self._update_metrics(campaign_id, mailbox_id, status, ai_tokens_used)
        
        return log_id
    
    # ============== ERROR LOGGING ==============
    
    def log_error(
        self,
        error_type: str,
        campaign_id: Optional[str],
        lead_id: Optional[str],
        mailbox_id: Optional[str],
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log an error event.
        
        Error types:
        - bounce: Email bounced
        - delivery_failure: Failed to deliver
        - mailbox_suspension: Mailbox suspended
        - api_error: Provider API error
        - rate_limit: Rate limit exceeded
        - validation_error: Data validation failed
        
        Returns:
            Error log ID
        """
        from bson import ObjectId
        error_id = str(ObjectId())
        
        entry = {
            "error_id": error_id,
            "error_type": error_type,
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "mailbox_id": mailbox_id,
            "message": message,
            "details": details or {},
            "logged_at": datetime.utcnow()
        }
        
        self.error_logs.insert_one(entry)
        
        # Log to Python logger as well
        logger.error(f"[{error_type}] {message} (campaign={campaign_id}, lead={lead_id})")
        
        return error_id
    
    def log_bounce(
        self,
        campaign_id: str,
        lead_id: str,
        mailbox_id: str,
        message_id: str,
        bounce_type: str,
        bounce_reason: Optional[str] = None
    ) -> str:
        """Log bounce event"""
        return self.log_error(
            error_type="bounce",
            campaign_id=campaign_id,
            lead_id=lead_id,
            mailbox_id=mailbox_id,
            message=f"Email bounced ({bounce_type}): {bounce_reason}",
            details={
                "message_id": message_id,
                "bounce_type": bounce_type,
                "bounce_reason": bounce_reason
            }
        )
    
    def log_mailbox_suspension(
        self,
        mailbox_id: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log mailbox suspension"""
        return self.log_error(
            error_type="mailbox_suspension",
            campaign_id=None,
            lead_id=None,
            mailbox_id=mailbox_id,
            message=f"Mailbox suspended: {reason}",
            details=details
        )
    
    def log_api_error(
        self,
        campaign_id: Optional[str],
        mailbox_id: str,
        provider: str,
        error_message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log API error"""
        return self.log_error(
            error_type="api_error",
            campaign_id=campaign_id,
            lead_id=None,
            mailbox_id=mailbox_id,
            message=f"{provider} API error: {error_message}",
            details={"provider": provider, **(details or {})}
        )
    
    # ============== METRICS ==============
    
    def _update_metrics(
        self,
        campaign_id: str,
        mailbox_id: str,
        status: str,
        ai_tokens: int
    ):
        """
        Update real-time metrics.
        """
        now = datetime.utcnow()
        hour_key = now.strftime("%Y-%m-%d-%H")
        
        # Update hourly metrics
        self.metrics.update_one(
            {
                "type": "hourly",
                "hour": hour_key,
                "campaign_id": campaign_id
            },
            {
                "$inc": {
                    f"status.{status}": 1,
                    "total_sends": 1,
                    "ai_tokens_used": ai_tokens
                },
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True
        )
        
        # Update mailbox metrics
        self.metrics.update_one(
            {
                "type": "mailbox_hourly",
                "hour": hour_key,
                "mailbox_id": mailbox_id
            },
            {
                "$inc": {
                    f"status.{status}": 1,
                    "total_sends": 1
                }
            },
            upsert=True
        )
    
    # ============== ANALYTICS QUERIES ==============
    
    def get_campaign_stats(
        self,
        campaign_id: str,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get campaign statistics for time period.
        
        Args:
            campaign_id: Campaign to query
            hours: Hours to look back
            
        Returns:
            Campaign statistics
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        pipeline = [
            {"$match": {
                "campaign_id": campaign_id,
                "logged_at": {"$gte": since}
            }},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "ai_tokens": {"$sum": "$ai_tokens_used"},
                "avg_send_time_ms": {"$avg": "$send_time_ms"}
            }}
        ]
        
        results = list(self.send_logs.aggregate(pipeline))
        
        # Build stats dict
        stats = {
            "campaign_id": campaign_id,
            "period_hours": hours,
            "total_sends": 0,
            "sent": 0,
            "bounced": 0,
            "failed": 0,
            "ai_tokens_used": 0,
            "avg_send_time_ms": 0,
            "by_status": {}
        }
        
        total_time = 0
        count = 0
        
        for r in results:
            status = r["_id"]
            c = r["count"]
            stats["total_sends"] += c
            stats["by_status"][status] = c
            stats["ai_tokens_used"] += r.get("ai_tokens", 0)
            
            if r.get("avg_send_time_ms"):
                total_time += r["avg_send_time_ms"] * c
                count += c
            
            if status == "sent":
                stats["sent"] = c
            elif status == "bounced":
                stats["bounced"] = c
            elif status == "failed":
                stats["failed"] = c
        
        if count > 0:
            stats["avg_send_time_ms"] = round(total_time / count, 2)
        
        # Calculate rates
        if stats["total_sends"] > 0:
            stats["bounce_rate"] = round(stats["bounced"] / stats["total_sends"], 4)
            stats["failure_rate"] = round(stats["failed"] / stats["total_sends"], 4)
        
        return stats
    
    def get_mailbox_stats(
        self,
        mailbox_id: str,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get mailbox performance statistics.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        pipeline = [
            {"$match": {
                "mailbox_used": mailbox_id,
                "logged_at": {"$gte": since}
            }},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(self.send_logs.aggregate(pipeline))
        
        stats = {
            "mailbox_id": mailbox_id,
            "period_hours": hours,
            "total_sends": 0,
            "sent": 0,
            "bounced": 0,
            "failed": 0,
            "bounce_rate": 0
        }
        
        for r in results:
            status = r["_id"]
            count = r["count"]
            stats["total_sends"] += count
            
            if status == "sent":
                stats["sent"] = count
            elif status == "bounced":
                stats["bounced"] = count
            elif status == "failed":
                stats["failed"] = count
        
        if stats["total_sends"] > 0:
            stats["bounce_rate"] = round(stats["bounced"] / stats["total_sends"], 4)
        
        return stats
    
    def get_ai_usage_stats(
        self,
        campaign_id: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get AI token usage statistics.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        match_stage: Dict[str, Any] = {"logged_at": {"$gte": since}}
        if campaign_id:
            match_stage["campaign_id"] = campaign_id
        
        pipeline = [
            {"$match": match_stage},
            {"$group": {
                "_id": "$personalization_level",
                "count": {"$sum": 1},
                "total_tokens": {"$sum": "$ai_tokens_used"},
                "avg_tokens": {"$avg": "$ai_tokens_used"},
                "max_tokens": {"$max": "$ai_tokens_used"}
            }}
        ]
        
        results = list(self.send_logs.aggregate(pipeline))
        
        stats = {
            "period_hours": hours,
            "campaign_id": campaign_id,
            "total_ai_tokens": 0,
            "by_level": {}
        }
        
        for r in results:
            level = r["_id"]
            stats["by_level"][level] = {
                "sends": r["count"],
                "total_tokens": r.get("total_tokens", 0),
                "avg_tokens": round(r.get("avg_tokens", 0), 2),
                "max_tokens": r.get("max_tokens", 0)
            }
            stats["total_ai_tokens"] += r.get("total_tokens", 0)
        
        return stats
    
    def get_error_summary(
        self,
        hours: int = 24,
        campaign_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get error summary for monitoring.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        match_stage: Dict[str, Any] = {"logged_at": {"$gte": since}}
        if campaign_id:
            match_stage["campaign_id"] = campaign_id
        
        pipeline = [
            {"$match": match_stage},
            {"$group": {
                "_id": "$error_type",
                "count": {"$sum": 1},
                "recent": {"$max": "$logged_at"}
            }}
        ]
        
        results = list(self.error_logs.aggregate(pipeline))
        
        summary = {
            "period_hours": hours,
            "campaign_id": campaign_id,
            "total_errors": 0,
            "by_type": {}
        }
        
        for r in results:
            error_type = r["_id"]
            count = r["count"]
            summary["total_errors"] += count
            summary["by_type"][error_type] = {
                "count": count,
                "most_recent": r.get("recent")
            }
        
        return summary
    
    def get_recent_errors(
        self,
        limit: int = 50,
        error_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent error logs.
        """
        query: Dict[str, Any] = {}
        if error_type:
            query["error_type"] = error_type
        
        errors = list(
            self.error_logs.find(query)
            .sort("logged_at", -1)
            .limit(limit)
        )
        
        # Clean up for JSON serialization
        for e in errors:
            e.pop("_id", None)
        
        return errors
    
    def get_hourly_send_trend(
        self,
        campaign_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get hourly send trend for charting.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        
        pipeline = [
            {"$match": {
                "campaign_id": campaign_id,
                "logged_at": {"$gte": since}
            }},
            {"$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d %H:00",
                        "date": "$logged_at"
                    }
                },
                "sent": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
                "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        results = list(self.send_logs.aggregate(pipeline))
        
        return [
            {
                "hour": r["_id"],
                "sent": r["sent"],
                "bounced": r["bounced"],
                "failed": r["failed"]
            }
            for r in results
        ]
    
    # ============== EXPORT ==============
    
    def export_logs(
        self,
        campaign_id: str,
        start_date: datetime,
        end_date: datetime,
        format: str = "json"
    ) -> List[Dict[str, Any]]:
        """
        Export logs for external analysis.
        
        Args:
            campaign_id: Campaign to export
            start_date: Start of period
            end_date: End of period
            format: Output format (json, csv)
            
        Returns:
            List of log entries
        """
        logs = list(
            self.send_logs.find({
                "campaign_id": campaign_id,
                "logged_at": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }).sort("logged_at", 1)
        )
        
        # Clean up for export
        for log in logs:
            log.pop("_id", None)
            # Convert datetime to ISO string
            if "logged_at" in log:
                log["logged_at"] = log["logged_at"].isoformat()
        
        return logs
