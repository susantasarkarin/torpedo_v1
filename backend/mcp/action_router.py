# backend/mcp/action_router.py
# Central MCP Action Router - Orchestrates all controlled writes

import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple, Callable
from bson import ObjectId
from pymongo import MongoClient

from .models import (
    MCPAction,
    MCPActionCreate,
    MCPActionBatch,
    ActionPayload,
    ActionResult,
    ActionStatus,
    ActionType,
    EntityType,
    DryRunResult,
    ValidationResult,
)
from .validators import get_validator, ActionValidator
from .rollback import get_rollback_manager, RollbackManager

# Import approval engine if available
try:
    from ..workflows import get_approval_engine, ApprovalRequestCreate
except ImportError:
    get_approval_engine = None
    ApprovalRequestCreate = None


class ActionExecutor:
    """Executes actions on entities"""
    
    # Entity type to (db_name, collection_name) mapping
    ENTITY_COLLECTIONS = {
        EntityType.INVOICE: ("finance_db", "invoices"),
        EntityType.BILL: ("finance_db", "bills"),
        EntityType.PAYMENT: ("finance_db", "payments_received"),
        EntityType.EXPENSE: ("finance_db", "expenses"),
        EntityType.LEAD: ("email_automation", "leads"),
        EntityType.CONTACT: ("email_automation", "contacts"),
        EntityType.DEAL: ("email_automation", "deals"),
        EntityType.RFQ: ("email_automation", "rfqs"),
        EntityType.PROJECT: ("torpedo_settings", "projects"),
        EntityType.TASK: ("torpedo_settings", "tasks"),
        EntityType.TICKET: ("torpedo_settings", "tickets"),
        EntityType.USER: ("torpedo_settings", "users"),
        EntityType.VENDOR: ("finance_db", "vendors"),
        EntityType.CUSTOMER: ("finance_db", "customers"),
    }
    
    def __init__(self, client: MongoClient):
        self.client = client
    
    def get_collection(self, entity_type: EntityType):
        """Get MongoDB collection for entity type"""
        db_name, collection_name = self.ENTITY_COLLECTIONS.get(
            entity_type,
            ("torpedo_settings", entity_type.value + "s")
        )
        return self.client[db_name][collection_name]
    
    def execute(self, action: MCPAction) -> ActionResult:
        """Execute an action and return the result"""
        payload = action.payload
        collection = self.get_collection(payload.entity_type)
        
        try:
            if payload.action_type == ActionType.CREATE:
                return self._execute_create(collection, payload, action)
            elif payload.action_type == ActionType.UPDATE:
                return self._execute_update(collection, payload, action)
            elif payload.action_type == ActionType.DELETE:
                return self._execute_delete(collection, payload, action)
            elif payload.action_type == ActionType.APPROVE:
                return self._execute_approve(collection, payload, action)
            elif payload.action_type == ActionType.REJECT:
                return self._execute_reject(collection, payload, action)
            elif payload.action_type == ActionType.ASSIGN:
                return self._execute_assign(collection, payload, action)
            elif payload.action_type == ActionType.CONVERT:
                return self._execute_convert(collection, payload, action)
            elif payload.action_type == ActionType.ARCHIVE:
                return self._execute_archive(collection, payload, action)
            elif payload.action_type == ActionType.RESTORE:
                return self._execute_restore(collection, payload, action)
            else:
                return ActionResult(
                    success=False,
                    action_id=action.id,
                    entity_type=payload.entity_type,
                    action_type=payload.action_type,
                    error_message=f"Unsupported action type: {payload.action_type}",
                    error_code="UNSUPPORTED_ACTION",
                )
        except Exception as e:
            return ActionResult(
                success=False,
                action_id=action.id,
                entity_type=payload.entity_type,
                action_type=payload.action_type,
                error_message=str(e),
                error_code="EXECUTION_ERROR",
            )
    
    def _execute_create(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute create action"""
        doc = dict(payload.data)
        doc["created_at"] = datetime.utcnow()
        doc["updated_at"] = datetime.utcnow()
        doc["created_by"] = action.initiated_by
        
        result = collection.insert_one(doc)
        entity_id = str(result.inserted_id)
        
        return ActionResult(
            success=True,
            action_id=action.id,
            entity_id=entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            result_data={"_id": entity_id, **doc},
            can_rollback=True,
        )
    
    def _execute_update(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute update action"""
        update_data = dict(payload.data)
        update_data["updated_at"] = datetime.utcnow()
        update_data["updated_by"] = action.initiated_by
        
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            return ActionResult(
                success=False,
                action_id=action.id,
                entity_id=payload.entity_id,
                entity_type=payload.entity_type,
                action_type=payload.action_type,
                error_message="Entity not found",
                error_code="NOT_FOUND",
            )
        
        return ActionResult(
            success=True,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            result_data=update_data,
            can_rollback=True,
        )
    
    def _execute_delete(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute soft delete action"""
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": action.initiated_by,
                }
            }
        )
        
        if result.matched_count == 0:
            return ActionResult(
                success=False,
                action_id=action.id,
                entity_id=payload.entity_id,
                entity_type=payload.entity_type,
                action_type=payload.action_type,
                error_message="Entity not found",
                error_code="NOT_FOUND",
            )
        
        return ActionResult(
            success=True,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            can_rollback=True,
        )
    
    def _execute_approve(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute approve action"""
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {
                "$set": {
                    "status": "approved",
                    "approved_at": datetime.utcnow(),
                    "approved_by": action.initiated_by,
                    "approval_comment": payload.data.get("comment"),
                }
            }
        )
        
        return ActionResult(
            success=result.matched_count > 0,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            can_rollback=True,
        )
    
    def _execute_reject(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute reject action"""
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {
                "$set": {
                    "status": "rejected",
                    "rejected_at": datetime.utcnow(),
                    "rejected_by": action.initiated_by,
                    "rejection_reason": payload.data.get("reason"),
                }
            }
        )
        
        return ActionResult(
            success=result.matched_count > 0,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            can_rollback=True,
        )
    
    def _execute_assign(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute assign action"""
        assign_data = {
            "assigned_to": payload.data.get("assigned_to"),
            "assigned_at": datetime.utcnow(),
            "assigned_by": action.initiated_by,
        }
        
        # Handle team_members for projects
        if "team_members" in payload.data:
            assign_data["team_members"] = payload.data["team_members"]
        
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {"$set": assign_data}
        )
        
        return ActionResult(
            success=result.matched_count > 0,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            can_rollback=True,
        )
    
    def _execute_convert(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute convert action (e.g., lead to contact)"""
        # Get the source entity
        source = collection.find_one({"_id": ObjectId(payload.entity_id)})
        if not source:
            return ActionResult(
                success=False,
                action_id=action.id,
                entity_id=payload.entity_id,
                entity_type=payload.entity_type,
                action_type=payload.action_type,
                error_message="Source entity not found",
                error_code="NOT_FOUND",
            )
        
        created_entities = {}
        
        # For lead conversion
        if payload.entity_type == EntityType.LEAD:
            if payload.data.get("create_contact", True):
                contacts_collection = self.client["email_automation"]["contacts"]
                contact_doc = {
                    "name": source.get("name"),
                    "email": source.get("email"),
                    "phone": source.get("phone"),
                    "company": source.get("company"),
                    "source_lead_id": str(source["_id"]),
                    "created_at": datetime.utcnow(),
                    "created_by": action.initiated_by,
                }
                contact_result = contacts_collection.insert_one(contact_doc)
                created_entities["contact_id"] = str(contact_result.inserted_id)
            
            if payload.data.get("create_deal", False):
                deals_collection = self.client["email_automation"]["deals"]
                deal_doc = {
                    "name": f"Deal - {source.get('company', source.get('name', 'Unknown'))}",
                    "contact_id": created_entities.get("contact_id"),
                    "source_lead_id": str(source["_id"]),
                    "value": payload.data.get("deal_value", 0),
                    "stage": "prospect",
                    "created_at": datetime.utcnow(),
                    "created_by": action.initiated_by,
                }
                deal_result = deals_collection.insert_one(deal_doc)
                created_entities["deal_id"] = str(deal_result.inserted_id)
        
        # Mark source as converted
        collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {
                "$set": {
                    "status": "converted",
                    "converted_at": datetime.utcnow(),
                    "converted_by": action.initiated_by,
                    "converted_to": created_entities,
                }
            }
        )
        
        return ActionResult(
            success=True,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            result_data={"converted_to": created_entities},
            can_rollback=False,  # Conversion is complex to rollback
        )
    
    def _execute_archive(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute archive action"""
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {
                "$set": {
                    "is_archived": True,
                    "archived_at": datetime.utcnow(),
                    "archived_by": action.initiated_by,
                }
            }
        )
        
        return ActionResult(
            success=result.matched_count > 0,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            can_rollback=True,
        )
    
    def _execute_restore(self, collection, payload: ActionPayload, action: MCPAction) -> ActionResult:
        """Execute restore action"""
        result = collection.update_one(
            {"_id": ObjectId(payload.entity_id)},
            {
                "$set": {
                    "is_archived": False,
                    "is_deleted": False,
                    "restored_at": datetime.utcnow(),
                    "restored_by": action.initiated_by,
                },
                "$unset": {
                    "archived_at": "",
                    "deleted_at": "",
                }
            }
        )
        
        return ActionResult(
            success=result.matched_count > 0,
            action_id=action.id,
            entity_id=payload.entity_id,
            entity_type=payload.entity_type,
            action_type=payload.action_type,
            can_rollback=True,
        )


class MCPActionRouter:
    """
    Central MCP Action Router
    
    Orchestrates all controlled write operations:
    1. Validates action payload
    2. Checks if approval is required
    3. Captures state for rollback
    4. Executes action
    5. Records audit trail
    """
    
    ACTIONS_COLLECTION = "mcp_actions"
    
    def __init__(self, client: MongoClient):
        self.client = client
        self.settings_db = client["torpedo_settings"]
        self.actions_collection = self.settings_db[self.ACTIONS_COLLECTION]
        
        self.validator = get_validator()
        self.rollback_manager = get_rollback_manager(client)
        self.executor = ActionExecutor(client)
        
        # Approval engine (optional)
        self.approval_engine = None
        if get_approval_engine:
            try:
                self.approval_engine = get_approval_engine(self.settings_db)
            except Exception:
                pass
        
        # Ensure indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create database indexes"""
        self.actions_collection.create_index("status")
        self.actions_collection.create_index("initiated_by")
        self.actions_collection.create_index("payload.entity_type")
        self.actions_collection.create_index("payload.entity_id")
        self.actions_collection.create_index("created_at")
    
    def submit_action(
        self,
        action_create: MCPActionCreate,
        user_id: str,
        user_name: Optional[str] = None,
    ) -> MCPAction:
        """
        Submit an action for execution.
        Returns the action with status (may be pending approval).
        """
        # Build payload
        payload = ActionPayload(
            entity_type=action_create.entity_type,
            action_type=action_create.action_type,
            entity_id=action_create.entity_id,
            data=action_create.data,
            reason=action_create.reason,
        )
        
        # Create action record
        action = MCPAction(
            payload=payload,
            priority=action_create.priority,
            is_dry_run=action_create.is_dry_run,
            initiated_by=user_id,
            initiated_by_name=user_name,
        )
        
        # Validate
        action.status = ActionStatus.VALIDATING
        validation_result = self.validator.validate(payload)
        action.validation_result = validation_result
        action.validated_at = datetime.utcnow()
        
        if not validation_result.is_valid:
            action.status = ActionStatus.FAILED
            action.audit_log.append({
                "event": "validation_failed",
                "errors": validation_result.errors,
                "timestamp": datetime.utcnow().isoformat(),
            })
            return self._save_action(action)
        
        # Handle dry run
        if action_create.is_dry_run:
            dry_run_result = self._execute_dry_run(action)
            action.dry_run_result = dry_run_result
            action.status = ActionStatus.COMPLETED
            action.audit_log.append({
                "event": "dry_run_completed",
                "timestamp": datetime.utcnow().isoformat(),
            })
            return self._save_action(action)
        
        # Check if approval is required
        if not action_create.skip_approval:
            requires_approval, approval_rule = self._check_approval_required(action)
            if requires_approval:
                action.requires_approval = True
                action.status = ActionStatus.AWAITING_APPROVAL
                
                # Create approval request
                if self.approval_engine and ApprovalRequestCreate:
                    approval_request = self.approval_engine.create_request(
                        ApprovalRequestCreate(
                            entity_type=payload.entity_type.value,
                            entity_id=payload.entity_id or "new",
                            entity_summary=f"{payload.action_type.value} {payload.entity_type.value}",
                            requested_action=payload.action_type.value,
                            request_reason=payload.reason,
                        ),
                        requested_by=user_id,
                        requested_by_name=user_name,
                        entity_snapshot=payload.data,
                    )
                    action.approval_request_id = approval_request.id
                
                action.audit_log.append({
                    "event": "awaiting_approval",
                    "rule": approval_rule,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                return self._save_action(action)
        
        # Execute immediately
        return self._execute_action(action)
    
    def execute_approved_action(self, action_id: str, approver_id: str) -> MCPAction:
        """Execute an action after approval"""
        action = self.get_action(action_id)
        if not action:
            raise ValueError(f"Action not found: {action_id}")
        
        if action.status != ActionStatus.AWAITING_APPROVAL:
            raise ValueError(f"Action is not awaiting approval: {action.status}")
        
        action.executed_by = approver_id
        return self._execute_action(action)
    
    def _execute_action(self, action: MCPAction) -> MCPAction:
        """Execute the action"""
        action.status = ActionStatus.EXECUTING
        action.executed_at = datetime.utcnow()
        
        # Capture state for rollback (non-create actions)
        previous_state = None
        if action.payload.entity_id:
            previous_state = self.rollback_manager.capture_state(
                action.payload.entity_type,
                action.payload.entity_id
            )
        
        # Execute
        result = self.executor.execute(action)
        action.result = result
        
        if result.success:
            action.status = ActionStatus.COMPLETED
            action.completed_at = datetime.utcnow()
            
            # Create rollback info
            if result.can_rollback:
                action.rollback_info = self.rollback_manager.create_rollback_info(
                    action,
                    previous_state=previous_state,
                    created_entity_id=result.entity_id if action.payload.action_type == ActionType.CREATE else None,
                )
            
            action.audit_log.append({
                "event": "completed",
                "entity_id": result.entity_id,
                "timestamp": datetime.utcnow().isoformat(),
            })
        else:
            action.status = ActionStatus.FAILED
            action.audit_log.append({
                "event": "failed",
                "error": result.error_message,
                "error_code": result.error_code,
                "timestamp": datetime.utcnow().isoformat(),
            })
        
        return self._save_action(action)
    
    def _execute_dry_run(self, action: MCPAction) -> Dict[str, Any]:
        """Execute a dry run without persisting changes"""
        requires_approval, approval_rule = self._check_approval_required(action)
        
        # Get affected entities
        affected = []
        if action.payload.entity_id:
            affected.append({
                "entity_type": action.payload.entity_type.value,
                "entity_id": action.payload.entity_id,
                "operation": action.payload.action_type.value,
            })
        
        return {
            "would_succeed": action.validation_result.is_valid,
            "requires_approval": requires_approval,
            "approval_rule": approval_rule,
            "affected_entities": affected,
            "predicted_changes": action.payload.data,
            "warnings": action.validation_result.warnings,
        }
    
    def _check_approval_required(self, action: MCPAction) -> Tuple[bool, Optional[str]]:
        """Check if action requires approval"""
        if not self.approval_engine:
            return False, None
        
        # Get entity data for rule matching
        entity_data = dict(action.payload.data)
        if action.payload.entity_id:
            # Fetch current entity to merge with payload
            state = self.rollback_manager.capture_state(
                action.payload.entity_type,
                action.payload.entity_id
            )
            if state:
                entity_data = {**state, **entity_data}
        
        requires, rule = self.approval_engine.requires_approval(
            action.payload.entity_type.value,
            action.payload.action_type.value,
            entity_data,
        )
        
        return requires, rule.name if rule else None
    
    def rollback_action(self, action_id: str, user_id: str) -> MCPAction:
        """Rollback a completed action"""
        action = self.get_action(action_id)
        if not action:
            raise ValueError(f"Action not found: {action_id}")
        
        return self.rollback_manager.rollback(action, user_id)
    
    def cancel_action(self, action_id: str, user_id: str) -> MCPAction:
        """Cancel a pending or awaiting approval action"""
        action = self.get_action(action_id)
        if not action:
            raise ValueError(f"Action not found: {action_id}")
        
        if action.status not in [ActionStatus.PENDING, ActionStatus.AWAITING_APPROVAL]:
            raise ValueError(f"Cannot cancel action with status: {action.status}")
        
        action.status = ActionStatus.CANCELLED
        action.audit_log.append({
            "event": "cancelled",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        return self._save_action(action)
    
    def submit_batch(
        self,
        batch: MCPActionBatch,
        user_id: str,
        user_name: Optional[str] = None,
    ) -> Tuple[List[MCPAction], bool]:
        """
        Submit a batch of actions.
        If atomic=True, all actions must succeed or all are rolled back.
        Returns (actions, all_succeeded)
        """
        actions = []
        all_succeeded = True
        
        for action_create in batch.actions:
            action = self.submit_action(action_create, user_id, user_name)
            actions.append(action)
            
            if action.status == ActionStatus.FAILED:
                all_succeeded = False
                if batch.atomic:
                    # Rollback all previously completed actions
                    for prev_action in actions[:-1]:
                        if prev_action.status == ActionStatus.COMPLETED:
                            try:
                                self.rollback_action(prev_action.id, user_id)
                            except Exception as e:
                                print(f"⚠️ Failed to rollback {prev_action.id}: {e}")
                    break
        
        return actions, all_succeeded
    
    def _save_action(self, action: MCPAction) -> MCPAction:
        """Save action to database"""
        doc = action.model_dump()
        
        if action.id:
            doc.pop("id", None)
            self.actions_collection.update_one(
                {"_id": ObjectId(action.id)},
                {"$set": doc}
            )
        else:
            result = self.actions_collection.insert_one(doc)
            action.id = str(result.inserted_id)
        
        return action
    
    def get_action(self, action_id: str) -> Optional[MCPAction]:
        """Get action by ID"""
        doc = self.actions_collection.find_one({"_id": ObjectId(action_id)})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return MCPAction(**doc)
    
    def list_actions(
        self,
        status: Optional[ActionStatus] = None,
        entity_type: Optional[EntityType] = None,
        initiated_by: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[MCPAction], int]:
        """List actions with optional filtering"""
        query = {}
        if status:
            query["status"] = status.value
        if entity_type:
            query["payload.entity_type"] = entity_type.value
        if initiated_by:
            query["initiated_by"] = initiated_by
        
        total = self.actions_collection.count_documents(query)
        cursor = self.actions_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        
        actions = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            actions.append(MCPAction(**doc))
        
        return actions, total


# Singleton instance
_action_router: Optional[MCPActionRouter] = None


def get_action_router(client: MongoClient) -> MCPActionRouter:
    """Get or create action router instance"""
    global _action_router
    if _action_router is None:
        _action_router = MCPActionRouter(client)
    return _action_router
