"""
TEMPLATE PERFORMANCE ANALYZER
==============================

Track email template performance across campaigns and provide intelligent
template recommendations based on recipient attributes.

Features:
- Template performance tracking (open rates, click rates, reply rates)
- Segmented performance analysis by industry, seniority, company size
- Template leaderboards and rankings
- Intelligent template recommendations for new leads
- A/B test variant performance comparison
- Historical performance trends

Collections:
- email_templates: Template definitions
- campaign_sends: Email send and engagement history
- campaigns: Campaign metadata
- leads: Lead attributes for segmentation

Usage:
    from analytics.template_performance import TemplatePerformanceAnalyzer
    
    analyzer = TemplatePerformanceAnalyzer(db)
    
    # Get performance stats for a template
    stats = analyzer.get_template_stats("template_123")
    # Returns: {
    #     "total_sends": 1500,
    #     "open_rate": 0.42,
    #     "click_rate": 0.18,
    #     "reply_rate": 0.08,
    #     "avg_time_to_open_hours": 2.5,
    #     "by_industry": {...},
    #     "by_seniority": {...}
    # }
    
    # Get top performing templates for a segment
    top_templates = analyzer.get_top_templates(
        industry="SaaS",
        seniority="VP",
        limit=5
    )
    
    # Suggest best template for a new lead
    recommendation = analyzer.suggest_template({
        "industry": "Technology",
        "seniority": "Director",
        "company_size": "mid"
    })

Requirements:
    pip install pandas numpy
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
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


class TemplatePerformanceAnalyzer:
    """
    Analyze email template performance across campaigns and segments.
    
    Tracks engagement metrics and provides intelligent recommendations.
    """
    
    def __init__(self, db):
        """
        Initialize the template performance analyzer.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.templates_col = db.email_templates
        self.sends_col = db.campaign_sends
        self.campaigns_col = db.campaigns
        self.leads_col = db.leads
        self.recipients_col = db.campaign_recipients
    
    def get_template_stats(
        self,
        template_id: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict:
        """
        Get comprehensive performance statistics for a template.
        
        Args:
            template_id: Template identifier
            date_from: Start date for analysis (default: all time)
            date_to: End date for analysis (default: now)
        
        Returns:
            Dict with performance metrics:
            {
                "template_id": "...",
                "template_name": "Initial Outreach - Tech VP",
                "total_sends": 1500,
                "open_rate": 0.42,
                "click_rate": 0.18,
                "reply_rate": 0.08,
                "bounce_rate": 0.02,
                "avg_time_to_open_hours": 2.5,
                "avg_time_to_reply_hours": 12.3,
                "by_industry": {"SaaS": {"sends": 500, "reply_rate": 0.09}, ...},
                "by_seniority": {"VP": {"sends": 800, "reply_rate": 0.10}, ...},
                "by_company_size": {"mid": {"sends": 600, "reply_rate": 0.085}, ...},
                "trend_last_30_days": [...]
            }
        """
        try:
            # Get template
            template = self.templates_col.find_one({"_id": ObjectId(template_id)})
            if not template:
                logger.error(f"Template {template_id} not found")
                return {}
            
            # Build query filter
            query = {"template_id": template_id}
            if date_from or date_to:
                query["sent_at"] = {}
                if date_from:
                    query["sent_at"]["$gte"] = date_from
                if date_to:
                    query["sent_at"]["$lte"] = date_to
            
            # Get all sends for this template
            sends = list(self.sends_col.find(query))
            
            if not sends:
                return {
                    "template_id": template_id,
                    "template_name": template.get("name", "Unknown"),
                    "total_sends": 0,
                    "message": "No sends found"
                }
            
            total_sends = len(sends)
            
            # Calculate basic metrics
            opens = sum(1 for s in sends if s.get("opened_at"))
            clicks = sum(1 for s in sends if s.get("clicked_at"))
            replies = sum(1 for s in sends if s.get("replied_at"))
            bounces = sum(1 for s in sends if s.get("status") == "bounced")
            
            open_rate = opens / total_sends if total_sends > 0 else 0
            click_rate = clicks / total_sends if total_sends > 0 else 0
            reply_rate = replies / total_sends if total_sends > 0 else 0
            bounce_rate = bounces / total_sends if total_sends > 0 else 0
            
            # Calculate time-to-engagement metrics
            open_times = []
            reply_times = []
            
            for send in sends:
                if send.get("sent_at") and send.get("opened_at"):
                    delta = send["opened_at"] - send["sent_at"]
                    open_times.append(delta.total_seconds() / 3600)  # hours
                
                if send.get("sent_at") and send.get("replied_at"):
                    delta = send["replied_at"] - send["sent_at"]
                    reply_times.append(delta.total_seconds() / 3600)  # hours
            
            avg_time_to_open = statistics.mean(open_times) if open_times else None
            avg_time_to_reply = statistics.mean(reply_times) if reply_times else None
            
            # Segmented performance analysis
            by_industry = self._segment_performance_by_attribute(
                sends, "industry"
            )
            by_seniority = self._segment_performance_by_attribute(
                sends, "seniority"
            )
            by_company_size = self._segment_performance_by_attribute(
                sends, "company_size"
            )
            
            # Trend analysis (last 30 days by week)
            trend = self._calculate_trend(template_id, days=30)
            
            return {
                "template_id": template_id,
                "template_name": template.get("name", "Unknown"),
                "template_category": template.get("category", "unknown"),
                "total_sends": total_sends,
                "open_rate": round(open_rate, 4),
                "click_rate": round(click_rate, 4),
                "reply_rate": round(reply_rate, 4),
                "bounce_rate": round(bounce_rate, 4),
                "avg_time_to_open_hours": round(avg_time_to_open, 2) if avg_time_to_open else None,
                "avg_time_to_reply_hours": round(avg_time_to_reply, 2) if avg_time_to_reply else None,
                "by_industry": by_industry,
                "by_seniority": by_seniority,
                "by_company_size": by_company_size,
                "trend_last_30_days": trend
            }
        
        except Exception as e:
            logger.error(f"Error getting template stats: {e}")
            return {"error": str(e)}
    
    def get_top_templates(
        self,
        industry: Optional[str] = None,
        seniority: Optional[str] = None,
        company_size: Optional[str] = None,
        metric: str = "reply_rate",
        limit: int = 5,
        min_sends: int = 50
    ) -> List[Dict]:
        """
        Get top performing templates, optionally filtered by segment.
        
        Args:
            industry: Filter by industry (e.g., "SaaS", "Enterprise")
            seniority: Filter by seniority (e.g., "VP", "Director")
            company_size: Filter by company size (e.g., "mid", "enterprise")
            metric: Ranking metric (default: "reply_rate")
                Options: "reply_rate", "open_rate", "click_rate"
            limit: Number of templates to return (default: 5)
            min_sends: Minimum sends required for inclusion (default: 50)
        
        Returns:
            List of top templates with stats:
            [
                {
                    "template_id": "...",
                    "template_name": "...",
                    "reply_rate": 0.12,
                    "total_sends": 500,
                    "rank": 1
                },
                ...
            ]
        """
        try:
            # Get all active templates
            templates = list(self.templates_col.find({"is_active": True}))
            
            template_scores = []
            
            for template in templates:
                template_id = str(template["_id"])
                
                # Build query for sends
                query = {"template_id": template_id}
                
                # If segment filters provided, join with recipients
                if industry or seniority or company_size:
                    # Get matching recipient IDs
                    lead_query = {}
                    if industry:
                        lead_query["industry"] = industry
                    if seniority:
                        lead_query["seniority"] = seniority
                    if company_size:
                        lead_query["company_size"] = company_size
                    
                    matching_leads = list(self.leads_col.find(
                        lead_query,
                        {"_id": 1}
                    ))
                    lead_ids = [str(l["_id"]) for l in matching_leads]
                    
                    # Get recipient IDs for these leads
                    matching_recipients = list(self.recipients_col.find(
                        {"lead_id": {"$in": lead_ids}},
                        {"_id": 1}
                    ))
                    recipient_ids = [str(r["_id"]) for r in matching_recipients]
                    
                    if not recipient_ids:
                        continue
                    
                    query["recipient_id"] = {"$in": recipient_ids}
                
                # Get sends
                sends = list(self.sends_col.find(query))
                
                if len(sends) < min_sends:
                    continue
                
                total_sends = len(sends)
                
                # Calculate metrics
                opens = sum(1 for s in sends if s.get("opened_at"))
                clicks = sum(1 for s in sends if s.get("clicked_at"))
                replies = sum(1 for s in sends if s.get("replied_at"))
                
                open_rate = opens / total_sends if total_sends > 0 else 0
                click_rate = clicks / total_sends if total_sends > 0 else 0
                reply_rate = replies / total_sends if total_sends > 0 else 0
                
                # Select score based on metric
                if metric == "open_rate":
                    score = open_rate
                elif metric == "click_rate":
                    score = click_rate
                else:  # reply_rate
                    score = reply_rate
                
                template_scores.append({
                    "template_id": template_id,
                    "template_name": template.get("name", "Unknown"),
                    "template_category": template.get("category", "unknown"),
                    "open_rate": round(open_rate, 4),
                    "click_rate": round(click_rate, 4),
                    "reply_rate": round(reply_rate, 4),
                    "total_sends": total_sends,
                    "score": score
                })
            
            # Sort by score descending
            template_scores.sort(key=lambda x: x["score"], reverse=True)
            
            # Add rank
            for i, template in enumerate(template_scores[:limit], 1):
                template["rank"] = i
                del template["score"]  # Remove internal score field
            
            return template_scores[:limit]
        
        except Exception as e:
            logger.error(f"Error getting top templates: {e}")
            return []
    
    def suggest_template(
        self,
        lead: Dict,
        metric: str = "reply_rate",
        min_sends: int = 30
    ) -> Dict:
        """
        Suggest the best template for a lead based on their attributes.
        
        Uses historical performance data to recommend templates that have
        performed well with similar leads (same industry, seniority, company size).
        
        Args:
            lead: Lead dictionary with attributes:
                {"industry": "SaaS", "seniority": "VP", "company_size": "mid"}
            metric: Optimization metric (default: "reply_rate")
            min_sends: Minimum sends required for recommendation (default: 30)
        
        Returns:
            Recommended template with confidence score:
            {
                "template_id": "...",
                "template_name": "...",
                "reply_rate": 0.12,
                "confidence": 0.85,
                "reason": "Best performing for SaaS VPs (120 sends, 12% reply rate)"
            }
        """
        try:
            industry = lead.get("industry")
            seniority = lead.get("seniority")
            company_size = lead.get("company_size")
            
            # Get top templates for this segment
            top_templates = self.get_top_templates(
                industry=industry,
                seniority=seniority,
                company_size=company_size,
                metric=metric,
                limit=3,
                min_sends=min_sends
            )
            
            if not top_templates:
                # Fallback: get overall top templates
                top_templates = self.get_top_templates(
                    metric=metric,
                    limit=3,
                    min_sends=min_sends
                )
                
                if not top_templates:
                    return {
                        "error": "No templates found",
                        "message": "Insufficient data for recommendation"
                    }
                
                # Lower confidence for generic recommendation
                recommendation = top_templates[0]
                recommendation["confidence"] = 0.5
                recommendation["reason"] = (
                    f"Generic recommendation (no segment-specific data). "
                    f"Overall {metric}: {recommendation[metric]:.1%}"
                )
                return recommendation
            
            # Best template for segment
            best = top_templates[0]
            
            # Calculate confidence based on sample size
            sends = best["total_sends"]
            if sends >= 100:
                confidence = 0.95
            elif sends >= 50:
                confidence = 0.85
            else:
                confidence = 0.70
            
            # Build reason string
            segment_parts = []
            if industry:
                segment_parts.append(industry)
            if seniority:
                segment_parts.append(f"{seniority}s")
            if company_size:
                segment_parts.append(f"{company_size}-size companies")
            
            segment_str = " ".join(segment_parts) if segment_parts else "similar leads"
            
            best["confidence"] = confidence
            best["reason"] = (
                f"Best performing for {segment_str} "
                f"({sends} sends, {best[metric]:.1%} {metric.replace('_', ' ')})"
            )
            
            return best
        
        except Exception as e:
            logger.error(f"Error suggesting template: {e}")
            return {"error": str(e)}
    
    def compare_variants(
        self,
        template_id: str,
        variant_a: str,
        variant_b: str
    ) -> Dict:
        """
        Compare performance of two A/B test variants.
        
        Args:
            template_id: Parent template ID
            variant_a: First variant identifier
            variant_b: Second variant identifier
        
        Returns:
            Comparison results with statistical significance
        """
        try:
            # Get sends for each variant
            sends_a = list(self.sends_col.find({
                "template_id": template_id,
                "ab_variant": variant_a
            }))
            
            sends_b = list(self.sends_col.find({
                "template_id": template_id,
                "ab_variant": variant_b
            }))
            
            if not sends_a or not sends_b:
                return {
                    "error": "Insufficient data",
                    "message": "Both variants need sends for comparison"
                }
            
            # Calculate metrics for both
            def calc_metrics(sends):
                total = len(sends)
                opens = sum(1 for s in sends if s.get("opened_at"))
                clicks = sum(1 for s in sends if s.get("clicked_at"))
                replies = sum(1 for s in sends if s.get("replied_at"))
                
                return {
                    "total_sends": total,
                    "open_rate": opens / total if total > 0 else 0,
                    "click_rate": clicks / total if total > 0 else 0,
                    "reply_rate": replies / total if total > 0 else 0
                }
            
            metrics_a = calc_metrics(sends_a)
            metrics_b = calc_metrics(sends_b)
            
            # Determine winner
            winner = None
            if metrics_a["reply_rate"] > metrics_b["reply_rate"]:
                winner = variant_a
                lift = (metrics_a["reply_rate"] - metrics_b["reply_rate"]) / metrics_b["reply_rate"] if metrics_b["reply_rate"] > 0 else None
            elif metrics_b["reply_rate"] > metrics_a["reply_rate"]:
                winner = variant_b
                lift = (metrics_b["reply_rate"] - metrics_a["reply_rate"]) / metrics_a["reply_rate"] if metrics_a["reply_rate"] > 0 else None
            else:
                lift = 0
            
            return {
                "template_id": template_id,
                "variant_a": {
                    "name": variant_a,
                    **metrics_a
                },
                "variant_b": {
                    "name": variant_b,
                    **metrics_b
                },
                "winner": winner,
                "lift_percentage": round(lift * 100, 2) if lift is not None else None
            }
        
        except Exception as e:
            logger.error(f"Error comparing variants: {e}")
            return {"error": str(e)}
    
    def _segment_performance_by_attribute(
        self,
        sends: List[Dict],
        attribute: str
    ) -> Dict:
        """
        Calculate performance metrics segmented by an attribute.
        
        Args:
            sends: List of send records
            attribute: Attribute to segment by (industry, seniority, company_size)
        
        Returns:
            Dict mapping attribute values to metrics
        """
        segments = defaultdict(lambda: {"sends": 0, "opens": 0, "clicks": 0, "replies": 0})
        
        for send in sends:
            recipient_id = send.get("recipient_id")
            if not recipient_id:
                continue
            
            # Get recipient to find lead_id
            recipient = self.recipients_col.find_one({"_id": ObjectId(recipient_id)})
            if not recipient or not recipient.get("lead_id"):
                continue
            
            # Get lead attributes
            lead = self.leads_col.find_one({"_id": ObjectId(recipient["lead_id"])})
            if not lead:
                continue
            
            attr_value = lead.get(attribute, "Unknown")
            
            segments[attr_value]["sends"] += 1
            if send.get("opened_at"):
                segments[attr_value]["opens"] += 1
            if send.get("clicked_at"):
                segments[attr_value]["clicks"] += 1
            if send.get("replied_at"):
                segments[attr_value]["replies"] += 1
        
        # Calculate rates
        result = {}
        for attr_value, stats in segments.items():
            total = stats["sends"]
            if total > 0:
                result[attr_value] = {
                    "sends": total,
                    "open_rate": round(stats["opens"] / total, 4),
                    "click_rate": round(stats["clicks"] / total, 4),
                    "reply_rate": round(stats["replies"] / total, 4)
                }
        
        return result
    
    def _calculate_trend(self, template_id: str, days: int = 30) -> List[Dict]:
        """
        Calculate performance trend over time.
        
        Args:
            template_id: Template identifier
            days: Number of days to analyze
        
        Returns:
            List of weekly performance snapshots
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            sends = list(self.sends_col.find({
                "template_id": template_id,
                "sent_at": {"$gte": cutoff_date}
            }))
            
            if not sends:
                return []
            
            # Group by week
            weeks = defaultdict(lambda: {"sends": 0, "opens": 0, "clicks": 0, "replies": 0})
            
            for send in sends:
                sent_at = send.get("sent_at")
                if not sent_at:
                    continue
                
                # Get week start (Monday)
                week_start = sent_at - timedelta(days=sent_at.weekday())
                week_key = week_start.strftime("%Y-%m-%d")
                
                weeks[week_key]["sends"] += 1
                if send.get("opened_at"):
                    weeks[week_key]["opens"] += 1
                if send.get("clicked_at"):
                    weeks[week_key]["clicks"] += 1
                if send.get("replied_at"):
                    weeks[week_key]["replies"] += 1
            
            # Convert to list and calculate rates
            trend = []
            for week, stats in sorted(weeks.items()):
                total = stats["sends"]
                trend.append({
                    "week_start": week,
                    "sends": total,
                    "open_rate": round(stats["opens"] / total, 4) if total > 0 else 0,
                    "click_rate": round(stats["clicks"] / total, 4) if total > 0 else 0,
                    "reply_rate": round(stats["replies"] / total, 4) if total > 0 else 0
                })
            
            return trend
        
        except Exception as e:
            logger.error(f"Error calculating trend: {e}")
            return []


# ============== EXAMPLE USAGE ==============

if __name__ == "__main__":
    from pymongo import MongoClient
    
    # Connect to database
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform
    
    analyzer = TemplatePerformanceAnalyzer(db)
    
    # Example: Get template statistics
    template_id = "60d5ec49f1a2c8b5e8c9a123"
    stats = analyzer.get_template_stats(template_id)
    print(f"\nTemplate Performance:")
    print(f"  Total sends: {stats.get('total_sends')}")
    print(f"  Reply rate: {stats.get('reply_rate', 0):.1%}")
    print(f"  Avg time to reply: {stats.get('avg_time_to_reply_hours')} hours")
    
    # Example: Get top templates for a segment
    top_templates = analyzer.get_top_templates(
        industry="SaaS",
        seniority="VP",
        limit=5
    )
    print(f"\nTop Templates for SaaS VPs:")
    for template in top_templates:
        print(f"  {template['rank']}. {template['template_name']}")
        print(f"     Reply rate: {template['reply_rate']:.1%} ({template['total_sends']} sends)")
    
    # Example: Suggest template for a lead
    lead = {
        "industry": "Technology",
        "seniority": "Director",
        "company_size": "mid"
    }
    recommendation = analyzer.suggest_template(lead)
    print(f"\nRecommended template: {recommendation.get('template_name')}")
    print(f"  Confidence: {recommendation.get('confidence', 0):.1%}")
    print(f"  Reason: {recommendation.get('reason')}")
