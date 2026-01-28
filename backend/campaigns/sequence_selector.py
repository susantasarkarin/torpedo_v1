"""
SEQUENCE SELECTOR - INTELLIGENT SEQUENCE RECOMMENDATION
========================================================

Analyze lead attributes and select optimal email sequences from library
based on historical performance data.

Features:
- Lead attribute analysis (industry, seniority, company size, engagement level)
- Sequence performance tracking by segment
- Intelligent sequence selection with confidence scoring
- Multi-criteria recommendation (reply rate, engagement, conversion)
- Fallback to default sequences when data is limited

Collections:
- campaign_sequences: Available sequence definitions
- campaigns: Campaign metadata and sequences
- campaign_sends: Historical send and engagement data
- leads: Lead attributes for matching

Usage:
    from campaigns.sequence_selector import SequenceSelector
    
    selector = SequenceSelector(db)
    
    # Select optimal sequence for a lead
    sequence_id = selector.select_optimal_sequence({
        "industry": "SaaS",
        "seniority": "VP",
        "company_size": "mid",
        "engagement_level": "cold"
    })
    
    # Get top 3 sequence recommendations with reasoning
    recommendations = selector.get_sequence_recommendations({
        "industry": "Technology",
        "seniority": "Director",
        "company_size": "enterprise"
    })
    # Returns: [
    #     {
    #         "sequence_id": "seq_123",
    #         "sequence_name": "Tech Enterprise - 5 Touch",
    #         "confidence": 0.85,
    #         "expected_reply_rate": 0.12,
    #         "reason": "Best performing for Tech Directors at enterprise companies"
    #     },
    #     ...
    # ]

Requirements:
    pip install numpy
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from bson import ObjectId
import logging
from collections import defaultdict

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logging.warning("numpy not installed")

logger = logging.getLogger(__name__)


# Default sequence recommendations by segment
DEFAULT_SEQUENCES = {
    "SaaS": {
        "C-Level": {
            "cold": "saas_c_level_cold_5touch",
            "warm": "saas_c_level_warm_3touch",
            "engaged": "saas_c_level_engaged_2touch"
        },
        "VP": {
            "cold": "saas_vp_cold_6touch",
            "warm": "saas_vp_warm_4touch",
            "engaged": "saas_vp_engaged_3touch"
        },
        "Director": {
            "cold": "saas_director_cold_7touch",
            "warm": "saas_director_warm_5touch",
            "engaged": "saas_director_engaged_3touch"
        }
    },
    "Enterprise": {
        "C-Level": {
            "cold": "enterprise_c_level_cold_4touch",
            "warm": "enterprise_c_level_warm_3touch",
            "engaged": "enterprise_c_level_engaged_2touch"
        },
        "VP": {
            "cold": "enterprise_vp_cold_5touch",
            "warm": "enterprise_vp_warm_4touch",
            "engaged": "enterprise_vp_engaged_3touch"
        },
        "Director": {
            "cold": "enterprise_director_cold_6touch",
            "warm": "enterprise_director_warm_4touch",
            "engaged": "enterprise_director_engaged_3touch"
        }
    },
    "Technology": {
        "C-Level": {
            "cold": "tech_c_level_cold_5touch",
            "warm": "tech_c_level_warm_3touch",
            "engaged": "tech_c_level_engaged_2touch"
        },
        "VP": {
            "cold": "tech_vp_cold_6touch",
            "warm": "tech_vp_warm_4touch",
            "engaged": "tech_vp_engaged_3touch"
        },
        "Director": {
            "cold": "tech_director_cold_6touch",
            "warm": "tech_director_warm_4touch",
            "engaged": "tech_director_engaged_3touch"
        }
    }
}


class SequenceSelector:
    """
    Intelligent sequence selector based on lead attributes and historical performance.
    
    Analyzes lead characteristics and recommends optimal email sequences.
    """
    
    def __init__(self, db):
        """
        Initialize the sequence selector.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.campaigns_col = db.campaigns
        self.sends_col = db.campaign_sends
        self.recipients_col = db.campaign_recipients
        self.leads_col = db.leads
        self.sequences_col = db.campaign_sequences if hasattr(db, 'campaign_sequences') else None
    
    def select_optimal_sequence(
        self,
        lead: Dict,
        optimization_metric: str = "reply_rate"
    ) -> str:
        """
        Select the optimal sequence for a lead based on their attributes.
        
        Args:
            lead: Lead dictionary with attributes:
                {
                    "industry": "SaaS",
                    "seniority": "VP",
                    "company_size": "mid",
                    "engagement_level": "cold"  # cold | warm | engaged
                }
            optimization_metric: Metric to optimize for (default: "reply_rate")
                Options: "reply_rate", "open_rate", "meeting_rate", "engagement_score"
        
        Returns:
            Sequence ID string (e.g., "saas_vp_cold_6touch")
        """
        try:
            # Get recommendations
            recommendations = self.get_sequence_recommendations(
                lead=lead,
                metric=optimization_metric,
                limit=1
            )
            
            if recommendations:
                best = recommendations[0]
                logger.info(
                    f"Selected sequence '{best['sequence_name']}' for lead "
                    f"(confidence: {best['confidence']:.1%})"
                )
                return best["sequence_id"]
            
            # Fallback to default sequence
            default_seq = self._get_default_sequence(lead)
            logger.info(f"Using default sequence: {default_seq}")
            return default_seq
        
        except Exception as e:
            logger.error(f"Error selecting sequence: {e}")
            # Ultimate fallback
            return "default_cold_5touch"
    
    def get_sequence_recommendations(
        self,
        lead: Dict,
        metric: str = "reply_rate",
        limit: int = 3,
        min_campaigns: int = 5
    ) -> List[Dict]:
        """
        Get top sequence recommendations for a lead with confidence scores.
        
        Args:
            lead: Lead attributes dictionary
            metric: Optimization metric (default: "reply_rate")
            limit: Number of recommendations to return (default: 3)
            min_campaigns: Minimum campaigns required for data-driven recommendation
        
        Returns:
            List of sequence recommendations:
            [
                {
                    "sequence_id": "saas_vp_cold_6touch",
                    "sequence_name": "SaaS VP Cold Outreach - 6 Touch",
                    "sequence_length": 6,
                    "confidence": 0.85,
                    "expected_reply_rate": 0.12,
                    "expected_open_rate": 0.45,
                    "sample_size": 150,
                    "reason": "Best performing for SaaS VPs (150 campaigns, 12% reply rate)"
                },
                ...
            ]
        """
        try:
            industry = lead.get("industry", "").strip()
            seniority = lead.get("seniority", "").strip()
            company_size = lead.get("company_size", "").strip()
            engagement_level = lead.get("engagement_level", "cold").strip()
            
            # Get all campaigns and analyze sequence performance
            sequence_performance = self._analyze_sequence_performance(
                industry=industry,
                seniority=seniority,
                company_size=company_size,
                metric=metric
            )
            
            if not sequence_performance:
                # No historical data, use defaults
                return self._get_default_recommendations(lead, limit)
            
            # Filter sequences with sufficient data
            viable_sequences = [
                seq for seq in sequence_performance
                if seq.get("sample_size", 0) >= min_campaigns
            ]
            
            if not viable_sequences:
                # Insufficient data, use defaults
                return self._get_default_recommendations(lead, limit)
            
            # Sort by performance metric
            viable_sequences.sort(
                key=lambda x: x.get(metric, 0),
                reverse=True
            )
            
            # Calculate confidence based on sample size and performance consistency
            for seq in viable_sequences:
                sample_size = seq.get("sample_size", 0)
                
                # Confidence increases with sample size
                if sample_size >= 50:
                    confidence = 0.95
                elif sample_size >= 20:
                    confidence = 0.85
                elif sample_size >= 10:
                    confidence = 0.75
                else:
                    confidence = 0.60
                
                seq["confidence"] = confidence
                
                # Build reason string
                seq["reason"] = (
                    f"Best performing for {industry or 'this'} "
                    f"{seniority or 'leads'} "
                    f"({sample_size} campaigns, "
                    f"{seq.get(metric, 0):.1%} {metric.replace('_', ' ')})"
                )
            
            return viable_sequences[:limit]
        
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}")
            return self._get_default_recommendations(lead, limit)
    
    def _analyze_sequence_performance(
        self,
        industry: Optional[str] = None,
        seniority: Optional[str] = None,
        company_size: Optional[str] = None,
        metric: str = "reply_rate"
    ) -> List[Dict]:
        """
        Analyze sequence performance for a specific segment.
        
        Args:
            industry: Industry filter
            seniority: Seniority filter
            company_size: Company size filter
            metric: Performance metric to calculate
        
        Returns:
            List of sequences with performance metrics
        """
        try:
            # Build lead filter
            lead_filter = {}
            if industry:
                lead_filter["industry"] = industry
            if seniority:
                lead_filter["seniority"] = seniority
            if company_size:
                lead_filter["company_size"] = company_size
            
            # Get matching leads
            matching_leads = list(self.leads_col.find(lead_filter, {"_id": 1}))
            lead_ids = [str(l["_id"]) for l in matching_leads]
            
            if not lead_ids:
                logger.info("No matching leads found for segment")
                return []
            
            # Get recipients for these leads
            matching_recipients = list(self.recipients_col.find(
                {"lead_id": {"$in": lead_ids}},
                {"_id": 1, "campaign_id": 1}
            ))
            
            if not matching_recipients:
                logger.info("No recipients found for matching leads")
                return []
            
            # Group by campaign and get sequence info
            campaigns_map = defaultdict(list)
            for recipient in matching_recipients:
                campaign_id = recipient.get("campaign_id")
                if campaign_id:
                    campaigns_map[campaign_id].append(str(recipient["_id"]))
            
            # Analyze each campaign's sequence performance
            sequence_stats = defaultdict(lambda: {
                "campaigns": 0,
                "total_sends": 0,
                "opens": 0,
                "clicks": 0,
                "replies": 0
            })
            
            for campaign_id, recipient_ids in campaigns_map.items():
                # Get campaign to identify sequence
                campaign = self.campaigns_col.find_one({"_id": ObjectId(campaign_id)})
                if not campaign:
                    continue
                
                # Generate sequence identifier from campaign
                sequence_id = self._identify_sequence(campaign)
                sequence_name = campaign.get("name", sequence_id)
                sequence_length = len(campaign.get("sequence_steps", []))
                
                # Get sends for these recipients
                sends = list(self.sends_col.find({
                    "campaign_id": campaign_id,
                    "recipient_id": {"$in": recipient_ids}
                }))
                
                if not sends:
                    continue
                
                # Update stats
                stats = sequence_stats[sequence_id]
                stats["campaigns"] += 1
                stats["total_sends"] += len(sends)
                stats["sequence_name"] = sequence_name
                stats["sequence_length"] = sequence_length
                
                for send in sends:
                    if send.get("opened_at"):
                        stats["opens"] += 1
                    if send.get("clicked_at"):
                        stats["clicks"] += 1
                    if send.get("replied_at"):
                        stats["replies"] += 1
            
            # Calculate rates
            results = []
            for sequence_id, stats in sequence_stats.items():
                total = stats["total_sends"]
                if total > 0:
                    results.append({
                        "sequence_id": sequence_id,
                        "sequence_name": stats["sequence_name"],
                        "sequence_length": stats["sequence_length"],
                        "sample_size": stats["campaigns"],
                        "total_sends": total,
                        "open_rate": stats["opens"] / total,
                        "click_rate": stats["clicks"] / total,
                        "reply_rate": stats["replies"] / total
                    })
            
            return results
        
        except Exception as e:
            logger.error(f"Error analyzing sequence performance: {e}")
            return []
    
    def _identify_sequence(self, campaign: Dict) -> str:
        """
        Identify sequence type from campaign configuration.
        
        Args:
            campaign: Campaign dictionary
        
        Returns:
            Sequence identifier string
        """
        # Check if campaign has explicit sequence_id
        if "sequence_id" in campaign:
            return campaign["sequence_id"]
        
        # Generate from campaign metadata
        steps = campaign.get("sequence_steps", [])
        length = len(steps)
        
        campaign_type = campaign.get("campaign_type", "cold")
        name = campaign.get("name", "").lower()
        
        # Try to parse from name
        if "saas" in name and "vp" in name:
            return f"saas_vp_{campaign_type}_{length}touch"
        elif "enterprise" in name and "director" in name:
            return f"enterprise_director_{campaign_type}_{length}touch"
        elif "tech" in name and "c-level" in name:
            return f"tech_c_level_{campaign_type}_{length}touch"
        
        # Generic fallback
        return f"{campaign_type}_{length}touch"
    
    def _get_default_sequence(self, lead: Dict) -> str:
        """
        Get default sequence based on lead attributes.
        
        Args:
            lead: Lead attributes
        
        Returns:
            Default sequence identifier
        """
        industry = lead.get("industry", "SaaS")
        seniority = lead.get("seniority", "VP")
        engagement_level = lead.get("engagement_level", "cold")
        
        # Normalize seniority
        if "c-" in seniority.lower() or "ceo" in seniority.lower() or "cto" in seniority.lower():
            seniority = "C-Level"
        elif "vp" in seniority.lower() or "vice president" in seniority.lower():
            seniority = "VP"
        elif "director" in seniority.lower():
            seniority = "Director"
        else:
            seniority = "Director"  # Default
        
        # Look up in default sequences
        if industry in DEFAULT_SEQUENCES:
            if seniority in DEFAULT_SEQUENCES[industry]:
                if engagement_level in DEFAULT_SEQUENCES[industry][seniority]:
                    return DEFAULT_SEQUENCES[industry][seniority][engagement_level]
        
        # Ultimate fallback
        return "default_cold_5touch"
    
    def _get_default_recommendations(
        self,
        lead: Dict,
        limit: int = 3
    ) -> List[Dict]:
        """
        Get default sequence recommendations when no historical data available.
        
        Args:
            lead: Lead attributes
            limit: Number of recommendations
        
        Returns:
            List of default recommendations
        """
        industry = lead.get("industry", "SaaS")
        seniority = lead.get("seniority", "VP")
        engagement_level = lead.get("engagement_level", "cold")
        
        # Normalize seniority
        if "c-" in seniority.lower() or "ceo" in seniority.lower():
            seniority = "C-Level"
        elif "vp" in seniority.lower():
            seniority = "VP"
        elif "director" in seniority.lower():
            seniority = "Director"
        else:
            seniority = "Director"
        
        recommendations = []
        
        # Primary recommendation: exact match
        if (industry in DEFAULT_SEQUENCES and 
            seniority in DEFAULT_SEQUENCES[industry] and
            engagement_level in DEFAULT_SEQUENCES[industry][seniority]):
            
            seq_id = DEFAULT_SEQUENCES[industry][seniority][engagement_level]
            recommendations.append({
                "sequence_id": seq_id,
                "sequence_name": f"{industry} {seniority} {engagement_level.title()} Outreach",
                "sequence_length": int(seq_id.split("touch")[0].split("_")[-1]) if "touch" in seq_id else 5,
                "confidence": 0.50,  # Lower confidence for default
                "expected_reply_rate": 0.08,  # Industry average
                "expected_open_rate": 0.35,
                "sample_size": 0,
                "reason": f"Default sequence for {industry} {seniority} (no historical data)"
            })
        
        # Add alternative engagement levels
        if len(recommendations) < limit:
            for alt_engagement in ["cold", "warm", "engaged"]:
                if alt_engagement != engagement_level:
                    if (industry in DEFAULT_SEQUENCES and 
                        seniority in DEFAULT_SEQUENCES[industry] and
                        alt_engagement in DEFAULT_SEQUENCES[industry][seniority]):
                        
                        seq_id = DEFAULT_SEQUENCES[industry][seniority][alt_engagement]
                        recommendations.append({
                            "sequence_id": seq_id,
                            "sequence_name": f"{industry} {seniority} {alt_engagement.title()} Outreach",
                            "sequence_length": int(seq_id.split("touch")[0].split("_")[-1]) if "touch" in seq_id else 5,
                            "confidence": 0.40,
                            "expected_reply_rate": 0.08,
                            "expected_open_rate": 0.35,
                            "sample_size": 0,
                            "reason": f"Alternative {alt_engagement} sequence for {industry} {seniority}"
                        })
                
                if len(recommendations) >= limit:
                    break
        
        # Fill remaining with generic sequences
        while len(recommendations) < limit:
            recommendations.append({
                "sequence_id": "default_cold_5touch",
                "sequence_name": "Generic Cold Outreach - 5 Touch",
                "sequence_length": 5,
                "confidence": 0.30,
                "expected_reply_rate": 0.05,
                "expected_open_rate": 0.30,
                "sample_size": 0,
                "reason": "Generic fallback sequence"
            })
        
        return recommendations[:limit]


# ============== EXAMPLE USAGE ==============

if __name__ == "__main__":
    from pymongo import MongoClient
    
    # Connect to database
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform
    
    selector = SequenceSelector(db)
    
    # Example: Select optimal sequence for a lead
    lead = {
        "industry": "SaaS",
        "seniority": "VP",
        "company_size": "mid",
        "engagement_level": "cold"
    }
    
    sequence_id = selector.select_optimal_sequence(lead)
    print(f"\nSelected sequence: {sequence_id}")
    
    # Example: Get top 3 recommendations
    recommendations = selector.get_sequence_recommendations(lead, limit=3)
    print(f"\nTop Sequence Recommendations:")
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec['sequence_name']}")
        print(f"   Sequence ID: {rec['sequence_id']}")
        print(f"   Length: {rec['sequence_length']} touches")
        print(f"   Confidence: {rec['confidence']:.1%}")
        print(f"   Expected reply rate: {rec['expected_reply_rate']:.1%}")
        print(f"   Reason: {rec['reason']}")
