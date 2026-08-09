"""
Global email suppression list manager.
Prevents sending emails to bounced, unsubscribed, or manually suppressed addresses.
"""
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Literal, Union
from pydantic import BaseModel, EmailStr, Field
from pymongo.database import Database

from leads.system_addresses import is_mailable

logger = logging.getLogger(__name__)

class SuppressionEntry(BaseModel):
    """Model for a suppression list entry."""
    email: str = Field(..., description="Email address (lowercase)")
    reason: Literal["unsubscribed", "bounced", "complaint", "manual"] = Field(..., description="Reason for suppression")
    source_campaign_id: Optional[str] = Field(None, description="Campaign that triggered suppression")
    suppressed_at: datetime = Field(default_factory=datetime.utcnow)
    suppressed_by: Optional[str] = Field(None, description="User ID or 'system'")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "reason": "unsubscribed",
                "source_campaign_id": "abc123",
                "suppressed_at": "2026-01-05T12:00:00Z",
                "suppressed_by": "system"
            }
        }


class SuppressionListManager:
    """
    Manages the global email suppression list.
    All emails are stored lowercase for case-insensitive matching.
    """
    
    COLLECTION_NAME = "suppression_list"
    
    def __init__(self, db: Database):
        self.db = db
        self.collection = db[self.COLLECTION_NAME]
    
    def ensure_indexes(self):
        """Create required indexes."""
        self.collection.create_index("email", unique=True)
        self.collection.create_index("reason")
        self.collection.create_index("suppressed_at")
        logger.info("Suppression list indexes ensured")
    
    def add(
        self,
        email: str,
        reason: Literal["unsubscribed", "bounced", "complaint", "manual"],
        source_campaign_id: Optional[str] = None,
        suppressed_by: Optional[str] = "system"
    ) -> bool:
        """
        Add an email to the suppression list.
        Returns True if added, False if already exists.
        """
        email_lower = email.lower().strip()
        
        try:
            entry = SuppressionEntry(
                email=email_lower,
                reason=reason,
                source_campaign_id=source_campaign_id,
                suppressed_at=datetime.utcnow(),
                suppressed_by=suppressed_by
            )
            
            self.collection.insert_one(entry.model_dump())
            logger.info(f"Email suppressed: {email_lower} (reason: {reason})")
            return True
            
        except Exception as e:
            if "duplicate key" in str(e).lower():
                logger.debug(f"Email already suppressed: {email_lower}")
                return False
            logger.error(f"Failed to add suppression: {e}")
            raise
    
    def remove(self, email: str, removed_by: Optional[str] = None) -> bool:
        """
        Remove an email from the suppression list.
        Returns True if removed, False if not found.
        Note: Consider adding to audit log before removing.
        """
        email_lower = email.lower().strip()
        
        result = self.collection.delete_one({"email": email_lower})
        
        if result.deleted_count > 0:
            logger.info(f"Suppression removed: {email_lower} (by: {removed_by})")
            return True
        return False
    
    def is_suppressed(self, email: str) -> bool:
        """Check if an email is suppressed.

        System addresses are suppressed implicitly, without needing a row.
        Mailing postmaster@ or a mailer-daemon achieves nothing and the reply
        is another bounce, so this holds even for an address that reached the
        send list some other way — the stored list only knows what has already
        gone wrong once.
        """
        if not is_mailable(email):
            return True
        email_lower = email.lower().strip()
        result = self.collection.find_one({"email": email_lower})
        return result is not None

    def bulk_check(self, emails: List[str]) -> Dict[str, bool]:
        """
        Check multiple emails for suppression status.
        Returns dict mapping email -> is_suppressed.
        Optimized for batch operations.
        """
        emails_lower = [e.lower().strip() for e in emails]

        # Find all suppressed emails in one query
        cursor = self.collection.find(
            {"email": {"$in": emails_lower}},
            {"email": 1}
        )
        suppressed_set = {doc["email"] for doc in cursor}

        return {
            email: (email in suppressed_set or not is_mailable(email))
            for email in emails_lower
        }
    
    def get_reason(self, email: str) -> Optional[str]:
        """Get the suppression reason for an email."""
        email_lower = email.lower().strip()
        result = self.collection.find_one({"email": email_lower})
        return result.get("reason") if result else None
    
    def get_entry(self, email: str) -> Optional[SuppressionEntry]:
        """Get full suppression entry for an email."""
        email_lower = email.lower().strip()
        result = self.collection.find_one({"email": email_lower})
        if result:
            result.pop("_id", None)
            return SuppressionEntry(**result)
        return None
    
    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        reason: Optional[str] = None
    ) -> List[SuppressionEntry]:
        """List suppressed emails with pagination."""
        query = {}
        if reason:
            query["reason"] = reason
        
        cursor = self.collection.find(query).skip(offset).limit(limit).sort("suppressed_at", -1)
        
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(SuppressionEntry(**doc))
        
        return results
    
    def count(self, reason: Optional[str] = None) -> int:
        """Count total suppressed emails."""
        query = {}
        if reason:
            query["reason"] = reason
        return self.collection.count_documents(query)


# Singleton instance holder
_suppression_manager: Optional[SuppressionListManager] = None

def get_suppression_manager(db: Database) -> SuppressionListManager:
    """Get or create the suppression list manager."""
    global _suppression_manager
    if _suppression_manager is None:
        _suppression_manager = SuppressionListManager(db)
        _suppression_manager.ensure_indexes()
    return _suppression_manager
