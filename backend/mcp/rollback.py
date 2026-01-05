# backend/mcp/rollback.py
# Rollback mechanism for MCP actions

from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from bson import ObjectId
from pymongo.database import Database

from .models import (
    MCPAction,
    ActionType,
    EntityType,
    ActionStatus,
    RollbackInfo,
)


class RollbackError(Exception):
    """Error during rollback operation"""
    def __init__(self, message: str, action_id: str):
        self.message = message
        self.action_id = action_id
        super().__init__(message)


class RollbackManager:
    """
    Manages rollback operations for MCP actions.
    
    Supports:
    - Capturing state before action execution
    - Rolling back individual actions
    - Rolling back batches (transactions)
    - Rollback history tracking
    """
    
    ACTIONS_COLLECTION = "mcp_actions"
    ROLLBACK_HISTORY_COLLECTION = "mcp_rollback_history"
    
    # Entity type to collection mapping
    ENTITY_COLLECTIONS = {
        EntityType.INVOICE.value: ("finance_db", "invoices"),
        EntityType.BILL.value: ("finance_db", "bills"),
        EntityType.PAYMENT.value: ("finance_db", "payments_received"),
        EntityType.EXPENSE.value: ("finance_db", "expenses"),
        EntityType.LEAD.value: ("email_automation", "leads"),
        EntityType.CONTACT.value: ("email_automation", "contacts"),
        EntityType.DEAL.value: ("email_automation", "deals"),
        EntityType.RFQ.value: ("email_automation", "rfqs"),
        EntityType.PROJECT.value: ("torpedo_settings", "projects"),
        EntityType.TASK.value: ("torpedo_settings", "tasks"),
        EntityType.TICKET.value: ("torpedo_settings", "tickets"),
        EntityType.USER.value: ("torpedo_settings", "users"),
        EntityType.VENDOR.value: ("finance_db", "vendors"),
        EntityType.CUSTOMER.value: ("finance_db", "customers"),
    }
    
    def __init__(self, client):
        """Initialize with MongoDB client"""
        self.client = client
        self.settings_db = client["torpedo_settings"]
        self.actions_collection = self.settings_db[self.ACTIONS_COLLECTION]
        self.rollback_history = self.settings_db[self.ROLLBACK_HISTORY_COLLECTION]
    
    def capture_state(self, entity_type: EntityType, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Capture the current state of an entity before modification.
        Returns None for create operations (no previous state).
        """
        if not entity_id:
            return None
        
        db_name, collection_name = self.ENTITY_COLLECTIONS.get(
            entity_type.value, 
            ("torpedo_settings", entity_type.value + "s")
        )
        
        db = self.client[db_name]
        collection = db[collection_name]
        
        try:
            doc = collection.find_one({"_id": ObjectId(entity_id)})
            if doc:
                # Convert ObjectId to string for storage
                doc["_id"] = str(doc["_id"])
                return doc
            return None
        except Exception as e:
            print(f"⚠️ Failed to capture state for {entity_type}/{entity_id}: {e}")
            return None
    
    def create_rollback_info(
        self,
        action: MCPAction,
        previous_state: Optional[Dict[str, Any]] = None,
        created_entity_id: Optional[str] = None,
    ) -> RollbackInfo:
        """Create rollback info for an action"""
        return RollbackInfo(
            action_id=action.id,
            entity_type=action.payload.entity_type,
            entity_id=action.payload.entity_id or created_entity_id or "",
            action_type=action.payload.action_type,
            previous_state=previous_state,
            created_entity_id=created_entity_id,
            is_rolled_back=False,
        )
    
    def can_rollback(self, action: MCPAction) -> Tuple[bool, str]:
        """
        Check if an action can be rolled back.
        Returns (can_rollback, reason)
        """
        if action.status != ActionStatus.COMPLETED:
            return False, "Only completed actions can be rolled back"
        
        if not action.rollback_info:
            return False, "No rollback information available"
        
        if action.rollback_info.is_rolled_back:
            return False, "Action has already been rolled back"
        
        # Check time limit (e.g., 24 hours)
        if action.completed_at:
            hours_since = (datetime.utcnow() - action.completed_at).total_seconds() / 3600
            if hours_since > 24:
                return False, "Rollback window has expired (24 hours)"
        
        # Check for dependent actions
        dependent_actions = self._find_dependent_actions(action)
        if dependent_actions:
            return False, f"Action has {len(dependent_actions)} dependent action(s) that must be rolled back first"
        
        return True, "Action can be rolled back"
    
    def rollback(self, action: MCPAction, user_id: str) -> MCPAction:
        """
        Rollback a completed action.
        Returns the updated action with rollback status.
        """
        can_rb, reason = self.can_rollback(action)
        if not can_rb:
            raise RollbackError(reason, action.id)
        
        rollback_info = action.rollback_info
        entity_type = rollback_info.entity_type.value
        
        db_name, collection_name = self.ENTITY_COLLECTIONS.get(
            entity_type,
            ("torpedo_settings", entity_type + "s")
        )
        
        db = self.client[db_name]
        collection = db[collection_name]
        
        try:
            if rollback_info.action_type == ActionType.CREATE:
                # Delete the created entity
                if rollback_info.created_entity_id:
                    collection.delete_one({"_id": ObjectId(rollback_info.created_entity_id)})
            
            elif rollback_info.action_type == ActionType.DELETE:
                # Restore the deleted entity
                if rollback_info.previous_state:
                    restore_doc = dict(rollback_info.previous_state)
                    restore_doc["_id"] = ObjectId(restore_doc["_id"])
                    restore_doc["restored_at"] = datetime.utcnow()
                    restore_doc["is_deleted"] = False
                    collection.insert_one(restore_doc)
            
            elif rollback_info.action_type in [ActionType.UPDATE, ActionType.APPROVE, ActionType.REJECT]:
                # Restore previous state
                if rollback_info.previous_state and rollback_info.entity_id:
                    previous = dict(rollback_info.previous_state)
                    entity_id = previous.pop("_id", rollback_info.entity_id)
                    previous["rolled_back_at"] = datetime.utcnow()
                    collection.update_one(
                        {"_id": ObjectId(entity_id)},
                        {"$set": previous}
                    )
            
            # Update rollback info
            now = datetime.utcnow()
            rollback_info.is_rolled_back = True
            rollback_info.rolled_back_at = now
            rollback_info.rolled_back_by = user_id
            
            # Update action status
            action.status = ActionStatus.ROLLED_BACK
            action.rollback_info = rollback_info
            action.audit_log.append({
                "event": "rolled_back",
                "user_id": user_id,
                "timestamp": now.isoformat(),
            })
            
            # Persist changes
            self._update_action(action)
            
            # Record in rollback history
            self._record_rollback(action, user_id)
            
            return action
            
        except Exception as e:
            raise RollbackError(f"Rollback failed: {str(e)}", action.id)
    
    def rollback_batch(
        self,
        action_ids: List[str],
        user_id: str,
    ) -> Tuple[List[MCPAction], List[str]]:
        """
        Rollback a batch of actions in reverse order.
        Returns (rolled_back_actions, failed_action_ids)
        """
        rolled_back = []
        failed = []
        
        # Sort actions by execution time (most recent first)
        actions = []
        for action_id in action_ids:
            doc = self.actions_collection.find_one({"_id": ObjectId(action_id)})
            if doc:
                doc["id"] = str(doc.pop("_id"))
                actions.append(MCPAction(**doc))
        
        actions.sort(key=lambda a: a.executed_at or datetime.min, reverse=True)
        
        for action in actions:
            try:
                rolled_back_action = self.rollback(action, user_id)
                rolled_back.append(rolled_back_action)
            except RollbackError as e:
                failed.append(action.id)
                print(f"⚠️ Failed to rollback {action.id}: {e.message}")
        
        return rolled_back, failed
    
    def _find_dependent_actions(self, action: MCPAction) -> List[str]:
        """Find actions that depend on this action's result"""
        if not action.result or not action.result.entity_id:
            return []
        
        # Look for actions that reference this entity
        dependent = self.actions_collection.find({
            "status": ActionStatus.COMPLETED.value,
            "rollback_info.is_rolled_back": False,
            "created_at": {"$gt": action.created_at},
            "$or": [
                {"payload.entity_id": action.result.entity_id},
                {"payload.data.related_entity_id": action.result.entity_id},
            ]
        })
        
        return [str(d["_id"]) for d in dependent]
    
    def _update_action(self, action: MCPAction):
        """Update action in database"""
        doc = action.model_dump()
        doc.pop("id", None)
        self.actions_collection.update_one(
            {"_id": ObjectId(action.id)},
            {"$set": doc}
        )
    
    def _record_rollback(self, action: MCPAction, user_id: str):
        """Record rollback in history"""
        self.rollback_history.insert_one({
            "action_id": action.id,
            "entity_type": action.payload.entity_type.value,
            "entity_id": action.rollback_info.entity_id,
            "action_type": action.payload.action_type.value,
            "rolled_back_by": user_id,
            "rolled_back_at": datetime.utcnow(),
            "previous_state_snapshot": action.rollback_info.previous_state,
        })
    
    def get_rollback_history(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get rollback history with optional filters"""
        query = {}
        if entity_type:
            query["entity_type"] = entity_type
        if entity_id:
            query["entity_id"] = entity_id
        if user_id:
            query["rolled_back_by"] = user_id
        
        total = self.rollback_history.count_documents(query)
        cursor = self.rollback_history.find(query).sort("rolled_back_at", -1).skip(skip).limit(limit)
        
        history = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            history.append(doc)
        
        return history, total


# Singleton instance
_rollback_manager: Optional[RollbackManager] = None


def get_rollback_manager(client) -> RollbackManager:
    """Get or create rollback manager instance"""
    global _rollback_manager
    if _rollback_manager is None:
        _rollback_manager = RollbackManager(client)
    return _rollback_manager
