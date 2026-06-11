"""
Performance Optimization Loop

Adjusts email variant weights and preferred send hours based on engagement data.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pymongo.database import Database

logger = logging.getLogger(__name__)


class PerformanceOptimizer:
    """
    Self-optimizing loop for campaign performance.
    """

    MIN_SAMPLE_SIZE = 20
    DEGRADATION_DELTA = 0.15
    BOOST_DELTA = 0.10
    WEIGHT_BOOST_FACTOR = 1.2

    def __init__(self, db: Database, decision_logger=None):
        self.db = db
        self.campaigns = db["campaigns"]
        self.campaign_sends = db["campaign_sends"]
        self.campaign_recipients = db["campaign_recipients"]
        self.email_variants = db["email_variants"]
        self.reply_decisions = db["reply_decisions"]
        self.decision_logger = decision_logger

    def optimize_campaign(self, campaign_id: str) -> Dict[str, Any]:
        campaign = self.campaigns.find_one({"_id": campaign_id})
        if not campaign:
            return {"error": f"Campaign {campaign_id} not found"}

        variant_metrics = self._compute_variant_metrics(campaign_id)
        if not variant_metrics:
            return {"campaign_id": campaign_id, "status": "no_data"}

        totals = self._compute_campaign_totals(variant_metrics)
        campaign_reply_rate = totals["reply_rate"]
        campaign_positive_reply_rate = totals["positive_reply_rate"]

        updates = {
            "degraded_variants": [],
            "boosted_variants": [],
            "preferred_send_hours": None
        }

        for variant_key, metrics in variant_metrics.items():
            if metrics["sample_size"] < self.MIN_SAMPLE_SIZE:
                continue

            reply_rate = metrics["reply_rate"]
            positive_reply_rate = metrics["positive_reply_rate"]

            if reply_rate < (campaign_reply_rate - self.DEGRADATION_DELTA):
                updates["degraded_variants"].append(variant_key)
                self._mark_variant_status(campaign_id, variant_key, "degraded")

            if positive_reply_rate > (campaign_positive_reply_rate + self.BOOST_DELTA):
                new_weight = self._boost_variant_weight(campaign_id, variant_key)
                updates["boosted_variants"].append({
                    "variant": variant_key,
                    "new_weight": new_weight
                })

        preferred_send_hours = self._compute_preferred_send_hours(campaign_id)
        if preferred_send_hours:
            updates["preferred_send_hours"] = preferred_send_hours
            self.campaigns.update_one(
                {"_id": campaign_id},
                {"$set": {"preferred_send_hours": preferred_send_hours}}
            )

        if self.decision_logger:
            self.decision_logger.log_decision(
                decision_type="performance_optimization",
                action="optimize_campaign",
                autonomous=True,
                campaign_id=campaign_id,
                confidence_score=max(0.85, totals["confidence_hint"]),
                reasoning={
                    "campaign_reply_rate": campaign_reply_rate,
                    "campaign_positive_reply_rate": campaign_positive_reply_rate,
                    "variant_metrics": variant_metrics
                },
                input_context={"campaign_id": campaign_id},
                decision_params=updates
            )

        self.campaigns.update_one(
            {"_id": campaign_id},
            {
                "$set": {
                    "variant_performance": variant_metrics,
                    "last_performance_optimization": datetime.utcnow(),
                    "performance_optimization_updates": updates
                }
            }
        )

        return {
            "campaign_id": campaign_id,
            "variant_metrics": variant_metrics,
            "updates": updates
        }

    def run_daily(self) -> Dict[str, Any]:
        campaigns = list(self.campaigns.find({}))
        results = []
        for campaign in campaigns:
            campaign_id = campaign.get("_id")
            if not campaign_id:
                continue
            results.append(self.optimize_campaign(campaign_id))
        return {"optimized": len(results), "results": results}

    def _compute_variant_metrics(self, campaign_id: str) -> Dict[str, Dict[str, float]]:
        sends = list(self.campaign_sends.find({"campaign_id": campaign_id}))
        if not sends:
            return {}

        variant_data: Dict[str, Dict[str, Any]] = {}
        for send in sends:
            variant_key = send.get("ab_variant") or send.get("template_id") or "default"
            data = variant_data.setdefault(variant_key, {
                "sample_size": 0,
                "opens": 0,
                "replies": 0
            })
            data["sample_size"] += 1
            if send.get("opened_at") or send.get("status") in ["opened", "clicked", "replied"]:
                data["opens"] += 1
            if send.get("replied_at") or send.get("status") == "replied":
                data["replies"] += 1

        positive_reply_counts = self._positive_replies_by_variant(campaign_id)

        metrics: Dict[str, Dict[str, float]] = {}
        for variant_key, data in variant_data.items():
            sample_size = data["sample_size"]
            opens = data["opens"]
            replies = data["replies"]
            positive_replies = positive_reply_counts.get(variant_key, 0)
            metrics[variant_key] = {
                "sample_size": sample_size,
                "open_rate": round(opens / sample_size, 4) if sample_size else 0.0,
                "reply_rate": round(replies / sample_size, 4) if sample_size else 0.0,
                "positive_reply_rate": round(positive_replies / sample_size, 4) if sample_size else 0.0
            }

        return metrics

    def _compute_campaign_totals(self, variant_metrics: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        total_sends = 0
        total_replies = 0
        total_positive = 0
        for metrics in variant_metrics.values():
            sample_size = metrics["sample_size"]
            total_sends += sample_size
            total_replies += metrics["reply_rate"] * sample_size
            total_positive += metrics["positive_reply_rate"] * sample_size

        reply_rate = total_replies / total_sends if total_sends else 0.0
        positive_reply_rate = total_positive / total_sends if total_sends else 0.0
        confidence_hint = 0.85 if total_sends >= self.MIN_SAMPLE_SIZE else 0.85

        return {
            "reply_rate": round(reply_rate, 4),
            "positive_reply_rate": round(positive_reply_rate, 4),
            "confidence_hint": confidence_hint
        }

    def _positive_replies_by_variant(self, campaign_id: str) -> Dict[str, int]:
        positive_replies = list(self.reply_decisions.find({
            "campaign_id": campaign_id,
            "classification": "positive_interest",
            "confidence_score": {"$gte": 0.85}
        }))

        if not positive_replies:
            return {}

        lead_ids = [r.get("lead_id") for r in positive_replies if r.get("lead_id")]
        recipients = list(self.campaign_recipients.find({
            "campaign_id": campaign_id,
            "lead_id": {"$in": lead_ids}
        }))

        lead_to_variant = {
            r.get("lead_id"): (r.get("ab_variant") or "default")
            for r in recipients
        }

        counts: Dict[str, int] = {}
        for reply in positive_replies:
            lead_id = reply.get("lead_id")
            variant = lead_to_variant.get(lead_id, "default")
            counts[variant] = counts.get(variant, 0) + 1

        return counts

    def _mark_variant_status(self, campaign_id: str, variant_key: str, status: str) -> None:
        self.email_variants.update_many(
            {"campaign_id": campaign_id, "variant_name": variant_key},
            {"$set": {"variant_status": status, "updated_at": datetime.utcnow()}}
        )
        self.campaigns.update_one(
            {"_id": campaign_id},
            {"$set": {f"variant_status.{variant_key}": status}}
        )

    def _boost_variant_weight(self, campaign_id: str, variant_key: str) -> float:
        campaign = self.campaigns.find_one({"_id": campaign_id}, {"variant_weights": 1}) or {}
        weights = campaign.get("variant_weights", {})
        current_weight = float(weights.get(variant_key, 1.0))
        new_weight = round(current_weight * self.WEIGHT_BOOST_FACTOR, 3)

        self.campaigns.update_one(
            {"_id": campaign_id},
            {"$set": {f"variant_weights.{variant_key}": new_weight}}
        )

        self.email_variants.update_many(
            {"campaign_id": campaign_id, "variant_name": variant_key},
            {"$set": {"variant_weight": new_weight, "updated_at": datetime.utcnow()}}
        )

        return new_weight

    def _compute_preferred_send_hours(self, campaign_id: str) -> Optional[List[int]]:
        since = datetime.utcnow() - timedelta(days=30)
        pipeline = [
            {
                "$match": {
                    "campaign_id": campaign_id,
                    "opened_at": {"$gte": since}
                }
            },
            {
                "$group": {
                    "_id": {"$hour": "$opened_at"},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"count": -1}}
        ]

        results = list(self.campaign_sends.aggregate(pipeline))
        if not results:
            return None

        top_hours = [r["_id"] for r in results[:2]]
        return sorted(top_hours)
