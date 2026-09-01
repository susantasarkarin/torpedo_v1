"""
ENGAGEMENT PATTERNS ANALYZER
=============================

ML service for detecting recipient behavior patterns and predicting optimal contact strategies.

Features:
- Detect engagement patterns (response latency, preferred contact frequency)
- Analyze segment performance to identify trends
- Suggest optimal contact frequency per segment
- Identify best days of week per industry/seniority
- Calculate engagement momentum and trajectory

Collections:
- campaign_sends: Email send and engagement history
- campaign_recipients: Recipient status and history
- leads: Lead metadata including industry, seniority, company size
- campaigns: Campaign metadata

Usage:
    from analytics.engagement_patterns import EngagementPatternAnalyzer
    
    analyzer = EngagementPatternAnalyzer(db)
    
    # Detect patterns for a specific lead
    patterns = analyzer.detect_patterns(lead_id="abc123")
    # Returns: {"open_latency_hours": 2.5, "click_latency_hours": 4.2, ...}
    
    # Suggest contact frequency for a segment
    frequency = analyzer.suggest_contact_frequency(industry="SaaS", seniority="VP")
    # Returns: {"days_between_contacts": 3, "weekly_contacts": 2, "confidence": 0.8}
    
    # Analyze performance across a segment
    performance = analyzer.analyze_segment_performance(
        segment_filter={"industry": "Technology", "company_size": "mid"}
    )

Requirements:
    pip install pandas numpy scipy
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
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
    logging.warning("pandas/numpy not installed")

logger = logging.getLogger(__name__)

# Default contact frequency recommendations by segment
DEFAULT_FREQUENCY_RECOMMENDATIONS = {
    "SaaS": {
        "C-Level": {"days_between_contacts": 5, "weekly_contacts": 1.5},
        "VP": {"days_between_contacts": 4, "weekly_contacts": 2},
        "Director": {"days_between_contacts": 3, "weekly_contacts": 2.5},
        "Manager": {"days_between_contacts": 2, "weekly_contacts": 3},
        "Other": {"days_between_contacts": 3, "weekly_contacts": 2}
    },
    "Enterprise": {
        "C-Level": {"days_between_contacts": 7, "weekly_contacts": 1},
        "VP": {"days_between_contacts": 5, "weekly_contacts": 1.5},
        "Director": {"days_between_contacts": 4, "weekly_contacts": 2},
        "Manager": {"days_between_contacts": 3, "weekly_contacts": 2.5},
        "Other": {"days_between_contacts": 4, "weekly_contacts": 2}
    },
    "Mid-Market": {
        "C-Level": {"days_between_contacts": 4, "weekly_contacts": 2},
        "VP": {"days_between_contacts": 3, "weekly_contacts": 2.5},
        "Director": {"days_between_contacts": 2, "weekly_contacts": 3},
        "Manager": {"days_between_contacts": 2, "weekly_contacts": 3},
        "Other": {"days_between_contacts": 3, "weekly_contacts": 2}
    }
}

BEST_DAYS_BY_SEGMENT = {
    "SaaS": {
        "C-Level": ["Tuesday", "Wednesday", "Thursday"],
        "VP": ["Tuesday", "Wednesday", "Thursday"],
        "Director": ["Monday", "Tuesday", "Wednesday", "Thursday"],
        "Manager": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    },
    "Enterprise": {
        "C-Level": ["Tuesday", "Wednesday"],
        "VP": ["Monday", "Tuesday", "Wednesday"],
        "Director": ["Monday", "Tuesday", "Wednesday", "Thursday"],
        "Manager": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    }
}


class EngagementPatternAnalyzer:
    """
    Service for analyzing recipient and segment engagement patterns.
    
    Detects behavioral patterns that inform optimal contact strategies.
    """
    
    def __init__(self, db, lookback_days: int = 90):
        """
        Initialize pattern analyzer.
        
        Args:
            db: MongoDB database instance
            lookback_days: Historical data window (default 90 days)
        """
        self.db = db
        self.sends_col = db.campaign_sends
        self.recipients_col = db.campaign_recipients
        self.leads_col = db.leads
        self.campaigns_col = db.campaigns
        self.lookback_days = lookback_days
    
    def detect_patterns(self, lead_id: str) -> Dict[str, Any]:
        """
        Detect engagement behavior patterns for a specific lead.
        
        Analyzes:
        - Response latency (how quickly lead opens/clicks)
        - Reply likelihood and timing
        - Day of week preferences
        - Engagement momentum (trending up/down)
        - Optimal contact frequency
        
        Args:
            lead_id: Lead ID to analyze
        
        Returns:
            Dict with detected patterns:
            {
                "lead_id": "abc123",
                "open_latency_hours": 2.5,
                "click_latency_hours": 4.2,
                "reply_latency_hours": 24.5,
                "reply_likelihood": 0.45,
                "preferred_days": ["Tuesday", "Wednesday"],
                "engagement_momentum": 0.8,  # 0-1, trending up
                "last_engagement": "2024-01-25T14:30:00",
                "total_sends_analyzed": 15,
                "high_value_indicator": True
            }
        """
        try:
            lead_obj_id = self._to_object_id(lead_id)
            cutoff_date = datetime.utcnow() - timedelta(days=self.lookback_days)
            
            sends = list(self.sends_col.find({
                "lead_id": lead_obj_id,
                "sent_at": {"$gte": cutoff_date}
            }).sort("sent_at", 1))
            
            if not sends:
                return {
                    "lead_id": lead_id,
                    "total_sends_analyzed": 0,
                    "patterns_found": False,
                    "reason": "Insufficient historical data"
                }
            
            # Calculate latencies
            latencies = {
                "open": [],
                "click": [],
                "reply": []
            }
            
            preferred_days = defaultdict(int)
            engagement_by_date = []
            
            for send in sends:
                sent_at = send.get("sent_at")
                status = send.get("status", "")
                
                # Track preferred days
                if status in ["opened", "clicked", "replied"]:
                    day_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][sent_at.weekday()]
                    preferred_days[day_of_week] += 1
                
                # Calculate latencies
                if status == "opened" and "opened_at" in send:
                    opened_at = send["opened_at"]
                    latency_hours = (opened_at - sent_at).total_seconds() / 3600
                    latencies["open"].append(latency_hours)
                
                if status == "clicked" and "clicked_at" in send:
                    clicked_at = send["clicked_at"]
                    latency_hours = (clicked_at - sent_at).total_seconds() / 3600
                    latencies["click"].append(latency_hours)
                
                if status == "replied" and "replied_at" in send:
                    replied_at = send["replied_at"]
                    latency_hours = (replied_at - sent_at).total_seconds() / 3600
                    latencies["reply"].append(latency_hours)
                
                # Track engagement momentum
                engagement_by_date.append({
                    "date": sent_at,
                    "engaged": status in ["opened", "clicked", "replied"]
                })
            
            # Calculate momentum (comparing recent vs older)
            mid_point = len(engagement_by_date) // 2
            if mid_point > 0:
                old_engagement_rate = sum(1 for e in engagement_by_date[:mid_point] if e["engaged"]) / mid_point
                new_engagement_rate = sum(1 for e in engagement_by_date[mid_point:] if e["engaged"]) / max(1, len(engagement_by_date) - mid_point)
                
                if old_engagement_rate > 0:
                    momentum = min(1.0, new_engagement_rate / old_engagement_rate)
                else:
                    momentum = 1.0 if new_engagement_rate > 0 else 0.5
            else:
                momentum = 0.5
            
            # Get top days
            if preferred_days:
                top_days = sorted(preferred_days.items(), key=lambda x: x[1], reverse=True)
                top_days_list = [day for day, count in top_days[:3]]
            else:
                top_days_list = []
            
            # Calculate average latencies
            result = {
                "lead_id": lead_id,
                "total_sends_analyzed": len(sends),
                "open_latency_hours": round(statistics.mean(latencies["open"]), 1) if latencies["open"] else None,
                "click_latency_hours": round(statistics.mean(latencies["click"]), 1) if latencies["click"] else None,
                "reply_latency_hours": round(statistics.mean(latencies["reply"]), 1) if latencies["reply"] else None,
                "reply_likelihood": round(sum(1 for s in sends if s.get("status") == "replied") / len(sends), 3),
                "preferred_days": top_days_list,
                "engagement_momentum": round(momentum, 2),
                "last_engagement": max([s.get("sent_at") for s in sends if s.get("status") in ["opened", "clicked", "replied"]], default=None),
                "patterns_found": True,
                "high_value_indicator": self._is_high_value_lead(sends, latencies)
            }
            
            return result
        
        except Exception as e:
            logger.error(f"Error detecting patterns for lead {lead_id}: {e}")
            return {"error": str(e), "lead_id": lead_id}
    
    def suggest_contact_frequency(self, industry: str, seniority: str) -> Dict[str, Any]:
        """
        Suggest optimal contact frequency for a specific segment.
        
        Uses segment benchmarks and historical performance data.
        
        Args:
            industry: Industry segment (e.g., "SaaS", "Enterprise")
            seniority: Seniority level (e.g., "VP", "Director")
        
        Returns:
            Dict with recommendations:
            {
                "industry": "SaaS",
                "seniority": "VP",
                "days_between_contacts": 4,
                "weekly_contacts": 2.0,
                "confidence": 0.8,
                "best_days": ["Tuesday", "Wednesday", "Thursday"],
                "avoid_days": ["Friday", "Saturday", "Sunday"]
            }
        """
        try:
            # Get historical performance for this segment
            segment_leads = list(self.leads_col.find({
                "industry": industry,
                "seniority_level": seniority
            }).limit(100))
            
            if not segment_leads:
                # Return defaults
                recommendation = DEFAULT_FREQUENCY_RECOMMENDATIONS.get(
                    industry, 
                    DEFAULT_FREQUENCY_RECOMMENDATIONS["Mid-Market"]
                ).get(seniority, {"days_between_contacts": 3, "weekly_contacts": 2})
                
                return {
                    "industry": industry,
                    "seniority": seniority,
                    **recommendation,
                    "confidence": 0.5,
                    "based_on_segment_size": len(segment_leads),
                    "best_days": BEST_DAYS_BY_SEGMENT.get(industry, {}).get(seniority, ["Tuesday", "Wednesday", "Thursday"]),
                    "avoid_days": ["Saturday", "Sunday"]
                }
            
            # Analyze actual performance for segment
            lead_ids = [str(lead.get("_id")) for lead in segment_leads]
            
            contact_intervals = []
            for lead_id in lead_ids:
                patterns = self.detect_patterns(lead_id)
                if patterns.get("reply_likelihood", 0) > 0:
                    contact_intervals.append(patterns.get("reply_likelihood", 0))
            
            # Calculate recommended frequency
            if contact_intervals:
                avg_likelihood = statistics.mean(contact_intervals)
                # More likely to respond = can contact more frequently
                weekly_contacts = min(4, max(1, 1 + (avg_likelihood * 3)))
                days_between = max(1, int(7 / weekly_contacts))
            else:
                weekly_contacts = 2
                days_between = 3
            
            return {
                "industry": industry,
                "seniority": seniority,
                "days_between_contacts": days_between,
                "weekly_contacts": round(weekly_contacts, 1),
                "confidence": min(0.95, 0.4 + len(segment_leads) / 100),
                "based_on_segment_size": len(segment_leads),
                "best_days": BEST_DAYS_BY_SEGMENT.get(industry, {}).get(seniority, ["Tuesday", "Wednesday", "Thursday"]),
                "avoid_days": ["Saturday", "Sunday"],
                "reasoning": f"Based on {len(segment_leads)} leads in segment with avg {round(avg_likelihood, 2)} reply likelihood"
            }
        
        except Exception as e:
            logger.error(f"Error suggesting frequency for {industry}/{seniority}: {e}")
            return {
                "error": str(e),
                "industry": industry,
                "seniority": seniority
            }
    
    def analyze_segment_performance(self, segment_filter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze performance metrics across a segment of leads.
        
        Groups leads by defined criteria and calculates aggregate metrics.
        
        Args:
            segment_filter: MongoDB filter dict (e.g., {"industry": "SaaS", "company_size": "mid"})
        
        Returns:
            Dict with segment performance:
            {
                "segment_filter": {...},
                "total_leads": 150,
                "avg_open_rate": 0.45,
                "avg_click_rate": 0.12,
                "avg_reply_rate": 0.08,
                "engagement_momentum": 0.75,
                "best_performing_day": "Tuesday",
                "best_performing_hour": 10,
                "recommended_contact_frequency": 3,
                "segment_trends": {...}
            }
        """
        try:
            # Find leads matching segment
            segment_leads = list(self.leads_col.find(segment_filter).limit(500))
            
            if not segment_leads:
                return {
                    "segment_filter": segment_filter,
                    "total_leads": 0,
                    "error": "No leads found for segment"
                }
            
            lead_ids = [str(lead.get("_id")) for lead in segment_leads]
            
            # Aggregate metrics
            open_rates = []
            click_rates = []
            reply_rates = []
            momentums = []
            
            day_performance = defaultdict(list)
            hour_performance = defaultdict(list)
            
            cutoff_date = datetime.utcnow() - timedelta(days=self.lookback_days)
            
            for lead_id in lead_ids:
                sends = list(self.sends_col.find({
                    "lead_id": ObjectId(lead_id),
                    "sent_at": {"$gte": cutoff_date}
                }))
                
                if sends:
                    opened = sum(1 for s in sends if s.get("status") in ["opened", "clicked", "replied"])
                    clicked = sum(1 for s in sends if s.get("status") in ["clicked", "replied"])
                    replied = sum(1 for s in sends if s.get("status") == "replied")
                    
                    total = len(sends)
                    open_rates.append(opened / total if total > 0 else 0)
                    click_rates.append(clicked / total if total > 0 else 0)
                    reply_rates.append(replied / total if total > 0 else 0)
                    
                    # Track day/hour performance
                    for send in sends:
                        if send.get("status") in ["opened", "clicked", "replied"]:
                            sent_at = send.get("sent_at")
                            day_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][sent_at.weekday()]
                            hour = sent_at.hour
                            
                            day_performance[day_of_week].append(1)
                            hour_performance[hour].append(1)
                    
                    # Get momentum
                    patterns = self.detect_patterns(lead_id)
                    if "engagement_momentum" in patterns:
                        momentums.append(patterns["engagement_momentum"])
            
            # Find best performing day/hour
            best_day = max(day_performance.items(), key=lambda x: len(x[1]))[0] if day_performance else "Tuesday"
            best_hour = max(hour_performance.items(), key=lambda x: len(x[1]))[0] if hour_performance else 10
            
            return {
                "segment_filter": segment_filter,
                "total_leads": len(segment_leads),
                "avg_open_rate": round(statistics.mean(open_rates), 3) if open_rates else 0,
                "avg_click_rate": round(statistics.mean(click_rates), 3) if click_rates else 0,
                "avg_reply_rate": round(statistics.mean(reply_rates), 3) if reply_rates else 0,
                "engagement_momentum": round(statistics.mean(momentums), 2) if momentums else 0.5,
                "best_performing_day": best_day,
                "best_performing_hour": best_hour,
                "recommended_contact_frequency": self._recommend_frequency_from_rates(
                    statistics.mean(reply_rates) if reply_rates else 0
                ),
                "high_performers_count": sum(1 for r in reply_rates if r > 0.15),
                "analysis_period_days": self.lookback_days
            }
        
        except Exception as e:
            logger.error(f"Error analyzing segment {segment_filter}: {e}")
            return {"error": str(e), "segment_filter": segment_filter}
    
    def _is_high_value_lead(self, sends: List[Dict], latencies: Dict[str, List]) -> bool:
        """Determine if a lead is high-value based on engagement patterns."""
        if not sends:
            return False
        
        reply_rate = sum(1 for s in sends if s.get("status") == "replied") / len(sends)
        has_fast_response = len(latencies["open"]) > 0 and statistics.mean(latencies["open"]) < 6
        
        return reply_rate > 0.2 or has_fast_response
    
    def _recommend_frequency_from_rates(self, reply_rate: float) -> int:
        """Convert reply rate to recommended contact frequency (days between contacts)."""
        if reply_rate < 0.05:
            return 7  # Contact weekly
        elif reply_rate < 0.10:
            return 5  # Every 5 days
        elif reply_rate < 0.15:
            return 3  # Every 3 days
        else:
            return 2  # Every 2 days
    
    def _to_object_id(self, value: Any) -> ObjectId:
        """Convert string to ObjectId if needed."""
        if isinstance(value, ObjectId):
            return value
        try:
            return ObjectId(value)
        except Exception:
            return ObjectId()
