# backend/workflows/approval_engine.py
# Core approval workflow engine with rule matching, request management, and escalation

import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable, Tuple
from bson import ObjectId
from pymongo.database import Database

from .models import (
    ApprovalRequest,
    ApprovalRequestCreate,
    ApprovalAction,
    ApprovalActionType,
    ApprovalRule,
    ApprovalRuleCreate,
    ApprovalStatus,
    ApprovalDecision,
    ApprovalStats,
)


class ApprovalEngine:
    """
    Enterprise Approval Workflow Engine
    
    Handles:
    - Rule-based approval triggers
    - Multi-level approval chains
    - Automatic escalation
    - Audit trail for all actions
    - Callback execution on resolution
    """
    
    # Default expiration for approval requests (7 days)
    DEFAULT_EXPIRATION_DAYS = 7
    
    # Collection names
    RULES_COLLECTION = "approval_rules"
    REQUESTS_COLLECTION = "approval_requests"
    
    def __init__(self, db: Database):
        self.db = db
        self.rules_collection = db[self.RULES_COLLECTION]
        self.requests_collection = db[self.REQUESTS_COLLECTION]
        
        # Registry for callbacks
        self._callbacks: Dict[str, Callable] = {}
        
        # Ensure indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create database indexes for performance"""
        # Rules indexes
        self.rules_collection.create_index("entity_type")
        self.rules_collection.create_index("action")
        self.rules_collection.create_index([("entity_type", 1), ("action", 1), ("is_active", 1)])
        self.rules_collection.create_index("priority")
        
        # Requests indexes
        self.requests_collection.create_index("entity_type")
        self.requests_collection.create_index("entity_id")
        self.requests_collection.create_index("status")
        self.requests_collection.create_index("requested_by")
        self.requests_collection.create_index("required_approvers")
        self.requests_collection.create_index([("status", 1), ("expires_at", 1)])
        self.requests_collection.create_index("created_at")
    
    # ==================== RULE MANAGEMENT ====================
    
    def create_rule(self, rule_data: ApprovalRuleCreate, created_by: str) -> ApprovalRule:
        """Create a new approval rule"""
        now = datetime.utcnow()
        
        doc = {
            **rule_data.model_dump(),
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
            "is_active": True,
        }
        
        result = self.rules_collection.insert_one(doc)
        doc["id"] = str(result.inserted_id)
        
        return ApprovalRule(**doc)
    
    def get_rule(self, rule_id: str) -> Optional[ApprovalRule]:
        """Get a rule by ID"""
        doc = self.rules_collection.find_one({"_id": ObjectId(rule_id)})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return ApprovalRule(**doc)
    
    def list_rules(
        self,
        entity_type: Optional[str] = None,
        action: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ApprovalRule], int]:
        """List approval rules with filtering"""
        query: Dict[str, Any] = {}
        
        if entity_type:
            query["entity_type"] = entity_type
        if action:
            query["action"] = action
        if is_active is not None:
            query["is_active"] = is_active
        
        total = self.rules_collection.count_documents(query)
        cursor = self.rules_collection.find(query).sort("priority", -1).skip(skip).limit(limit)
        
        rules = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            rules.append(ApprovalRule(**doc))
        
        return rules, total
    
    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> Optional[ApprovalRule]:
        """Update an approval rule"""
        updates["updated_at"] = datetime.utcnow()
        
        result = self.rules_collection.find_one_and_update(
            {"_id": ObjectId(rule_id)},
            {"$set": updates},
            return_document=True
        )
        
        if not result:
            return None
        result["id"] = str(result.pop("_id"))
        return ApprovalRule(**result)
    
    def delete_rule(self, rule_id: str) -> bool:
        """Delete an approval rule (soft delete by deactivating)"""
        result = self.rules_collection.update_one(
            {"_id": ObjectId(rule_id)},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    def find_matching_rule(
        self,
        entity_type: str,
        action: str,
        entity: Dict[str, Any]
    ) -> Optional[ApprovalRule]:
        """
        Find the highest priority rule matching the entity and action.
        Evaluates conditions against the entity data.
        """
        # Get all active rules for this entity type and action
        rules = self.rules_collection.find({
            "entity_type": entity_type,
            "action": action,
            "is_active": True
        }).sort("priority", -1)
        
        for rule_doc in rules:
            conditions = rule_doc.get("conditions", {})
            
            # If no conditions, rule matches everything
            if not conditions:
                rule_doc["id"] = str(rule_doc.pop("_id"))
                return ApprovalRule(**rule_doc)
            
            # Evaluate conditions against entity
            if self._evaluate_conditions(conditions, entity):
                rule_doc["id"] = str(rule_doc.pop("_id"))
                return ApprovalRule(**rule_doc)
        
        return None
    
    def _evaluate_conditions(self, conditions: Dict[str, Any], entity: Dict[str, Any]) -> bool:
        """
        Evaluate MongoDB-style conditions against an entity.
        Supports: $eq, $ne, $gt, $gte, $lt, $lte, $in, $nin, $exists
        """
        for field, condition in conditions.items():
            entity_value = entity.get(field)
            
            if isinstance(condition, dict):
                # Complex condition with operators
                for op, expected in condition.items():
                    if not self._evaluate_operator(op, entity_value, expected):
                        return False
            else:
                # Simple equality
                if entity_value != condition:
                    return False
        
        return True
    
    def _evaluate_operator(self, op: str, actual: Any, expected: Any) -> bool:
        """Evaluate a single operator"""
        if op == "$eq":
            return actual == expected
        elif op == "$ne":
            return actual != expected
        elif op == "$gt":
            return actual is not None and actual > expected
        elif op == "$gte":
            return actual is not None and actual >= expected
        elif op == "$lt":
            return actual is not None and actual < expected
        elif op == "$lte":
            return actual is not None and actual <= expected
        elif op == "$in":
            return actual in expected
        elif op == "$nin":
            return actual not in expected
        elif op == "$exists":
            return (actual is not None) == expected
        else:
            # Unknown operator, fail safe
            return False
    
    # ==================== REQUEST MANAGEMENT ====================
    
    def requires_approval(
        self,
        entity_type: str,
        action: str,
        entity: Dict[str, Any]
    ) -> Tuple[bool, Optional[ApprovalRule]]:
        """
        Check if an action on an entity requires approval.
        Returns (requires_approval, matching_rule)
        """
        rule = self.find_matching_rule(entity_type, action, entity)
        return (rule is not None, rule)
    
    def create_request(
        self,
        request_data: ApprovalRequestCreate,
        requested_by: str,
        requested_by_name: Optional[str] = None,
        entity_snapshot: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """
        Create a new approval request.
        If rule_id not provided, finds matching rule automatically.
        """
        now = datetime.utcnow()
        
        # Find the rule
        if request_data.rule_id:
            rule = self.get_rule(request_data.rule_id)
            if not rule:
                raise ValueError(f"Rule not found: {request_data.rule_id}")
        else:
            rule = self.find_matching_rule(
                request_data.entity_type,
                request_data.requested_action,
                entity_snapshot or {}
            )
            if not rule:
                raise ValueError(
                    f"No approval rule found for {request_data.entity_type}/{request_data.requested_action}"
                )
        
        # Build list of required approvers
        required_approvers = list(rule.approver_user_ids)
        
        # If roles are specified, we'll need to resolve them to users
        # For now, store the role requirements separately
        
        # Calculate expiration
        expires_at = now + timedelta(days=self.DEFAULT_EXPIRATION_DAYS)
        
        doc = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "entity_type": request_data.entity_type,
            "entity_id": request_data.entity_id,
            "entity_summary": request_data.entity_summary,
            "entity_snapshot": entity_snapshot,
            "requested_action": request_data.requested_action,
            "status": ApprovalStatus.PENDING.value,
            "required_approvers": required_approvers,
            "approver_roles": rule.approver_roles,  # Store for role-based lookup
            "approved_by": [],
            "rejected_by": None,
            "min_approvals_required": rule.min_approvals,
            "actions": [],
            "current_escalation_level": 0,
            "escalated_at": None,
            "requested_by": requested_by,
            "requested_by_name": requested_by_name,
            "request_reason": request_data.request_reason,
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "resolved_at": None,
            "on_approve_callback": None,
            "on_reject_callback": None,
            "callback_data": None,
        }
        
        result = self.requests_collection.insert_one(doc)
        doc["id"] = str(result.inserted_id)
        doc.pop("_id", None)
        
        return ApprovalRequest(**doc)
    
    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get an approval request by ID"""
        doc = self.requests_collection.find_one({"_id": ObjectId(request_id)})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return ApprovalRequest(**doc)
    
    def list_requests(
        self,
        status: Optional[ApprovalStatus] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        requested_by: Optional[str] = None,
        approver_id: Optional[str] = None,
        include_expired: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ApprovalRequest], int]:
        """List approval requests with filtering"""
        query: Dict[str, Any] = {}
        
        if status:
            query["status"] = status.value
        if entity_type:
            query["entity_type"] = entity_type
        if entity_id:
            query["entity_id"] = entity_id
        if requested_by:
            query["requested_by"] = requested_by
        if approver_id:
            query["$or"] = [
                {"required_approvers": approver_id},
                {"approver_roles": {"$exists": True}}  # Will need role resolution
            ]
        if not include_expired:
            query["$or"] = query.get("$or", [])
            # Only pending requests can expire
            query["$and"] = [
                {"$or": [
                    {"status": {"$ne": ApprovalStatus.PENDING.value}},
                    {"expires_at": {"$gt": datetime.utcnow()}}
                ]}
            ]
        
        total = self.requests_collection.count_documents(query)
        cursor = self.requests_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        
        requests = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            requests.append(ApprovalRequest(**doc))
        
        return requests, total
    
    def get_pending_for_user(
        self,
        user_id: str,
        user_roles: List[str],
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ApprovalRequest], int]:
        """Get pending approval requests that a user can act on"""
        now = datetime.utcnow()
        
        query = {
            "status": ApprovalStatus.PENDING.value,
            "expires_at": {"$gt": now},
            "$or": [
                {"required_approvers": user_id},
                {"approver_roles": {"$in": user_roles}}
            ],
            # Exclude already approved by this user
            "approved_by": {"$ne": user_id}
        }
        
        total = self.requests_collection.count_documents(query)
        cursor = self.requests_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        
        requests = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            requests.append(ApprovalRequest(**doc))
        
        return requests, total
    
    # ==================== DECISION HANDLING ====================
    
    def make_decision(
        self,
        request_id: str,
        decision: ApprovalDecision,
        user_id: str,
        user_name: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Make a decision on an approval request.
        Handles approve, reject, escalate, delegate, comment.
        """
        request = self.get_request(request_id)
        if not request:
            raise ValueError(f"Approval request not found: {request_id}")
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request is not pending (status: {request.status})")
        
        now = datetime.utcnow()
        
        # Create action record
        action = ApprovalAction(
            action_type=decision.action,
            user_id=user_id,
            user_name=user_name,
            timestamp=now,
            comment=decision.comment,
            delegated_to_user_id=decision.delegated_to_user_id,
            escalation_level=request.current_escalation_level,
        )
        
        updates: Dict[str, Any] = {
            "updated_at": now,
        }
        push_updates: Dict[str, Any] = {
            "actions": action.model_dump()
        }
        
        if decision.action == ApprovalActionType.APPROVE:
            # Add to approved_by list
            push_updates["approved_by"] = user_id
            
            # Check if we have enough approvals
            new_approved_count = len(request.approved_by) + 1
            if new_approved_count >= request.min_approvals_required:
                updates["status"] = ApprovalStatus.APPROVED.value
                updates["resolved_at"] = now
        
        elif decision.action == ApprovalActionType.REJECT:
            updates["status"] = ApprovalStatus.REJECTED.value
            updates["rejected_by"] = user_id
            updates["resolved_at"] = now
        
        elif decision.action == ApprovalActionType.ESCALATE:
            updates["status"] = ApprovalStatus.ESCALATED.value
            updates["current_escalation_level"] = request.current_escalation_level + 1
            updates["escalated_at"] = now
        
        elif decision.action == ApprovalActionType.DELEGATE:
            if decision.delegated_to_user_id:
                push_updates["required_approvers"] = decision.delegated_to_user_id
        
        # Comment-only doesn't change status
        
        # Apply updates
        update_query = {"$set": updates}
        if push_updates:
            update_query["$push"] = push_updates
        
        result = self.requests_collection.find_one_and_update(
            {"_id": ObjectId(request_id)},
            update_query,
            return_document=True
        )
        
        result["id"] = str(result.pop("_id"))
        updated_request = ApprovalRequest(**result)
        
        # Execute callbacks if resolved
        if updated_request.status in [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]:
            self._execute_callbacks(updated_request)
        
        return updated_request
    
    def cancel_request(
        self,
        request_id: str,
        user_id: str,
        reason: Optional[str] = None
    ) -> ApprovalRequest:
        """Cancel an approval request (only by requester or admin)"""
        request = self.get_request(request_id)
        if not request:
            raise ValueError(f"Approval request not found: {request_id}")
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request is not pending (status: {request.status})")
        
        now = datetime.utcnow()
        
        action = ApprovalAction(
            action_type=ApprovalActionType.COMMENT,
            user_id=user_id,
            timestamp=now,
            comment=f"Cancelled: {reason}" if reason else "Cancelled by requester",
        )
        
        result = self.requests_collection.find_one_and_update(
            {"_id": ObjectId(request_id)},
            {
                "$set": {
                    "status": ApprovalStatus.CANCELLED.value,
                    "updated_at": now,
                    "resolved_at": now,
                },
                "$push": {"actions": action.model_dump()}
            },
            return_document=True
        )
        
        result["id"] = str(result.pop("_id"))
        return ApprovalRequest(**result)
    
    # ==================== ESCALATION ====================
    
    def check_and_escalate_expired(self) -> List[str]:
        """
        Check for pending requests that need escalation.
        Should be run periodically (e.g., every hour).
        Returns list of escalated request IDs.
        """
        now = datetime.utcnow()
        escalated_ids = []
        
        # Find pending requests past their escalation time
        # This requires rules to have escalation config
        pending_requests = self.requests_collection.find({
            "status": ApprovalStatus.PENDING.value,
        })
        
        for req_doc in pending_requests:
            rule = self.get_rule(req_doc["rule_id"])
            if not rule or not rule.escalation or not rule.escalation.enabled:
                continue
            
            # Check if enough time has passed
            created_at = req_doc["created_at"]
            escalation_hours = rule.escalation.hours_until_escalation
            escalation_multiplier = req_doc.get("current_escalation_level", 0) + 1
            
            should_escalate_at = created_at + timedelta(
                hours=escalation_hours * escalation_multiplier
            )
            
            if now >= should_escalate_at:
                # Check max escalations
                if req_doc.get("current_escalation_level", 0) >= rule.escalation.max_escalations:
                    # Mark as expired instead
                    self.requests_collection.update_one(
                        {"_id": req_doc["_id"]},
                        {
                            "$set": {
                                "status": ApprovalStatus.EXPIRED.value,
                                "updated_at": now,
                                "resolved_at": now,
                            }
                        }
                    )
                else:
                    # Escalate
                    action = ApprovalAction(
                        action_type=ApprovalActionType.ESCALATE,
                        user_id="system",
                        user_name="Automatic Escalation",
                        timestamp=now,
                        comment=f"Auto-escalated after {escalation_hours} hours",
                        escalation_level=req_doc.get("current_escalation_level", 0) + 1,
                    )
                    
                    self.requests_collection.update_one(
                        {"_id": req_doc["_id"]},
                        {
                            "$set": {
                                "status": ApprovalStatus.ESCALATED.value,
                                "current_escalation_level": req_doc.get("current_escalation_level", 0) + 1,
                                "escalated_at": now,
                                "updated_at": now,
                            },
                            "$push": {"actions": action.model_dump()}
                        }
                    )
                    escalated_ids.append(str(req_doc["_id"]))
        
        return escalated_ids
    
    def expire_old_requests(self) -> int:
        """
        Mark pending requests past their expiration date as expired.
        Returns count of expired requests.
        """
        now = datetime.utcnow()
        
        result = self.requests_collection.update_many(
            {
                "status": ApprovalStatus.PENDING.value,
                "expires_at": {"$lte": now}
            },
            {
                "$set": {
                    "status": ApprovalStatus.EXPIRED.value,
                    "updated_at": now,
                    "resolved_at": now,
                }
            }
        )
        
        return result.modified_count
    
    # ==================== CALLBACKS ====================
    
    def register_callback(self, name: str, callback: Callable):
        """Register a callback function by name"""
        self._callbacks[name] = callback
    
    def set_request_callbacks(
        self,
        request_id: str,
        on_approve: Optional[str] = None,
        on_reject: Optional[str] = None,
        callback_data: Optional[Dict[str, Any]] = None,
    ):
        """Set callback functions for a request"""
        updates = {}
        if on_approve:
            updates["on_approve_callback"] = on_approve
        if on_reject:
            updates["on_reject_callback"] = on_reject
        if callback_data:
            updates["callback_data"] = callback_data
        
        if updates:
            self.requests_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": updates}
            )
    
    def _execute_callbacks(self, request: ApprovalRequest):
        """Execute callbacks after request resolution"""
        callback_name = None
        if request.status == ApprovalStatus.APPROVED:
            callback_name = request.on_approve_callback
        elif request.status == ApprovalStatus.REJECTED:
            callback_name = request.on_reject_callback
        
        if callback_name and callback_name in self._callbacks:
            try:
                self._callbacks[callback_name](request, request.callback_data)
            except Exception as e:
                # Log error but don't fail the approval
                print(f"⚠️ Callback {callback_name} failed: {e}")
    
    # ==================== STATISTICS ====================
    
    def get_stats(self, days: int = 30) -> ApprovalStats:
        """Get approval statistics for the specified period"""
        since = datetime.utcnow() - timedelta(days=days)
        
        pipeline = [
            {"$match": {"created_at": {"$gte": since}}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        status_counts = {
            ApprovalStatus.PENDING.value: 0,
            ApprovalStatus.APPROVED.value: 0,
            ApprovalStatus.REJECTED.value: 0,
            ApprovalStatus.ESCALATED.value: 0,
            ApprovalStatus.EXPIRED.value: 0,
        }
        
        for doc in self.requests_collection.aggregate(pipeline):
            status_counts[doc["_id"]] = doc["count"]
        
        # Entity type breakdown
        entity_pipeline = [
            {"$match": {"created_at": {"$gte": since}}},
            {"$group": {"_id": "$entity_type", "count": {"$sum": 1}}}
        ]
        by_entity_type = {}
        for doc in self.requests_collection.aggregate(entity_pipeline):
            by_entity_type[doc["_id"]] = doc["count"]
        
        # Average resolution time
        resolution_pipeline = [
            {"$match": {
                "created_at": {"$gte": since},
                "resolved_at": {"$exists": True, "$ne": None}
            }},
            {"$project": {
                "resolution_ms": {"$subtract": ["$resolved_at", "$created_at"]}
            }},
            {"$group": {
                "_id": None,
                "avg_ms": {"$avg": "$resolution_ms"}
            }}
        ]
        avg_resolution = 0.0
        for doc in self.requests_collection.aggregate(resolution_pipeline):
            avg_ms = doc.get("avg_ms", 0)
            avg_resolution = avg_ms / (1000 * 60 * 60) if avg_ms else 0  # Convert to hours
        
        return ApprovalStats(
            pending_count=status_counts[ApprovalStatus.PENDING.value],
            approved_count=status_counts[ApprovalStatus.APPROVED.value],
            rejected_count=status_counts[ApprovalStatus.REJECTED.value],
            escalated_count=status_counts[ApprovalStatus.ESCALATED.value],
            expired_count=status_counts[ApprovalStatus.EXPIRED.value],
            average_resolution_hours=round(avg_resolution, 2),
            by_entity_type=by_entity_type,
        )


# Singleton instance holder
_approval_engine: Optional[ApprovalEngine] = None


def get_approval_engine(db: Database) -> ApprovalEngine:
    """Get or create the approval engine singleton"""
    global _approval_engine
    if _approval_engine is None:
        _approval_engine = ApprovalEngine(db)
    return _approval_engine
