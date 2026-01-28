"""
COMPETITOR TRACKER
==================

Competitive intelligence system for tracking competitor mentions in replies.

Features:
- Detect competitor mentions in reply text
- Log competitive intelligence data
- Track competitor frequency and context
- Generate competitive summary reports
- Integration with MongoDB for persistence

Competitor Categories:
- CRM: Salesforce, HubSpot, Pipedrive, etc.
- Marketing Automation: Marketo, Pardot, ActiveCampaign
- Sales Engagement: Outreach, SalesLoft, Apollo
- General: Any other mentioned competitors

Usage:
    tracker = CompetitorTracker()
    
    # Detect competitors
    competitors = tracker.detect_competitors(
        "We're currently using Salesforce and HubSpot."
    )
    # Returns: ["Salesforce", "HubSpot"]
    
    # Log competitive intel
    tracker.log_competitive_intel(
        lead_id="123",
        competitor="Salesforce",
        context="Using for CRM, satisfied"
    )
    
    # Get summary
    summary = tracker.get_competitor_summary()
"""

import os
import logging
import re
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta
from collections import Counter, defaultdict

try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None

logger = logging.getLogger(__name__)


class CompetitorTracker:
    """
    Track and analyze competitor mentions in campaign replies.
    Provides competitive intelligence for sales strategy.
    """
    
    # Known competitor database (can be expanded)
    KNOWN_COMPETITORS = {
        "crm": [
            "Salesforce", "HubSpot", "Pipedrive", "Zoho CRM", "Monday.com",
            "Freshsales", "Copper", "Insightly", "Nimble", "Bitrix24"
        ],
        "marketing_automation": [
            "Marketo", "Pardot", "ActiveCampaign", "Mailchimp", "Constant Contact",
            "SendGrid", "Drip", "ConvertKit", "GetResponse", "AWeber"
        ],
        "sales_engagement": [
            "Outreach", "SalesLoft", "Apollo", "Lemlist", "Woodpecker",
            "Reply.io", "Yesware", "Mixmax", "Groove", "Close"
        ],
        "general": [
            "Intercom", "Drift", "Zendesk", "ServiceNow", "Jira"
        ]
    }
    
    # Flatten for easy lookup
    ALL_COMPETITORS = []
    COMPETITOR_CATEGORY = {}
    for category, competitors in KNOWN_COMPETITORS.items():
        for comp in competitors:
            ALL_COMPETITORS.append(comp.lower())
            COMPETITOR_CATEGORY[comp.lower()] = category
    
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        database: str = "campaign_platform"
    ):
        """
        Initialize the competitor tracker.
        
        Args:
            mongo_uri: MongoDB connection URI
            database: Database name
        """
        self.mongo_uri = mongo_uri or os.getenv("MONGO_URI")
        self.database_name = database
        self.db = None
        self.collection = None
        
        if self.mongo_uri and MongoClient:
            try:
                self.client = MongoClient(self.mongo_uri)
                self.db = self.client[self.database_name]
                self.collection = self.db["competitive_intelligence"]
                logger.info("CompetitorTracker connected to MongoDB")
            except Exception as e:
                logger.warning(f"MongoDB connection failed: {e}")
        else:
            logger.warning("MongoDB not configured - using in-memory tracking only")
        
        # In-memory cache for this session
        self.session_mentions = []
    
    def detect_competitors(
        self,
        reply: str,
        custom_competitors: Optional[List[str]] = None
    ) -> List[str]:
        """
        Detect competitor mentions in reply text.
        
        Args:
            reply: The reply text to analyze
            custom_competitors: Additional competitors to check for
            
        Returns:
            List of detected competitor names
        """
        if not reply:
            return []
        
        reply_lower = reply.lower()
        detected = []
        
        # Check known competitors
        for competitor in self.ALL_COMPETITORS:
            # Use word boundary regex to avoid partial matches
            pattern = r'\b' + re.escape(competitor) + r'\b'
            if re.search(pattern, reply_lower):
                # Return original capitalization
                original_name = next(
                    (name for cat_comps in self.KNOWN_COMPETITORS.values() 
                     for name in cat_comps if name.lower() == competitor),
                    competitor.title()
                )
                if original_name not in detected:
                    detected.append(original_name)
        
        # Check custom competitors
        if custom_competitors:
            for competitor in custom_competitors:
                pattern = r'\b' + re.escape(competitor.lower()) + r'\b'
                if re.search(pattern, reply_lower) and competitor not in detected:
                    detected.append(competitor)
        
        logger.info(f"Detected {len(detected)} competitor(s): {', '.join(detected)}")
        
        return detected
    
    def log_competitive_intel(
        self,
        lead_id: str,
        competitor: str,
        context: str,
        reply_text: Optional[str] = None,
        sentiment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log competitive intelligence data.
        
        Args:
            lead_id: Lead identifier
            competitor: Competitor name
            context: Context of mention (e.g., "currently using", "evaluating")
            reply_text: Full reply text
            sentiment: Sentiment towards competitor (positive, neutral, negative)
            metadata: Additional metadata (lead company, industry, etc.)
            
        Returns:
            True if logged successfully
        """
        intel = {
            "lead_id": lead_id,
            "competitor": competitor,
            "competitor_lower": competitor.lower(),
            "category": self.COMPETITOR_CATEGORY.get(competitor.lower(), "unknown"),
            "context": context,
            "reply_text": reply_text[:500] if reply_text else None,  # First 500 chars
            "sentiment": sentiment,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow(),
            "created_at": datetime.utcnow()
        }
        
        # Store in session
        self.session_mentions.append(intel)
        
        # Store in MongoDB if available
        if self.collection is not None:
            try:
                self.collection.insert_one(intel)
                logger.info(f"Logged competitive intel: {competitor} for lead {lead_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to log competitive intel: {e}")
                return False
        
        return True  # Still return True if in-memory storage succeeded
    
    def get_competitor_mentions(
        self,
        competitor: Optional[str] = None,
        days: int = 30,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get competitor mentions from the database.
        
        Args:
            competitor: Specific competitor to filter by
            days: Number of days to look back
            category: Competitor category to filter by
            
        Returns:
            List of competitive intel records
        """
        mentions = []
        
        # Query from MongoDB if available
        if self.collection is not None:
            try:
                query = {
                    "timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}
                }
                
                if competitor:
                    query["competitor_lower"] = competitor.lower()
                
                if category:
                    query["category"] = category
                
                cursor = self.collection.find(query).sort("timestamp", -1)
                mentions = list(cursor)
                
            except Exception as e:
                logger.error(f"Failed to query competitive intel: {e}")
        
        # Add session mentions
        cutoff = datetime.utcnow() - timedelta(days=days)
        session_filtered = [
            m for m in self.session_mentions
            if m["timestamp"] >= cutoff
            and (not competitor or m["competitor_lower"] == competitor.lower())
            and (not category or m["category"] == category)
        ]
        
        mentions.extend(session_filtered)
        
        return mentions
    
    def get_competitor_summary(
        self,
        days: int = 30,
        top_n: int = 10
    ) -> Dict[str, Any]:
        """
        Get aggregated competitive intelligence summary.
        
        Args:
            days: Number of days to analyze
            top_n: Number of top competitors to include
            
        Returns:
            Dict with competitive intelligence summary
        """
        mentions = self.get_competitor_mentions(days=days)
        
        if not mentions:
            return {
                "total_mentions": 0,
                "period_days": days,
                "top_competitors": [],
                "by_category": {},
                "sentiment_breakdown": {}
            }
        
        # Count competitor mentions
        competitor_counts = Counter([m["competitor"] for m in mentions])
        
        # Count by category
        category_counts = Counter([m["category"] for m in mentions])
        
        # Sentiment breakdown
        sentiment_counts = Counter([m.get("sentiment") for m in mentions if m.get("sentiment")])
        
        # Context analysis
        context_patterns = defaultdict(list)
        for m in mentions:
            context_patterns[m["competitor"]].append(m.get("context", ""))
        
        # Top competitors with details
        top_competitors = []
        for competitor, count in competitor_counts.most_common(top_n):
            competitor_mentions = [m for m in mentions if m["competitor"] == competitor]
            
            sentiments = [m.get("sentiment") for m in competitor_mentions if m.get("sentiment")]
            sentiment_breakdown = Counter(sentiments)
            
            top_competitors.append({
                "competitor": competitor,
                "mentions": count,
                "category": self.COMPETITOR_CATEGORY.get(competitor.lower(), "unknown"),
                "sentiment_breakdown": dict(sentiment_breakdown),
                "recent_contexts": [m.get("context", "") for m in competitor_mentions[:5]],
                "first_seen": min(m["timestamp"] for m in competitor_mentions),
                "last_seen": max(m["timestamp"] for m in competitor_mentions)
            })
        
        return {
            "total_mentions": len(mentions),
            "unique_competitors": len(competitor_counts),
            "period_days": days,
            "top_competitors": top_competitors,
            "by_category": dict(category_counts),
            "sentiment_breakdown": dict(sentiment_counts),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def get_competitor_comparison_data(
        self,
        our_product: str,
        competitor: str,
        days: int = 90
    ) -> Dict[str, Any]:
        """
        Get data for creating competitor comparison materials.
        
        Args:
            our_product: Our product name
            competitor: Competitor to compare against
            days: Days of data to analyze
            
        Returns:
            Dict with comparison insights
        """
        mentions = self.get_competitor_mentions(competitor=competitor, days=days)
        
        # Analyze contexts to find pain points/gaps
        pain_points = []
        positive_aspects = []
        
        for mention in mentions:
            context = mention.get("context", "").lower()
            
            # Look for pain point indicators
            pain_indicators = ["but", "however", "issue", "problem", "lacking", "missing", "wish"]
            if any(indicator in context for indicator in pain_indicators):
                pain_points.append(mention.get("context"))
            
            # Look for positive aspects
            positive_indicators = ["love", "great", "good", "works well", "happy"]
            if any(indicator in context for indicator in positive_indicators):
                positive_aspects.append(mention.get("context"))
        
        return {
            "competitor": competitor,
            "our_product": our_product,
            "total_mentions": len(mentions),
            "analysis_period_days": days,
            "identified_pain_points": pain_points[:10],  # Top 10
            "identified_strengths": positive_aspects[:10],
            "sentiment_breakdown": Counter([
                m.get("sentiment") for m in mentions if m.get("sentiment")
            ]),
            "competitive_angles": self._generate_competitive_angles(
                competitor, pain_points
            ),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def _generate_competitive_angles(
        self,
        competitor: str,
        pain_points: List[str]
    ) -> List[str]:
        """Generate competitive positioning angles based on pain points."""
        
        angles = []
        
        # Generic angles
        generic_angles = [
            f"Unlike {competitor}, we offer...",
            f"While {competitor} focuses on X, we excel at Y...",
            f"Customers switching from {competitor} see improvements in..."
        ]
        
        # Pain point-based angles
        if "price" in " ".join(pain_points).lower() or "cost" in " ".join(pain_points).lower():
            angles.append(f"More cost-effective than {competitor} with transparent pricing")
        
        if "support" in " ".join(pain_points).lower() or "help" in " ".join(pain_points).lower():
            angles.append(f"Superior customer support compared to {competitor}")
        
        if "complex" in " ".join(pain_points).lower() or "difficult" in " ".join(pain_points).lower():
            angles.append(f"Easier to use and implement than {competitor}")
        
        angles.extend(generic_angles)
        
        return angles[:5]  # Return top 5
    
    def export_competitive_report(
        self,
        days: int = 30,
        format: str = "dict"
    ) -> Dict[str, Any]:
        """
        Export comprehensive competitive intelligence report.
        
        Args:
            days: Days of data to include
            format: Output format (dict, json)
            
        Returns:
            Comprehensive competitive report
        """
        summary = self.get_competitor_summary(days=days)
        
        # Get detailed data for top competitors
        top_competitor_details = []
        for comp_data in summary["top_competitors"][:5]:  # Top 5
            competitor = comp_data["competitor"]
            comparison = self.get_competitor_comparison_data(
                our_product="Our Product",
                competitor=competitor,
                days=days
            )
            top_competitor_details.append(comparison)
        
        report = {
            "report_title": f"Competitive Intelligence Report - Last {days} Days",
            "generated_at": datetime.utcnow().isoformat(),
            "summary": summary,
            "top_competitor_analysis": top_competitor_details,
            "recommendations": self._generate_recommendations(summary)
        }
        
        if format == "json":
            import json
            return json.dumps(report, indent=2, default=str)
        
        return report
    
    def _generate_recommendations(self, summary: Dict[str, Any]) -> List[str]:
        """Generate strategic recommendations based on competitive data."""
        
        recommendations = []
        
        top_comps = summary.get("top_competitors", [])
        
        if not top_comps:
            return ["Insufficient data for recommendations"]
        
        # Most mentioned competitor
        if top_comps:
            top_comp = top_comps[0]
            recommendations.append(
                f"Focus competitive positioning against {top_comp['competitor']} "
                f"({top_comp['mentions']} mentions)"
            )
        
        # Category concentration
        by_category = summary.get("by_category", {})
        if by_category:
            dominant_category = max(by_category.items(), key=lambda x: x[1])
            recommendations.append(
                f"High concentration in {dominant_category[0]} category - "
                "consider targeted differentiation messaging"
            )
        
        # Sentiment analysis
        sentiment = summary.get("sentiment_breakdown", {})
        if sentiment.get("positive", 0) > sentiment.get("negative", 0):
            recommendations.append(
                "Competitors have positive sentiment - emphasize unique value props and differentiators"
            )
        else:
            recommendations.append(
                "Competitors have negative sentiment - leverage pain points in messaging"
            )
        
        return recommendations


# Convenience functions
def detect_competitors_in_reply(reply: str) -> List[str]:
    """Quick competitor detection."""
    tracker = CompetitorTracker()
    return tracker.detect_competitors(reply)


def log_competitor_mention(lead_id: str, competitor: str, context: str) -> bool:
    """Quick competitive intel logging."""
    tracker = CompetitorTracker()
    return tracker.log_competitive_intel(lead_id, competitor, context)


if __name__ == "__main__":
    # Test the competitor tracker
    logging.basicConfig(level=logging.INFO)
    
    tracker = CompetitorTracker()
    
    print("\n=== Competitor Tracker Test ===\n")
    
    # Test detection
    test_replies = [
        "We're currently using Salesforce and it works well for us.",
        "We evaluated HubSpot and Pipedrive but went with Zoho CRM.",
        "Not interested, we're happy with Outreach for sales engagement."
    ]
    
    print("Testing competitor detection:\n")
    for i, reply in enumerate(test_replies):
        print(f"Reply {i+1}: {reply}")
        competitors = tracker.detect_competitors(reply)
        print(f"Detected: {', '.join(competitors) if competitors else 'None'}\n")
    
    # Test logging
    print("\nTesting competitive intel logging:\n")
    tracker.log_competitive_intel(
        lead_id="test_lead_1",
        competitor="Salesforce",
        context="Currently using, satisfied",
        sentiment="positive"
    )
    
    tracker.log_competitive_intel(
        lead_id="test_lead_2",
        competitor="HubSpot",
        context="Price too high",
        sentiment="negative"
    )
    
    # Test summary
    print("\nGenerating competitive summary:\n")
    summary = tracker.get_competitor_summary(days=30)
    print(f"Total mentions: {summary['total_mentions']}")
    print(f"Unique competitors: {summary['unique_competitors']}")
    
    if summary['top_competitors']:
        print("\nTop Competitors:")
        for comp in summary['top_competitors'][:3]:
            print(f"  - {comp['competitor']}: {comp['mentions']} mentions")
