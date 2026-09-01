"""
SEND TIME OPTIMIZER SERVICE
=============================

ML-based optimal send time prediction and engagement pattern analysis.

Features:
- Analyze historical engagement data (opens, clicks) by hour and day of week
- Build per-recipient optimal send time model
- Batch optimize campaign schedule based on recipient patterns
- Fallback to timezone-based defaults if insufficient historical data
- Confidence scoring for predictions

Collections:
- campaign_sends: Historical email engagement data
- leads: Recipient/lead information including timezone
- campaigns: Campaign metadata

Usage:
    from campaigns.send_time_optimizer import SendTimeOptimizer
    
    optimizer = SendTimeOptimizer(db)
    
    # Analyze historical engagement for a recipient
    patterns = optimizer.analyze_engagement_by_time(lead_id="abc123")
    # Returns: {"Monday": {"9": 0.45, "10": 0.52, ...}, ...}
    
    # Get predicted optimal send time for a recipient
    optimal = optimizer.predict_optimal_send_time(lead_id="abc123")
    # Returns: {"day": "Tuesday", "hour": 10, "confidence": 0.87}
    
    # Reorder campaign recipients by optimal send times
    schedule = optimizer.batch_optimize_schedule(campaign_id="campaign_456")
    # Returns: {"optimized_recipients": [...], "metrics": {...}}

Requirements:
    pip install pandas numpy
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from bson import ObjectId
import logging
from collections import defaultdict
import statistics

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logging.warning("pandas/numpy not installed. Install with: pip install pandas numpy")

logger = logging.getLogger(__name__)

# Default timezone to hour mappings for fallback
DEFAULT_HOUR_PREFERENCES = {
    "UTC": [9, 10, 14, 15],
    "EST": [9, 10, 14, 15],
    "CST": [10, 11, 15, 16],
    "MST": [10, 11, 15, 16],
    "PST": [9, 10, 13, 14],
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOURS_IN_DAY = list(range(24))


class SendTimeOptimizer:
    """
    Service for predicting and optimizing email send times based on historical engagement data.
    
    Attributes:
        db: MongoDB database instance
        min_data_points: Minimum engagement events required to make predictions
        engagement_window_days: How far back to look for historical data
    """
    
    def __init__(self, db, min_data_points: int = 5, engagement_window_days: int = 90):
        """
        Initialize the send time optimizer.
        
        Args:
            db: MongoDB database instance
            min_data_points: Minimum events required per hour/day combo for reliable patterns
            engagement_window_days: Days of historical data to analyze (default 90 days)
        """
        self.db = db
        self.sends_col = db.campaign_sends
        self.leads_col = db.leads
        self.campaigns_col = db.campaigns
        self.min_data_points = min_data_points
        self.engagement_window_days = engagement_window_days
    
    def analyze_engagement_by_time(self, lead_id: str) -> Dict[str, Dict[int, float]]:
        """
        Analyze historical engagement data for a lead grouped by day of week and hour.
        
        Calculates engagement rates (opens/clicks) for each hour and day combination.
        
        Args:
            lead_id: Lead/recipient ID to analyze
        
        Returns:
            Dict with structure:
            {
                "Monday": {9: 0.45, 10: 0.52, ...},
                "Tuesday": {9: 0.38, 10: 0.60, ...},
                ...
            }
        """
        try:
            # Query campaign sends for this lead
            lead_obj_id = self._to_object_id(lead_id)
            
            cutoff_date = datetime.utcnow() - timedelta(days=self.engagement_window_days)
            
            sends = list(self.sends_col.find({
                "lead_id": lead_obj_id,
                "sent_at": {"$gte": cutoff_date},
                "status": {"$in": ["sent", "delivered", "opened", "clicked"]}
            }).sort("sent_at", -1))
            
            if not sends:
                logger.info(f"No sends found for lead {lead_id} in last {self.engagement_window_days} days")
                return {}
            
            # Group by day of week and hour
            engagement_by_time = defaultdict(lambda: defaultdict(list))
            
            for send in sends:
                sent_time = send.get("sent_at")
                if not sent_time:
                    continue
                
                # Get day of week and hour
                day_of_week = DAYS_OF_WEEK[sent_time.weekday()]
                hour = sent_time.hour
                
                # Track engagement
                is_engaged = send.get("status") in ["opened", "clicked"]
                engagement_by_time[day_of_week][hour].append(int(is_engaged))
            
            # Calculate open rates for each hour/day
            result = {}
            for day in DAYS_OF_WEEK:
                if day in engagement_by_time:
                    day_data = {}
                    for hour in HOURS_IN_DAY:
                        engagements = engagement_by_time[day].get(hour, [])
                        if len(engagements) >= self.min_data_points:
                            open_rate = sum(engagements) / len(engagements)
                            day_data[hour] = round(open_rate, 3)
                    
                    if day_data:
                        result[day] = day_data
            
            return result
        
        except Exception as e:
            logger.error(f"Error analyzing engagement for lead {lead_id}: {e}")
            return {}
    
    def predict_optimal_send_time(self, lead_id: str) -> Dict[str, Any]:
        """
        Predict the optimal send time for a specific lead based on historical engagement.
        
        Finds the hour and day with the highest engagement rate.
        Includes confidence score based on data volume.
        
        Args:
            lead_id: Lead/recipient ID to predict for
        
        Returns:
            Dict with structure:
            {
                "day": "Tuesday",
                "hour": 10,
                "confidence": 0.87,
                "open_rate": 0.65,
                "data_points": 23,
                "fallback": False
            }
        """
        try:
            # Get engagement patterns
            engagement_data = self.analyze_engagement_by_time(lead_id)
            
            if not engagement_data:
                # Fallback to timezone-based default
                return self._get_timezone_default_send_time(lead_id)
            
            # Find best performing hour and day
            best_score = 0
            best_day = None
            best_hour = None
            best_data_points = 0
            
            for day, hours_data in engagement_data.items():
                for hour, engagement_rate in hours_data.items():
                    if engagement_rate > best_score:
                        best_score = engagement_rate
                        best_day = day
                        best_hour = hour
                        # Count data points for this hour/day combo
                        lead_obj_id = self._to_object_id(lead_id)
                        cutoff_date = datetime.utcnow() - timedelta(days=self.engagement_window_days)
                        
                        count = self.sends_col.count_documents({
                            "lead_id": lead_obj_id,
                            "sent_at": {"$gte": cutoff_date}
                        })
                        best_data_points = count
            
            if best_day is None or best_hour is None:
                return self._get_timezone_default_send_time(lead_id)
            
            # Calculate confidence based on data volume
            # More data points = higher confidence
            confidence = min(0.95, 0.5 + (best_data_points / 50) * 0.45)
            confidence = round(confidence, 2)
            
            return {
                "day": best_day,
                "hour": best_hour,
                "confidence": confidence,
                "open_rate": round(best_score, 3),
                "data_points": best_data_points,
                "fallback": False
            }
        
        except Exception as e:
            logger.error(f"Error predicting send time for lead {lead_id}: {e}")
            return self._get_timezone_default_send_time(lead_id)
    
    def batch_optimize_schedule(self, campaign_id: str) -> Dict[str, Any]:
        """
        Optimize send schedule for all recipients in a campaign.
        
        Reorders recipients to group by optimal send times, enabling more efficient
        sending (e.g., send all 10am recipients together, then 11am, etc.).
        
        Args:
            campaign_id: Campaign ID to optimize
        
        Returns:
            Dict with structure:
            {
                "campaign_id": "campaign_123",
                "optimized_recipients": [
                    {
                        "recipient_id": "lead_456",
                        "optimal_day": "Tuesday",
                        "optimal_hour": 10,
                        "confidence": 0.87,
                        "send_order": 1
                    },
                    ...
                ],
                "metrics": {
                    "total_recipients": 500,
                    "with_predictions": 350,
                    "confidence_high": 200,
                    "confidence_medium": 120,
                    "confidence_low": 30,
                    "fallback_defaults": 150
                }
            }
        """
        try:
            campaign_obj_id = self._to_object_id(campaign_id)
            
            # Get campaign recipients
            recipients = list(self.db.campaign_recipients.find({
                "campaign_id": campaign_obj_id,
                "status": {"$in": ["pending", "in_sequence"]}
            }))
            
            if not recipients:
                logger.warning(f"No recipients found for campaign {campaign_id}")
                return {
                    "campaign_id": campaign_id,
                    "optimized_recipients": [],
                    "metrics": {
                        "total_recipients": 0,
                        "with_predictions": 0,
                        "confidence_high": 0,
                        "confidence_medium": 0,
                        "confidence_low": 0,
                        "fallback_defaults": 0
                    }
                }
            
            optimized_recipients = []
            metrics = {
                "total_recipients": len(recipients),
                "with_predictions": 0,
                "confidence_high": 0,
                "confidence_medium": 0,
                "confidence_low": 0,
                "fallback_defaults": 0
            }
            
            # Get optimal times for each recipient
            for idx, recipient in enumerate(recipients):
                lead_id = str(recipient.get("lead_id"))
                optimal_time = self.predict_optimal_send_time(lead_id)
                
                confidence = optimal_time.get("confidence", 0)
                if optimal_time.get("fallback"):
                    metrics["fallback_defaults"] += 1
                else:
                    metrics["with_predictions"] += 1
                
                if confidence >= 0.8:
                    metrics["confidence_high"] += 1
                elif confidence >= 0.6:
                    metrics["confidence_medium"] += 1
                else:
                    metrics["confidence_low"] += 1
                
                optimized_recipients.append({
                    "recipient_id": lead_id,
                    "optimal_day": optimal_time.get("day"),
                    "optimal_hour": optimal_time.get("hour"),
                    "confidence": confidence,
                    "send_order": idx + 1,
                    "open_rate": optimal_time.get("open_rate"),
                    "data_points": optimal_time.get("data_points", 0)
                })
            
            # Sort by optimal hour for efficient batch sending
            # Group by hour, then by day
            def sort_key(item):
                day_idx = DAYS_OF_WEEK.index(item["optimal_day"]) if item["optimal_day"] in DAYS_OF_WEEK else 0
                hour = item["optimal_hour"] if item["optimal_hour"] is not None else 0
                return (hour, day_idx)
            
            optimized_recipients.sort(key=sort_key)
            
            # Re-number send order after sorting
            for idx, recipient in enumerate(optimized_recipients):
                recipient["send_order"] = idx + 1
            
            return {
                "campaign_id": campaign_id,
                "optimized_recipients": optimized_recipients,
                "metrics": metrics,
                "optimization_timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error optimizing schedule for campaign {campaign_id}: {e}")
            return {
                "campaign_id": campaign_id,
                "optimized_recipients": [],
                "metrics": {
                    "total_recipients": 0,
                    "error": str(e)
                }
            }
    
    def _get_timezone_default_send_time(self, lead_id: str) -> Dict[str, Any]:
        """
        Get default send time based on recipient's timezone.
        
        Used as fallback when insufficient historical data exists.
        
        Args:
            lead_id: Lead/recipient ID
        
        Returns:
            Default send time dict with fallback flag set to True
        """
        try:
            lead_obj_id = self._to_object_id(lead_id)
            lead = self.leads_col.find_one({"_id": lead_obj_id})
            
            if not lead:
                timezone = "UTC"
            else:
                timezone = lead.get("timezone", "UTC")
            
            # Get preferred hours for timezone
            preferred_hours = DEFAULT_HOUR_PREFERENCES.get(timezone, [9, 10, 14, 15])
            
            # Pick midday if available
            if 10 in preferred_hours:
                hour = 10
            elif 14 in preferred_hours:
                hour = 14
            else:
                hour = preferred_hours[0] if preferred_hours else 9
            
            # Default to Tuesday (mid-week)
            return {
                "day": "Tuesday",
                "hour": hour,
                "confidence": 0.45,
                "fallback": True,
                "timezone": timezone,
                "data_points": 0,
                "reason": "Insufficient historical data - using timezone default"
            }
        
        except Exception as e:
            logger.error(f"Error getting timezone default for lead {lead_id}: {e}")
            return {
                "day": "Tuesday",
                "hour": 10,
                "confidence": 0.40,
                "fallback": True,
                "data_points": 0,
                "reason": "Error accessing lead data - using system default"
            }
    
    def _to_object_id(self, value: Any) -> ObjectId:
        """Convert string to ObjectId if needed."""
        if isinstance(value, ObjectId):
            return value
        try:
            return ObjectId(value)
        except Exception:
            return ObjectId()


class EngagementMetricsAnalyzer:
    """
    Analyze and aggregate engagement metrics for send time optimization.
    
    Provides summary statistics and trending analysis.
    """
    
    def __init__(self, db):
        """Initialize metrics analyzer."""
        self.db = db
        self.sends_col = db.campaign_sends
    
    def get_engagement_summary(self, lead_id: str, days: int = 30) -> Dict[str, Any]:
        """
        Get engagement summary for a lead over a time period.
        
        Args:
            lead_id: Lead ID
            days: Number of days to analyze
        
        Returns:
            Summary dict with open rate, click rate, average response time, etc.
        """
        try:
            lead_obj_id = ObjectId(lead_id) if isinstance(lead_id, str) else lead_id
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            sends = list(self.sends_col.find({
                "lead_id": lead_obj_id,
                "sent_at": {"$gte": cutoff_date}
            }))
            
            if not sends:
                return {
                    "lead_id": lead_id,
                    "days_analyzed": days,
                    "total_sends": 0,
                    "engagement_rate": 0,
                    "open_rate": 0,
                    "click_rate": 0,
                    "reply_rate": 0
                }
            
            opened = sum(1 for s in sends if s.get("status") in ["opened", "clicked", "replied"])
            clicked = sum(1 for s in sends if s.get("status") in ["clicked", "replied"])
            replied = sum(1 for s in sends if s.get("status") == "replied")
            
            total = len(sends)
            
            return {
                "lead_id": lead_id,
                "days_analyzed": days,
                "total_sends": total,
                "engagement_rate": round(opened / total, 3),
                "open_rate": round(opened / total, 3),
                "click_rate": round(clicked / total, 3),
                "reply_rate": round(replied / total, 3),
                "last_send": max(s.get("sent_at") for s in sends if s.get("sent_at")).isoformat() if sends else None
            }
        
        except Exception as e:
            logger.error(f"Error getting engagement summary for lead {lead_id}: {e}")
            return {"error": str(e)}
