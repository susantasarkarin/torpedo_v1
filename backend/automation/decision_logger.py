"""
Decision Logger - Logs all autonomous decisions with full reasoning for compliance

Implements GDPR/CAN-SPAM compliance logging:
- Every decision logged with confidence score, reasoning, and input context
- Searchable by decision type, lead, campaign, timestamp
- Supports audit exports for compliance reviews

Database: campaign_decisions collection
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pymongo.database import Database
from bson import ObjectId

logger = logging.getLogger(__name__)


class DecisionLogger:
    """
    Autonomous decision logging for compliance.

    Every routing, email generation, and scheduling decision is logged
    with full reasoning, confidence scores, and input context.
    """

    def __init__(self, db: Database):
        """
        Initialize decision logger.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.decisions = db["campaign_decisions"]

        self._setup_indexes()

    def _setup_indexes(self):
        """Create necessary indexes for efficient querying"""
        try:
            self.decisions.create_index([("logged_at", -1)])
            self.decisions.create_index([("decision_type", 1), ("logged_at", -1)])
            self.decisions.create_index([("lead_id", 1), ("logged_at", -1)])
            self.decisions.create_index([("campaign_id", 1), ("logged_at", -1)])
            self.decisions.create_index([("autonomous", 1), ("logged_at", -1)])
            self.decisions.create_index([("confidence_score", 1)])
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")

    def log_decision(
        self,
        decision_type: str,
        action: str,
        autonomous: bool = True,
        lead_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        user_id: Optional[str] = None,
        confidence_score: float = 1.0,
        reasoning: Optional[Dict[str, Any]] = None,
        input_context: Optional[Dict[str, Any]] = None,
        decision_params: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> str:
        """
        Log an autonomous decision with full compliance information.

        Args:
            decision_type: Type of decision (lead_routing, email_generation, schedule_optimization)
            action: Specific action taken (route_to_campaign, select_variant, set_schedule)
            autonomous: Whether decision was made by system (bool) or human (false)
            lead_id: Optional lead ID
            campaign_id: Optional campaign ID
            user_id: Optional user ID (null for autonomous)
            confidence_score: Confidence in decision (0.0-1.0)
            reasoning: Dict explaining why this decision was made
            input_context: Dict with context that led to decision
            decision_params: Dict with parameters of the decision
            error: Optional error message if decision failed

        Returns:
            Decision ID
        """
        decision_id = str(ObjectId())

        doc = {
            "decision_id": decision_id,
            "decision_type": decision_type,
            "action": action,
            "autonomous": autonomous,
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "confidence_score": confidence_score,
            "reasoning": reasoning or {},
            "input_context": input_context or {},
            "decision_params": decision_params or {},
            "error": error,
            "logged_at": datetime.utcnow()
        }

        # Add audit signature (hash of decision for compliance)
        import hashlib
        import json
        audit_content = json.dumps({
            "decision_type": decision_type,
            "action": action,
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "confidence_score": confidence_score,
            "timestamp": doc["logged_at"].isoformat()
        }, sort_keys=True)
        doc["audit_signature"] = hashlib.sha256(audit_content.encode()).hexdigest()

        try:
            self.decisions.insert_one(doc)
            logger.info(f"Decision logged: {decision_type} - {action} (confidence: {confidence_score:.2f})")
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

        return decision_id

    def get_decision_history(
        self,
        lead_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get decision history for compliance review.

        Args:
            lead_id: Filter by lead
            campaign_id: Filter by campaign
            decision_type: Filter by decision type
            limit: Max results to return

        Returns:
            List of decision records
        """
        query: Dict[str, Any] = {}

        if lead_id:
            query["lead_id"] = lead_id
        if campaign_id:
            query["campaign_id"] = campaign_id
        if decision_type:
            query["decision_type"] = decision_type

        decisions = list(
            self.decisions.find(query)
            .sort("logged_at", -1)
            .limit(limit)
        )

        # Clean up for JSON serialization
        for d in decisions:
            d.pop("_id", None)
            if "logged_at" in d:
                d["logged_at"] = d["logged_at"].isoformat()

        return decisions

    def get_confidence_stats(
        self,
        decision_type: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get confidence score statistics for decision quality monitoring.

        Args:
            decision_type: Filter by decision type
            hours: Hours to look back

        Returns:
            Statistics on confidence scores
        """
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(hours=hours)

        match_stage: Dict[str, Any] = {"logged_at": {"$gte": since}}
        if decision_type:
            match_stage["decision_type"] = decision_type

        pipeline = [
            {"$match": match_stage},
            {"$group": {
                "_id": "$decision_type",
                "count": {"$sum": 1},
                "avg_confidence": {"$avg": "$confidence_score"},
                "min_confidence": {"$min": "$confidence_score"},
                "max_confidence": {"$max": "$confidence_score"},
                "below_85": {"$sum": {"$cond": [{"$lt": ["$confidence_score", 0.85]}, 1, 0]}}
            }}
        ]

        try:
            results = list(self.decisions.aggregate(pipeline))

            stats = {
                "period_hours": hours,
                "total_decisions": sum(r["count"] for r in results),
                "by_type": {}
            }

            for r in results:
                decision_type_name = r["_id"]
                stats["by_type"][decision_type_name] = {
                    "count": r["count"],
                    "avg_confidence": round(r["avg_confidence"], 3),
                    "min_confidence": round(r["min_confidence"], 3),
                    "max_confidence": round(r["max_confidence"], 3),
                    "below_85_threshold": r["below_85"],
                    "below_85_pct": round(r["below_85"] / r["count"] * 100, 1) if r["count"] > 0 else 0
                }

            return stats
        except Exception as e:
            logger.error(f"Failed to get confidence stats: {e}")
            return {}

    def export_audit_trail(
        self,
        start_date: datetime,
        end_date: datetime,
        decision_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Export audit trail for compliance reviews (GDPR, CAN-SPAM).

        Args:
            start_date: Start of period
            end_date: End of period
            decision_type: Optional filter by decision type

        Returns:
            List of decision records with compliance info
        """
        query: Dict[str, Any] = {
            "logged_at": {
                "$gte": start_date,
                "$lte": end_date
            }
        }

        if decision_type:
            query["decision_type"] = decision_type

        decisions = list(
            self.decisions.find(query)
            .sort("logged_at", 1)
        )

        # Clean up for export
        for d in decisions:
            d.pop("_id", None)
            if "logged_at" in d:
                d["logged_at"] = d["logged_at"].isoformat()

        return decisions
