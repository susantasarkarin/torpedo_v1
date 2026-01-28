"""
SEND QUEUE MANAGER
==================

Redis-backed queue for high-volume email sending with priority levels,
retry logic, and Celery integration.

Features:
- Priority-based queue (critical, high, normal, low)
- Exponential backoff retry mechanism
- Batch dequeuing for efficient processing
- Dead letter queue for persistent failures
- Celery worker integration
- Queue metrics and monitoring

Usage:
    from campaigns.send_queue import SendQueueManager
    
    queue = SendQueueManager()
    
    # Enqueue emails
    queue.enqueue_send({
        "to": "prospect@company.com",
        "subject": "Follow up",
        "body": "...",
        "campaign_id": "..."
    }, priority="high")
    
    # Worker dequeue
    sends = queue.dequeue_sends(batch_size=100)
    for send_data in sends:
        # Process send
        pass
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Literal
from redis import Redis
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Priority levels
PriorityLevel = Literal["critical", "high", "normal", "low"]

# Queue names
QUEUE_CRITICAL = "send_queue:critical"
QUEUE_HIGH = "send_queue:high"
QUEUE_NORMAL = "send_queue:normal"
QUEUE_LOW = "send_queue:low"
QUEUE_RETRY = "send_queue:retry"
QUEUE_DEAD_LETTER = "send_queue:dead_letter"

# Redis keys
KEY_SEND_COUNTER = "send_queue:counter"
KEY_PROCESSING = "send_queue:processing:{send_id}"
KEY_RETRY_COUNT = "send_queue:retry_count:{send_id}"


class SendQueueItem(BaseModel):
    """Individual send queue item"""
    send_id: str = Field(default_factory=lambda: f"send_{int(time.time() * 1000)}")
    
    # Email data
    to: str
    subject: str
    body_html: str
    body_plain: Optional[str] = None
    from_email: str
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    
    # Campaign context
    campaign_id: str
    recipient_id: Optional[str] = None
    sequence_step: Optional[int] = None
    template_id: Optional[str] = None
    
    # Tracking
    tracking_domain: Optional[str] = None
    track_opens: bool = True
    track_clicks: bool = True
    
    # Attachments
    attachments: List[Dict] = []
    
    # Metadata
    priority: PriorityLevel = "normal"
    enqueued_at: datetime = Field(default_factory=datetime.utcnow)
    scheduled_for: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    
    # Custom headers
    custom_headers: Dict[str, str] = {}


class SendQueueManager:
    """
    Manages high-volume email send queue with Redis backend
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Initialize queue manager
        
        Args:
            redis_url: Redis connection URL
        """
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.redis_binary = Redis.from_url(redis_url, decode_responses=False)
        
    def enqueue_send(
        self,
        email_data: Dict,
        priority: PriorityLevel = "normal",
        scheduled_for: Optional[datetime] = None
    ) -> str:
        """
        Add email to send queue
        
        Args:
            email_data: Email details (to, subject, body, etc.)
            priority: Queue priority level
            scheduled_for: Optional scheduled send time
            
        Returns:
            send_id: Unique identifier for this send
        """
        # Create queue item
        item = SendQueueItem(**email_data, priority=priority, scheduled_for=scheduled_for)
        
        # Select queue based on priority
        queue_name = self._get_queue_name(priority)
        
        # Calculate score (timestamp for FIFO within priority)
        if scheduled_for:
            score = scheduled_for.timestamp()
        else:
            score = time.time()
        
        # Add to sorted set (allows scheduled sends)
        self.redis.zadd(queue_name, {item.json(): score})
        
        # Increment counter
        self.redis.incr(KEY_SEND_COUNTER)
        
        logger.info(f"Enqueued send {item.send_id} with priority {priority}")
        return item.send_id
    
    def dequeue_sends(
        self,
        batch_size: int = 100,
        respect_schedule: bool = True
    ) -> List[SendQueueItem]:
        """
        Dequeue emails for sending (checks all priority queues)
        
        Args:
            batch_size: Maximum number of sends to dequeue
            respect_schedule: Only dequeue sends scheduled for now or earlier
            
        Returns:
            List of SendQueueItem objects ready for sending
        """
        current_time = time.time()
        results = []
        
        # Process queues in priority order
        for queue_name in [QUEUE_CRITICAL, QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW]:
            if len(results) >= batch_size:
                break
                
            remaining = batch_size - len(results)
            
            # Get items from this priority queue
            if respect_schedule:
                # Only get items scheduled for now or earlier
                items = self.redis.zrangebyscore(
                    queue_name,
                    0,
                    current_time,
                    start=0,
                    num=remaining,
                    withscores=False
                )
            else:
                # Get any items
                items = self.redis.zrange(
                    queue_name,
                    0,
                    remaining - 1,
                    withscores=False
                )
            
            # Remove from queue and add to results
            for item_json in items:
                # Remove from queue
                self.redis.zrem(queue_name, item_json)
                
                # Parse and add to results
                item = SendQueueItem.parse_raw(item_json)
                
                # Mark as processing
                self.redis.setex(
                    KEY_PROCESSING.format(send_id=item.send_id),
                    300,  # 5 minute timeout
                    "1"
                )
                
                results.append(item)
        
        logger.info(f"Dequeued {len(results)} sends for processing")
        return results
    
    def retry_failed(
        self,
        send_item: SendQueueItem,
        error_message: Optional[str] = None,
        max_retries: int = 3
    ) -> bool:
        """
        Retry failed send with exponential backoff
        
        Args:
            send_item: Original send item
            error_message: Error description
            max_retries: Maximum retry attempts
            
        Returns:
            True if requeued for retry, False if moved to dead letter
        """
        # Increment retry count
        retry_key = KEY_RETRY_COUNT.format(send_id=send_item.send_id)
        retry_count = self.redis.incr(retry_key)
        self.redis.expire(retry_key, 86400)  # 24 hour TTL
        
        send_item.retry_count = retry_count
        
        if retry_count <= max_retries:
            # Calculate exponential backoff delay
            # 1st retry: 5 min, 2nd: 15 min, 3rd: 45 min
            delay_minutes = 5 * (3 ** (retry_count - 1))
            scheduled_for = datetime.utcnow() + timedelta(minutes=delay_minutes)
            
            # Re-enqueue with original priority
            score = scheduled_for.timestamp()
            queue_name = self._get_queue_name(send_item.priority)
            self.redis.zadd(queue_name, {send_item.json(): score})
            
            logger.warning(
                f"Retry {retry_count}/{max_retries} for send {send_item.send_id}, "
                f"scheduled in {delay_minutes} minutes. Error: {error_message}"
            )
            return True
        else:
            # Move to dead letter queue
            self.redis.zadd(
                QUEUE_DEAD_LETTER,
                {json.dumps({
                    "send_item": send_item.dict(),
                    "error": error_message,
                    "failed_at": datetime.utcnow().isoformat(),
                    "retry_count": retry_count
                }): time.time()}
            )
            
            logger.error(
                f"Send {send_item.send_id} moved to dead letter queue after "
                f"{retry_count} retries. Error: {error_message}"
            )
            return False
    
    def mark_complete(self, send_id: str) -> None:
        """
        Mark send as successfully completed
        
        Args:
            send_id: Send identifier
        """
        # Remove processing marker
        self.redis.delete(KEY_PROCESSING.format(send_id=send_id))
        
        # Clear retry count
        self.redis.delete(KEY_RETRY_COUNT.format(send_id=send_id))
    
    def get_queue_stats(self) -> Dict[str, int]:
        """
        Get queue statistics
        
        Returns:
            Dictionary with queue lengths and metrics
        """
        return {
            "critical": self.redis.zcard(QUEUE_CRITICAL),
            "high": self.redis.zcard(QUEUE_HIGH),
            "normal": self.redis.zcard(QUEUE_NORMAL),
            "low": self.redis.zcard(QUEUE_LOW),
            "retry": self.redis.zcard(QUEUE_RETRY),
            "dead_letter": self.redis.zcard(QUEUE_DEAD_LETTER),
            "total_processed": int(self.redis.get(KEY_SEND_COUNTER) or 0)
        }
    
    def peek_queue(
        self,
        priority: PriorityLevel = "normal",
        limit: int = 10
    ) -> List[SendQueueItem]:
        """
        Peek at queue contents without removing items
        
        Args:
            priority: Priority queue to peek
            limit: Maximum items to return
            
        Returns:
            List of SendQueueItem objects
        """
        queue_name = self._get_queue_name(priority)
        items = self.redis.zrange(queue_name, 0, limit - 1)
        
        return [SendQueueItem.parse_raw(item) for item in items]
    
    def clear_queue(self, priority: Optional[PriorityLevel] = None) -> int:
        """
        Clear queue (for testing or emergency)
        
        Args:
            priority: Specific priority queue to clear, or None for all
            
        Returns:
            Number of items removed
        """
        if priority:
            queue_name = self._get_queue_name(priority)
            count = self.redis.zcard(queue_name)
            self.redis.delete(queue_name)
            logger.warning(f"Cleared {count} items from {priority} queue")
            return count
        else:
            total = 0
            for queue_name in [QUEUE_CRITICAL, QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW]:
                count = self.redis.zcard(queue_name)
                self.redis.delete(queue_name)
                total += count
            logger.warning(f"Cleared all queues: {total} total items")
            return total
    
    def requeue_from_dead_letter(
        self,
        send_id: str,
        priority: PriorityLevel = "low"
    ) -> bool:
        """
        Manually requeue a failed send from dead letter queue
        
        Args:
            send_id: Send identifier to requeue
            priority: New priority level
            
        Returns:
            True if requeued successfully
        """
        # Find in dead letter queue
        items = self.redis.zrange(QUEUE_DEAD_LETTER, 0, -1)
        
        for item_json in items:
            item_data = json.loads(item_json)
            if item_data.get("send_item", {}).get("send_id") == send_id:
                # Remove from dead letter
                self.redis.zrem(QUEUE_DEAD_LETTER, item_json)
                
                # Reset retry count and requeue
                send_item = SendQueueItem(**item_data["send_item"])
                send_item.retry_count = 0
                send_item.priority = priority
                
                queue_name = self._get_queue_name(priority)
                self.redis.zadd(queue_name, {send_item.json(): time.time()})
                
                # Clear retry counter
                self.redis.delete(KEY_RETRY_COUNT.format(send_id=send_id))
                
                logger.info(f"Requeued send {send_id} from dead letter with priority {priority}")
                return True
        
        logger.warning(f"Send {send_id} not found in dead letter queue")
        return False
    
    def _get_queue_name(self, priority: PriorityLevel) -> str:
        """Get Redis queue name for priority level"""
        queue_map = {
            "critical": QUEUE_CRITICAL,
            "high": QUEUE_HIGH,
            "normal": QUEUE_NORMAL,
            "low": QUEUE_LOW
        }
        return queue_map[priority]


# ============== CELERY TASK INTEGRATION ==============

def create_celery_send_task(celery_app):
    """
    Create Celery task for send queue processing
    
    Args:
        celery_app: Celery application instance
        
    Returns:
        Celery task function
    """
    
    @celery_app.task(name="campaigns.process_send_queue", bind=True, max_retries=3)
    def process_send_queue(self, batch_size: int = 100):
        """
        Celery task to process send queue
        
        Args:
            batch_size: Number of sends to process in this batch
        """
        from campaigns.email_sender import EmailSender
        
        queue = SendQueueManager()
        sender = EmailSender()
        
        # Dequeue batch
        sends = queue.dequeue_sends(batch_size=batch_size)
        
        if not sends:
            logger.info("No sends in queue")
            return {"processed": 0, "success": 0, "failed": 0}
        
        success_count = 0
        fail_count = 0
        
        for send_item in sends:
            try:
                # Send email
                result = sender.send(
                    to=send_item.to,
                    subject=send_item.subject,
                    body_html=send_item.body_html,
                    body_plain=send_item.body_plain,
                    from_email=send_item.from_email,
                    from_name=send_item.from_name,
                    reply_to=send_item.reply_to,
                    custom_headers=send_item.custom_headers
                )
                
                if result["success"]:
                    queue.mark_complete(send_item.send_id)
                    success_count += 1
                else:
                    # Retry with backoff
                    queue.retry_failed(send_item, result.get("error"))
                    fail_count += 1
                    
            except Exception as e:
                logger.error(f"Error sending {send_item.send_id}: {str(e)}")
                queue.retry_failed(send_item, str(e))
                fail_count += 1
        
        return {
            "processed": len(sends),
            "success": success_count,
            "failed": fail_count
        }
    
    return process_send_queue
