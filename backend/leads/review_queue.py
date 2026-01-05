"""
P1.6: Human Review Queue for Low-Confidence AI Classifications

Provides a queue system for AI classifications that fall below
the confidence threshold, requiring human review before acceptance.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Confidence threshold - classifications below this go to review queue
CONFIDENCE_THRESHOLD = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.7"))

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


class ReviewStatus(str, Enum):
    """Status of a review queue item."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class ReviewQueueItem(BaseModel):
    """Model for a review queue item."""
    entity_type: str = Field(..., description="Type: lead, email, rfq")
    entity_id: str = Field(..., description="ID of the entity")
    ai_classification: Dict[str, Any] = Field(..., description="AI classification result")
    confidence_score: float = Field(..., description="AI confidence score")
    status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    queued_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    human_classification: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class ReviewQueueService:
    """
    Service for managing the human review queue for low-confidence AI classifications.
    """
    
    def __init__(self, db=None):
        if db is None:
            client = MongoClient(MONGO_URI)
            self.db = client["email_automation"]
        else:
            self.db = db
        
        self.queue = self.db["ai_review_queue"]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Ensure required indexes exist."""
        try:
            self.queue.create_index([("status", 1), ("queued_at", -1)])
            self.queue.create_index("entity_type")
            self.queue.create_index([("entity_type", 1), ("entity_id", 1)])
        except Exception as e:
            logger.warning(f"Could not create indexes: {e}")
    
    def should_queue_for_review(self, confidence_score: float) -> bool:
        """Check if a classification should be queued for review."""
        return confidence_score < CONFIDENCE_THRESHOLD
    
    def add_to_queue(
        self,
        entity_type: str,
        entity_id: str,
        ai_classification: Dict[str, Any],
        confidence_score: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Add a low-confidence classification to the review queue.
        Returns the queue item ID if added, None if not needed.
        """
        if not self.should_queue_for_review(confidence_score):
            return None
        
        # Check if already in queue
        existing = self.queue.find_one({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": ReviewStatus.PENDING.value
        })
        
        if existing:
            # Update existing entry
            self.queue.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "ai_classification": ai_classification,
                        "confidence_score": confidence_score,
                        "queued_at": datetime.utcnow(),
                        "metadata": metadata or {}
                    }
                }
            )
            logger.info(f"Updated review queue item for {entity_type}/{entity_id}")
            return str(existing["_id"])
        
        # Insert new entry
        item = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "ai_classification": ai_classification,
            "confidence_score": confidence_score,
            "status": ReviewStatus.PENDING.value,
            "queued_at": datetime.utcnow(),
            "reviewed_at": None,
            "reviewed_by": None,
            "human_classification": None,
            "notes": None,
            "metadata": metadata or {}
        }
        
        result = self.queue.insert_one(item)
        logger.info(f"Added {entity_type}/{entity_id} to review queue (confidence: {confidence_score:.2f})")
        return str(result.inserted_id)
    
    def get_pending_items(
        self,
        entity_type: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        """Get pending review items, optionally filtered by entity type."""
        query = {"status": ReviewStatus.PENDING.value}
        if entity_type:
            query["entity_type"] = entity_type
        
        items = list(
            self.queue.find(query)
            .sort("queued_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        
        # Convert ObjectIds to strings
        for item in items:
            item["_id"] = str(item["_id"])
        
        return items
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get statistics about the review queue."""
        pipeline = [
            {
                "$group": {
                    "_id": {"status": "$status", "entity_type": "$entity_type"},
                    "count": {"$sum": 1},
                    "avg_confidence": {"$avg": "$confidence_score"}
                }
            }
        ]
        
        results = list(self.queue.aggregate(pipeline))
        
        stats = {
            "pending": {"total": 0, "by_type": {}},
            "approved": {"total": 0, "by_type": {}},
            "rejected": {"total": 0, "by_type": {}},
            "modified": {"total": 0, "by_type": {}}
        }
        
        for r in results:
            status = r["_id"]["status"]
            entity_type = r["_id"]["entity_type"]
            count = r["count"]
            
            if status in stats:
                stats[status]["total"] += count
                stats[status]["by_type"][entity_type] = {
                    "count": count,
                    "avg_confidence": round(r.get("avg_confidence", 0), 3)
                }
        
        stats["confidence_threshold"] = CONFIDENCE_THRESHOLD
        
        return stats
    
    def approve(
        self,
        queue_id: str,
        reviewed_by: str,
        notes: Optional[str] = None
    ) -> bool:
        """Approve the AI classification as-is."""
        return self._update_review(
            queue_id=queue_id,
            status=ReviewStatus.APPROVED,
            reviewed_by=reviewed_by,
            human_classification=None,
            notes=notes
        )
    
    def reject(
        self,
        queue_id: str,
        reviewed_by: str,
        notes: Optional[str] = None
    ) -> bool:
        """Reject the AI classification."""
        return self._update_review(
            queue_id=queue_id,
            status=ReviewStatus.REJECTED,
            reviewed_by=reviewed_by,
            human_classification=None,
            notes=notes
        )
    
    def modify(
        self,
        queue_id: str,
        reviewed_by: str,
        human_classification: Dict[str, Any],
        notes: Optional[str] = None
    ) -> bool:
        """Modify the AI classification with human corrections."""
        return self._update_review(
            queue_id=queue_id,
            status=ReviewStatus.MODIFIED,
            reviewed_by=reviewed_by,
            human_classification=human_classification,
            notes=notes
        )
    
    def _update_review(
        self,
        queue_id: str,
        status: ReviewStatus,
        reviewed_by: str,
        human_classification: Optional[Dict[str, Any]],
        notes: Optional[str]
    ) -> bool:
        """Internal method to update a review item."""
        try:
            result = self.queue.update_one(
                {"_id": ObjectId(queue_id), "status": ReviewStatus.PENDING.value},
                {
                    "$set": {
                        "status": status.value,
                        "reviewed_at": datetime.utcnow(),
                        "reviewed_by": reviewed_by,
                        "human_classification": human_classification,
                        "notes": notes
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Review queue item {queue_id} marked as {status.value}")
                return True
            
            logger.warning(f"Review queue item {queue_id} not found or already reviewed")
            return False
        except Exception as e:
            logger.error(f"Error updating review queue item: {e}")
            return False
    
    def get_item(self, queue_id: str) -> Optional[Dict[str, Any]]:
        """Get a single queue item by ID."""
        try:
            item = self.queue.find_one({"_id": ObjectId(queue_id)})
            if item:
                item["_id"] = str(item["_id"])
            return item
        except Exception as e:
            logger.error(f"Error getting review queue item: {e}")
            return None


# Singleton instance
_review_queue_service: Optional[ReviewQueueService] = None

def get_review_queue_service() -> ReviewQueueService:
    """Get or create the review queue service singleton."""
    global _review_queue_service
    if _review_queue_service is None:
        _review_queue_service = ReviewQueueService()
    return _review_queue_service
