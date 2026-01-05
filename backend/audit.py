"""
Unified audit logging system for tracking all data changes.
Provides complete audit trail for compliance and debugging.

Uses synchronous pymongo to match the rest of the project.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field
from pymongo.database import Database

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """Model for an audit log entry."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = Field(None, description="User who performed the action")
    action: Literal["create", "update", "delete", "restore", "send", "classify"] = Field(..., description="Action performed")
    entity_type: str = Field(..., description="Type of entity (invoice, vendor, project, etc)")
    entity_id: str = Field(..., description="ID of the entity")
    changes: Optional[Dict[str, Any]] = Field(None, description="For updates: {field: {before, after}}")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    
    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2026-01-05T12:00:00Z",
                "user_id": "user123",
                "action": "update",
                "entity_type": "invoice",
                "entity_id": "inv123",
                "changes": {"amount": {"before": 100, "after": 150}},
                "metadata": {"reason": "Customer requested change"}
            }
        }


class AuditLogger:
    """
    Unified audit logger for all entity operations.
    Logs to MongoDB for persistence and queryability.
    """
    
    COLLECTION_NAME = "audit_log"
    
    def __init__(self, db: Database):
        self.db = db
        self.collection = db[self.COLLECTION_NAME]
    
    def ensure_indexes(self):
        """Create required indexes for efficient queries."""
        self.collection.create_index([
            ("entity_type", 1),
            ("entity_id", 1),
            ("timestamp", -1)
        ])
        self.collection.create_index("timestamp")
        self.collection.create_index("user_id")
        self.collection.create_index("action")
        logger.info("Audit log indexes ensured")
    
    def _log(self, entry: AuditEntry) -> str:
        """Internal method to insert audit entry."""
        try:
            result = self.collection.insert_one(entry.model_dump())
            logger.debug(f"Audit logged: {entry.action} {entry.entity_type}/{entry.entity_id}")
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Failed to log audit entry: {e}")
            # Don't raise - audit logging should not break main operations
            return ""
    
    def _sanitize_value(self, value: Any) -> Any:
        """Sanitize a single value for storage."""
        from bson import ObjectId
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return self._sanitize_data(value)
        if isinstance(value, list):
            return [self._sanitize_value(v) for v in value]
        return value
    
    def _sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize data for storage, converting ObjectIds and removing sensitive fields."""
        if not data:
            return {}
        
        sanitized = {}
        sensitive_fields = {"password", "token", "secret", "api_key", "credential"}
        
        for key, value in data.items():
            if key.lower() in sensitive_fields:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = self._sanitize_value(value)
        
        return sanitized
    
    def log_create(
        self,
        entity_type: str,
        entity_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log entity creation."""
        sanitized = self._sanitize_data(data)
        entry = AuditEntry(
            action="create",
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            changes={"created": sanitized},
            metadata=metadata or {}
        )
        return self._log(entry)
    
    def log_update(
        self,
        entity_type: str,
        entity_id: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log entity update with before/after comparison."""
        # Calculate changes
        changes = {}
        all_keys = set(before.keys()) | set(after.keys())
        for key in all_keys:
            if key.startswith("_"):  # Skip internal fields
                continue
            before_val = before.get(key)
            after_val = after.get(key)
            if before_val != after_val:
                changes[key] = {
                    "before": self._sanitize_value(before_val),
                    "after": self._sanitize_value(after_val)
                }
        
        if not changes:
            logger.debug(f"No changes detected for {entity_type}/{entity_id}")
            return ""
        
        entry = AuditEntry(
            action="update",
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            changes=changes,
            metadata=metadata or {}
        )
        return self._log(entry)
    
    def log_delete(
        self,
        entity_type: str,
        entity_id: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log entity deletion (soft or hard)."""
        entry = AuditEntry(
            action="delete",
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            metadata=metadata or {}
        )
        return self._log(entry)
    
    def log_restore(
        self,
        entity_type: str,
        entity_id: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log entity restoration from soft delete."""
        entry = AuditEntry(
            action="restore",
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            metadata=metadata or {}
        )
        return self._log(entry)
    
    def log_email_send(
        self,
        campaign_id: str,
        recipient_email: str,
        status: str,
        message_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log email send attempt."""
        entry = AuditEntry(
            action="send",
            entity_type="email",
            entity_id=campaign_id,
            user_id=user_id,
            metadata={
                "recipient_email": recipient_email,
                "status": status,
                "message_id": message_id,
                **(metadata or {})
            }
        )
        return self._log(entry)
    
    def log_ai_classification(
        self,
        entity_type: str,
        entity_id: str,
        classification: Dict[str, Any],
        confidence: float,
        model: str,
        duration_ms: int,
        user_id: Optional[str] = None
    ) -> str:
        """Log AI classification result."""
        entry = AuditEntry(
            action="classify",
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            metadata={
                "classification": classification,
                "confidence": confidence,
                "model": model,
                "duration_ms": duration_ms
            }
        )
        return self._log(entry)
    
    def get_history(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 100
    ) -> List[AuditEntry]:
        """Get audit history for a specific entity."""
        cursor = self.collection.find({
            "entity_type": entity_type,
            "entity_id": entity_id
        }).sort("timestamp", -1).limit(limit)
        
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(AuditEntry(**doc))
        
        return results
    
    def get_user_activity(
        self,
        user_id: str,
        limit: int = 100
    ) -> List[AuditEntry]:
        """Get all activity by a specific user."""
        cursor = self.collection.find({
            "user_id": user_id
        }).sort("timestamp", -1).limit(limit)
        
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(AuditEntry(**doc))
        
        return results
    
    def get_recent(
        self,
        entity_type: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditEntry]:
        """Get recent audit entries with optional filters."""
        query = {}
        if entity_type:
            query["entity_type"] = entity_type
        if action:
            query["action"] = action
        
        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)
        
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            results.append(AuditEntry(**doc))
        
        return results


# Singleton instance holder
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(db: Database) -> AuditLogger:
    """Get or create the audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(db)
        _audit_logger.ensure_indexes()
    return _audit_logger
