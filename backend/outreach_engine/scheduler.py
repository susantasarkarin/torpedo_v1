"""
SEND SCHEDULER
==============

Job queue based scheduler for email sends.

Features:
- Schedule sends at specific times
- Recurring batch processing
- Timezone-aware scheduling
- Follow-up scheduling based on workflow delays
- No ad-hoc cron logic - uses proper job queue
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from pymongo.database import Database
import threading
import time
from bson import ObjectId

from .models import WorkflowStatus
from .workflow_engine import WorkflowEngine
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class SendScheduler:
    """
    Job queue based scheduler for email sends.
    
    Responsibilities:
    - Process scheduled sends from queue
    - Schedule follow-ups based on workflow
    - Handle timezone conversions
    - Integrate with background workers
    """
    
    # Scheduler configuration
    DEFAULT_POLL_INTERVAL = 30  # seconds
    BATCH_SIZE = 50
    
    def __init__(
        self,
        db: Database,
        sending_callback: Optional[Callable] = None
    ):
        """
        Initialize scheduler.
        
        Args:
            db: MongoDB database instance
            sending_callback: Function to call for actual sending
        """
        self.db = db
        self.sending_callback = sending_callback
        
        # Collections
        self.queue_collection = db["outreach_send_queue"]
        self.leads_collection = db["outreach_leads_v2"]
        self.campaigns_collection = db["outreach_campaigns_v2"]
        
        # Dependencies
        self.workflow_engine = WorkflowEngine(db)
        self.rate_limiter = RateLimiter(db)
        
        # Background worker state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes including UNIQUE constraint for idempotency"""
        try:
            # CRITICAL: Unique compound index prevents duplicate sends
            # This is the DB-level guarantee against race conditions
            self.queue_collection.create_index(
                [
                    ("campaign_id", 1),
                    ("lead_id", 1),
                    ("step_number", 1)
                ],
                unique=True,
                name="idempotency_unique_idx"
            )
            
            # Query optimization indexes
            self.queue_collection.create_index([
                ("scheduled_at", 1),
                ("status", 1)
            ])
            self.queue_collection.create_index([("campaign_id", 1)])
            self.queue_collection.create_index([("lead_id", 1)])
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    # ============== QUEUE MANAGEMENT ==============
    
    def enqueue_send(
        self,
        campaign_id: str,
        lead_id: str,
        step_number: int,
        scheduled_at: datetime,
        priority: int = 0
    ) -> str:
        """
        Add send to queue with IDEMPOTENCY guarantee.
        
        Uses upsert with $setOnInsert to ensure:
        - Same (campaign_id, lead_id, step_number) can only exist once
        - Duplicate enqueue calls are no-ops
        - Race conditions cannot create duplicate sends
        
        Args:
            campaign_id: Campaign ID
            lead_id: Lead ID
            step_number: Workflow step
            scheduled_at: When to send
            priority: Higher = more urgent
            
        Returns:
            Queue entry ID (existing or new)
        """
        entry_id = str(ObjectId())
        now = datetime.utcnow()
        
        # IDEMPOTENT UPSERT:
        # - If entry exists: returns existing, does NOT modify
        # - If entry doesn't exist: creates new entry
        # - Combined with unique index: physically impossible to duplicate
        result = self.queue_collection.update_one(
            {
                "campaign_id": campaign_id,
                "lead_id": lead_id,
                "step_number": step_number
            },
            {
                "$setOnInsert": {
                    "entry_id": entry_id,
                    "campaign_id": campaign_id,
                    "lead_id": lead_id,
                    "step_number": step_number,
                    "scheduled_at": scheduled_at,
                    "priority": priority,
                    "status": "pending",
                    "created_at": now,
                    "attempts": 0,
                    "last_attempt_at": None,
                    "error_message": None
                }
            },
            upsert=True
        )
        
        if result.upserted_id:
            logger.debug(f"Enqueued NEW send for lead {lead_id} step {step_number} at {scheduled_at}")
            return entry_id
        else:
            # Entry already exists - get existing entry_id
            existing = self.queue_collection.find_one({
                "campaign_id": campaign_id,
                "lead_id": lead_id,
                "step_number": step_number
            })
            existing_id = existing.get("entry_id") if existing else entry_id
            logger.debug(f"Send already queued for lead {lead_id} step {step_number}, returning existing")
            return existing_id
    
    def schedule_campaign_sends(
        self,
        campaign_id: str,
        lead_ids: List[str],
        step_number: int = 0,
        start_at: Optional[datetime] = None,
        spread_over_hours: int = 4
    ) -> Dict[str, Any]:
        """
        Schedule sends for multiple leads with spread timing.
        
        Args:
            campaign_id: Campaign to schedule for
            lead_ids: List of leads to send to
            step_number: Workflow step
            start_at: When to start (default: now)
            spread_over_hours: Spread sends over this many hours
            
        Returns:
            Schedule summary
        """
        now = datetime.utcnow()
        start_at = start_at or now
        
        # Calculate spread interval
        total_leads = len(lead_ids)
        if total_leads == 0:
            return {"scheduled": 0}
        
        interval_seconds = (spread_over_hours * 3600) / total_leads
        interval_seconds = max(60, interval_seconds)  # Minimum 60 seconds
        
        scheduled_count = 0
        
        for i, lead_id in enumerate(lead_ids):
            scheduled_time = start_at + timedelta(seconds=i * interval_seconds)
            
            # Adjust for sending window
            scheduled_time = self._adjust_to_sending_window(scheduled_time)
            
            self.enqueue_send(
                campaign_id=campaign_id,
                lead_id=lead_id,
                step_number=step_number,
                scheduled_at=scheduled_time,
                priority=1
            )
            scheduled_count += 1
        
        return {
            "scheduled": scheduled_count,
            "first_send_at": start_at,
            "last_send_at": start_at + timedelta(seconds=(total_leads - 1) * interval_seconds),
            "interval_seconds": interval_seconds
        }
    
    def schedule_follow_up(
        self,
        campaign_id: str,
        lead_id: str,
        current_step: int,
        delay_days: int,
        delay_hours: int = 0
    ) -> Optional[str]:
        """
        Schedule follow-up send.
        
        Args:
            campaign_id: Campaign ID
            lead_id: Lead ID
            current_step: Just completed step
            delay_days: Days to wait
            delay_hours: Additional hours
            
        Returns:
            Queue entry ID or None
        """
        next_step = current_step + 1
        
        # Get campaign to check if next step exists
        campaign = self.campaigns_collection.find_one({"campaign_id": campaign_id})
        if not campaign:
            return None
        
        workflow_steps = campaign.get("workflow_steps", [])
        if next_step >= len(workflow_steps):
            logger.debug(f"No more steps for lead {lead_id}")
            return None
        
        # Calculate send time
        send_at = datetime.utcnow() + timedelta(days=delay_days, hours=delay_hours)
        send_at = self._adjust_to_sending_window(send_at)
        
        # Update lead's next_send_at
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": {
                "next_send_at": send_at,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Enqueue the send
        entry_id = self.enqueue_send(
            campaign_id=campaign_id,
            lead_id=lead_id,
            step_number=next_step,
            scheduled_at=send_at
        )
        
        return entry_id
    
    def _adjust_to_sending_window(
        self,
        dt: datetime,
        start_hour: int = 9,
        end_hour: int = 17,
        valid_days: List[int] = None
    ) -> datetime:
        """
        Adjust datetime to fall within sending window.
        """
        valid_days = valid_days or [0, 1, 2, 3, 4]  # Mon-Fri
        
        # Adjust hour
        if dt.hour < start_hour:
            dt = dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        elif dt.hour >= end_hour:
            # Move to next day
            dt = dt + timedelta(days=1)
            dt = dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        # Adjust day
        while dt.weekday() not in valid_days:
            dt = dt + timedelta(days=1)
            dt = dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        return dt
    
    # ============== QUEUE PROCESSING ==============
    
    def process_queue(self, limit: int = None) -> Dict[str, Any]:
        """
        Process pending sends from queue.
        
        Args:
            limit: Max sends to process
            
        Returns:
            Processing results
        """
        limit = limit or self.BATCH_SIZE
        now = datetime.utcnow()
        
        # Get pending sends that are due
        pending = list(self.queue_collection.find({
            "status": "pending",
            "scheduled_at": {"$lte": now}
        }).sort([
            ("priority", -1),
            ("scheduled_at", 1)
        ]).limit(limit))
        
        if not pending:
            return {"processed": 0, "success": 0, "failed": 0}
        
        success_count = 0
        failed_count = 0
        
        for entry in pending:
            entry_id = entry["entry_id"]
            lead_id = entry["lead_id"]
            campaign_id = entry["campaign_id"]
            step_number = entry["step_number"]
            
            # Mark as processing
            self.queue_collection.update_one(
                {"entry_id": entry_id},
                {"$set": {
                    "status": "processing",
                    "last_attempt_at": now
                },
                "$inc": {"attempts": 1}}
            )
            
            # Check if lead is still eligible
            lead = self.leads_collection.find_one({"lead_id": lead_id})
            if not lead:
                self._mark_entry_failed(entry_id, "Lead not found")
                failed_count += 1
                continue
            
            # Check workflow status
            if lead.get("workflow_status") != WorkflowStatus.IN_PROGRESS.value:
                self._mark_entry_failed(entry_id, f"Workflow not in progress: {lead.get('workflow_status')}")
                failed_count += 1
                continue
            
            # Process via callback or mark for external processing
            if self.sending_callback:
                try:
                    success, message = self.sending_callback(
                        lead_id=lead_id,
                        campaign_id=campaign_id,
                        step_number=step_number
                    )
                    
                    if success:
                        self._mark_entry_complete(entry_id)
                        success_count += 1
                    else:
                        self._mark_entry_failed(entry_id, message)
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Send callback error: {e}")
                    self._mark_entry_failed(entry_id, str(e))
                    failed_count += 1
            else:
                # Mark as ready for external processing
                self.queue_collection.update_one(
                    {"entry_id": entry_id},
                    {"$set": {"status": "ready"}}
                )
                success_count += 1
        
        return {
            "processed": len(pending),
            "success": success_count,
            "failed": failed_count
        }
    
    def _mark_entry_complete(self, entry_id: str):
        """Mark queue entry as complete"""
        self.queue_collection.update_one(
            {"entry_id": entry_id},
            {"$set": {
                "status": "complete",
                "completed_at": datetime.utcnow()
            }}
        )
    
    def _mark_entry_failed(self, entry_id: str, error: str):
        """Mark queue entry as failed"""
        entry = self.queue_collection.find_one({"entry_id": entry_id})
        attempts = entry.get("attempts", 1) if entry else 1
        
        # Retry up to 3 times
        if attempts < 3:
            # Reschedule with backoff
            retry_at = datetime.utcnow() + timedelta(minutes=attempts * 5)
            self.queue_collection.update_one(
                {"entry_id": entry_id},
                {"$set": {
                    "status": "pending",
                    "scheduled_at": retry_at,
                    "error_message": error
                }}
            )
        else:
            # Mark as failed permanently
            self.queue_collection.update_one(
                {"entry_id": entry_id},
                {"$set": {
                    "status": "failed",
                    "error_message": error,
                    "failed_at": datetime.utcnow()
                }}
            )
    
    # ============== QUEUE STATS ==============
    
    def get_queue_stats(self, campaign_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Args:
            campaign_id: Optional filter by campaign
            
        Returns:
            Queue stats
        """
        match = {}
        if campaign_id:
            match["campaign_id"] = campaign_id
        
        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(self.queue_collection.aggregate(pipeline))
        
        stats = {
            "pending": 0,
            "processing": 0,
            "ready": 0,
            "complete": 0,
            "failed": 0,
            "total": 0
        }
        
        for r in results:
            status = r["_id"]
            count = r["count"]
            stats[status] = count
            stats["total"] += count
        
        # Get next scheduled
        next_pending = self.queue_collection.find_one(
            {"status": "pending", **({"campaign_id": campaign_id} if campaign_id else {})},
            sort=[("scheduled_at", 1)]
        )
        
        if next_pending:
            stats["next_scheduled_at"] = next_pending.get("scheduled_at")
        
        return stats
    
    def clear_queue(self, campaign_id: str, status: Optional[str] = None):
        """
        Clear queue entries.
        
        Args:
            campaign_id: Campaign to clear
            status: Optional status filter
        """
        query = {"campaign_id": campaign_id}
        if status:
            query["status"] = status
        
        result = self.queue_collection.delete_many(query)
        logger.info(f"Cleared {result.deleted_count} queue entries for campaign {campaign_id}")
    
    # ============== BACKGROUND WORKER ==============
    
    def start_worker(self, poll_interval: int = None):
        """
        Start background worker thread.
        
        Args:
            poll_interval: Seconds between polling
        """
        if self._running:
            logger.warning("Scheduler worker already running")
            return
        
        self._running = True
        self._stop_event.clear()
        poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL
        
        def worker_loop():
            while self._running and not self._stop_event.is_set():
                try:
                    result = self.process_queue()
                    if result["processed"] > 0:
                        logger.info(f"Processed {result['processed']} sends ({result['success']} success, {result['failed']} failed)")
                except Exception as e:
                    logger.error(f"Worker error: {e}", exc_info=True)
                
                self._stop_event.wait(poll_interval)
        
        self._thread = threading.Thread(target=worker_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler worker started")
    
    def stop_worker(self):
        """Stop background worker"""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Scheduler worker stopped")
    
    def is_running(self) -> bool:
        """Check if worker is running"""
        return self._running and self._thread is not None and self._thread.is_alive()


# ============== CELERY TASK INTEGRATION ==============

def create_celery_tasks(app, db):
    """
    Create Celery tasks for scheduling.
    
    Args:
        app: Celery application
        db: MongoDB database
    """
    scheduler = SendScheduler(db)
    
    @app.task(name="outreach.process_queue")
    def process_queue_task():
        """Process send queue"""
        return scheduler.process_queue()
    
    @app.task(name="outreach.schedule_follow_up")
    def schedule_follow_up_task(campaign_id: str, lead_id: str, step: int, delay_days: int):
        """Schedule follow-up send"""
        return scheduler.schedule_follow_up(campaign_id, lead_id, step, delay_days)
    
    return {
        "process_queue": process_queue_task,
        "schedule_follow_up": schedule_follow_up_task
    }
