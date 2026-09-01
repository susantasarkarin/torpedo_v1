"""
Campaign Optimizer Service.

Analyzes campaign performance and provides optimization recommendations.
"""

import json
import logging
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

class PerformanceMetrics(BaseModel):
    """Campaign performance metrics."""
    total_sent: int = 0
    total_delivered: int = 0
    total_opened: int = 0
    total_clicked: int = 0
    total_replied: int = 0
    total_positive_replies: int = 0
    total_meetings: int = 0
    total_bounces: int = 0
    total_complaints: int = 0
    
    @property
    def delivery_rate(self) -> float:
        return (self.total_delivered / self.total_sent * 100) if self.total_sent else 0
    
    @property
    def open_rate(self) -> float:
        return (self.total_opened / self.total_delivered * 100) if self.total_delivered else 0
    
    @property
    def click_rate(self) -> float:
        return (self.total_clicked / self.total_delivered * 100) if self.total_delivered else 0
    
    @property
    def reply_rate(self) -> float:
        return (self.total_replied / self.total_delivered * 100) if self.total_delivered else 0
    
    @property
    def positive_reply_rate(self) -> float:
        return (self.total_positive_replies / self.total_delivered * 100) if self.total_delivered else 0
    
    @property
    def meeting_rate(self) -> float:
        return (self.total_meetings / self.total_delivered * 100) if self.total_delivered else 0
    
    @property
    def bounce_rate(self) -> float:
        return (self.total_bounces / self.total_sent * 100) if self.total_sent else 0


class PerformanceInsights(BaseModel):
    """Insights derived from performance analysis."""
    winning_subject_patterns: list[str] = Field(default_factory=list)
    underperforming_elements: list[str] = Field(default_factory=list)
    best_send_windows: list[str] = Field(default_factory=list)
    top_performing_senders: list[str] = Field(default_factory=list)
    best_industries: list[str] = Field(default_factory=list)
    worst_industries: list[str] = Field(default_factory=list)


class OptimizationRecommendations(BaseModel):
    """Actionable optimization recommendations."""
    subject_strategy: str = ""
    tone_adjustment: str = ""
    cta_modification: str = ""
    send_time_optimization: str = ""
    sender_reallocation: str = ""
    targeting_refinement: str = ""


class ActionItem(BaseModel):
    """Specific action item from optimization."""
    priority: str = Field(..., pattern="^(high|medium|low)$")
    action: str
    expected_impact: str


class OptimizationReport(BaseModel):
    """Complete optimization report."""
    report_date: datetime = Field(default_factory=datetime.utcnow)
    period_start: datetime
    period_end: datetime
    performance_summary: dict
    insights: PerformanceInsights
    recommendations: OptimizationRecommendations
    action_items: list[ActionItem] = Field(default_factory=list)
    health_alerts: Optional[list[str]] = None


class CampaignData(BaseModel):
    """Raw campaign data for analysis."""
    emails: list[dict]  # List of email records with metrics
    subject_performance: dict[str, dict] = Field(default_factory=dict)  # subject -> metrics
    sender_performance: dict[str, dict] = Field(default_factory=dict)  # sender_id -> metrics
    time_performance: dict[str, dict] = Field(default_factory=dict)  # hour -> metrics
    industry_performance: dict[str, dict] = Field(default_factory=dict)  # industry -> metrics


# =============================================================================
# Service Implementation
# =============================================================================

class CampaignOptimizerService:
    """
    Service for analyzing and optimizing campaign performance.
    
    This service:
    1. Aggregates campaign metrics
    2. Identifies patterns and trends
    3. Generates AI-powered recommendations
    4. Creates actionable optimization plans
    """
    
    def __init__(self, ai_client: Any, db: Any = None):
        """
        Initialize the optimizer.
        
        Args:
            ai_client: AI client for analysis
            db: MongoDB database instance
        """
        self.ai_client = ai_client
        self.db = db
    
    async def generate_weekly_report(
        self,
        campaign_data: Optional[CampaignData] = None,
        period_days: int = 7
    ) -> OptimizationReport:
        """
        Generate a weekly optimization report.
        
        Args:
            campaign_data: Raw campaign performance data (loads from DB if not provided)
            period_days: Number of days to analyze
            
        Returns:
            OptimizationReport with insights and recommendations
        """
        from .master_prompts import WEEKLY_OPTIMIZATION_PROMPT
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=period_days)
        
        # Load data from DB if not provided
        if campaign_data is None and self.db:
            campaign_data = await self._load_campaign_data(period_start, period_end)
        
        if campaign_data is None:
            return self._generate_empty_report(period_start, period_end)
        
        # Calculate aggregate metrics
        metrics = self._calculate_metrics(campaign_data)
        
        # Build context for AI analysis
        context = self._build_analysis_context(campaign_data, metrics)
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="claude-opus-4-8",
                messages=[
                    {"role": "user", "content": f"{WEEKLY_OPTIMIZATION_PROMPT}\n\n---\n\nPERFORMANCE DATA:\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1500
            )
            
            result = json.loads(response.choices[0].message.content)
            
            return OptimizationReport(
                period_start=period_start,
                period_end=period_end,
                performance_summary=result.get("performance_summary", {}),
                insights=PerformanceInsights(**result.get("insights", {})),
                recommendations=OptimizationRecommendations(**result.get("recommendations", {})),
                action_items=[ActionItem(**item) for item in result.get("action_items", [])],
                health_alerts=result.get("health_alerts")
            )
            
        except Exception as e:
            logger.error(f"Weekly optimization analysis failed: {e}")
            # Return basic report without AI insights
            return self._generate_basic_report(campaign_data, metrics, period_start, period_end)
    
    async def _load_campaign_data(
        self,
        period_start: datetime,
        period_end: datetime
    ) -> Optional[CampaignData]:
        """Load campaign data from database."""
        if not self.db:
            return None
        
        try:
            emails_collection = self.db["outreach_emails"]
            events_collection = self.db["outreach_events"]
            
            # Load emails from period
            emails = list(emails_collection.find({
                "sent_at": {"$gte": period_start, "$lte": period_end}
            }))
            
            if not emails:
                return None
            
            # Enrich with events
            for email in emails:
                email_id = str(email["_id"])
                events = list(events_collection.find({"email_id": email_id}))
                
                email["opened"] = any(e["event_type"] == "opened" for e in events)
                email["clicked"] = any(e["event_type"] == "clicked" for e in events)
                email["replied"] = any(e["event_type"] == "replied" for e in events)
                email["bounced"] = any(e["event_type"] == "bounced" for e in events)
                email["delivered"] = not email["bounced"]
            
            # Aggregate by subject, sender, time, industry
            subject_perf = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0})
            sender_perf = defaultdict(lambda: {"sent": 0, "bounces": 0, "health_score": 100})
            time_perf = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0})
            industry_perf = defaultdict(lambda: {"sent": 0, "replied": 0, "meetings": 0})
            
            for email in emails:
                subject = email.get("subject", "")
                sender = email.get("sender_id", "unknown")
                hour = email.get("sent_at", datetime.utcnow()).strftime("%H:00")
                industry = email.get("industry", "Unknown")
                
                subject_perf[subject]["sent"] += 1
                if email.get("opened"):
                    subject_perf[subject]["opened"] += 1
                if email.get("replied"):
                    subject_perf[subject]["replied"] += 1
                
                sender_perf[sender]["sent"] += 1
                if email.get("bounced"):
                    sender_perf[sender]["bounces"] += 1
                
                time_perf[hour]["sent"] += 1
                if email.get("opened"):
                    time_perf[hour]["opened"] += 1
                if email.get("replied"):
                    time_perf[hour]["replied"] += 1
                
                industry_perf[industry]["sent"] += 1
                if email.get("replied"):
                    industry_perf[industry]["replied"] += 1
            
            # Calculate rates
            for subject, data in subject_perf.items():
                if data["sent"] > 0:
                    data["open_rate"] = data["opened"] / data["sent"] * 100
                    data["reply_rate"] = data["replied"] / data["sent"] * 100
            
            for hour, data in time_perf.items():
                if data["sent"] > 0:
                    data["open_rate"] = data["opened"] / data["sent"] * 100
                    data["reply_rate"] = data["replied"] / data["sent"] * 100
            
            for industry, data in industry_perf.items():
                if data["sent"] > 0:
                    data["reply_rate"] = data["replied"] / data["sent"] * 100
            
            return CampaignData(
                emails=emails,
                subject_performance=dict(subject_perf),
                sender_performance=dict(sender_perf),
                time_performance=dict(time_perf),
                industry_performance=dict(industry_perf)
            )
            
        except Exception as e:
            logger.error(f"Failed to load campaign data: {e}")
            return None
    
    def _calculate_metrics(self, data: CampaignData) -> PerformanceMetrics:
        """Calculate aggregate performance metrics."""
        metrics = PerformanceMetrics()
        
        for email in data.emails:
            metrics.total_sent += 1
            if email.get("delivered"):
                metrics.total_delivered += 1
            if email.get("opened"):
                metrics.total_opened += 1
            if email.get("clicked"):
                metrics.total_clicked += 1
            if email.get("replied"):
                metrics.total_replied += 1
            if email.get("positive_reply"):
                metrics.total_positive_replies += 1
            if email.get("meeting_booked"):
                metrics.total_meetings += 1
            if email.get("bounced"):
                metrics.total_bounces += 1
            if email.get("complained"):
                metrics.total_complaints += 1
        
        return metrics
    
    def _build_analysis_context(
        self,
        data: CampaignData,
        metrics: PerformanceMetrics
    ) -> str:
        """Build context string for AI analysis."""
        
        # Subject line performance
        subject_summary = []
        for subject, perf in sorted(
            data.subject_performance.items(),
            key=lambda x: x[1].get("open_rate", 0),
            reverse=True
        )[:10]:
            subject_summary.append(
                f"- \"{subject[:50]}...\": Opens={perf.get('open_rate', 0):.1f}%, "
                f"Replies={perf.get('reply_rate', 0):.1f}%"
            )
        
        # Time performance
        time_summary = []
        for hour, perf in sorted(
            data.time_performance.items(),
            key=lambda x: x[1].get("open_rate", 0),
            reverse=True
        )[:5]:
            time_summary.append(
                f"- {hour}: Opens={perf.get('open_rate', 0):.1f}%, "
                f"Replies={perf.get('reply_rate', 0):.1f}%"
            )
        
        # Sender performance
        sender_summary = []
        for sender_id, perf in sorted(
            data.sender_performance.items(),
            key=lambda x: x[1].get("health_score", 0),
            reverse=True
        ):
            sender_summary.append(
                f"- {sender_id}: Health={perf.get('health_score', 0):.0f}, "
                f"Sent={perf.get('sent', 0)}, Bounces={perf.get('bounces', 0)}"
            )
        
        # Industry performance
        industry_summary = []
        for industry, perf in sorted(
            data.industry_performance.items(),
            key=lambda x: x[1].get("reply_rate", 0),
            reverse=True
        ):
            industry_summary.append(
                f"- {industry}: Replies={perf.get('reply_rate', 0):.1f}%, "
                f"Meetings={perf.get('meeting_rate', 0):.1f}%"
            )
        
        return f"""
AGGREGATE METRICS:
- Total Sent: {metrics.total_sent}
- Delivery Rate: {metrics.delivery_rate:.1f}%
- Open Rate: {metrics.open_rate:.1f}%
- Reply Rate: {metrics.reply_rate:.1f}%
- Positive Reply Rate: {metrics.positive_reply_rate:.1f}%
- Meeting Rate: {metrics.meeting_rate:.1f}%
- Bounce Rate: {metrics.bounce_rate:.1f}%

SUBJECT LINE PERFORMANCE (Top 10):
{chr(10).join(subject_summary) if subject_summary else "No data"}

SEND TIME PERFORMANCE (Top 5 hours):
{chr(10).join(time_summary) if time_summary else "No data"}

SENDER PERFORMANCE:
{chr(10).join(sender_summary) if sender_summary else "No data"}

INDUSTRY PERFORMANCE:
{chr(10).join(industry_summary) if industry_summary else "No data"}
"""
    
    def _generate_basic_report(
        self,
        data: CampaignData,
        metrics: PerformanceMetrics,
        period_start: datetime,
        period_end: datetime
    ) -> OptimizationReport:
        """Generate basic report without AI."""
        
        # Simple rule-based insights
        health_alerts = []
        if metrics.bounce_rate > 5:
            health_alerts.append(f"HIGH BOUNCE RATE: {metrics.bounce_rate:.1f}%")
        if metrics.open_rate < 20:
            health_alerts.append(f"LOW OPEN RATE: {metrics.open_rate:.1f}%")
        
        return OptimizationReport(
            period_start=period_start,
            period_end=period_end,
            performance_summary={
                "total_sent": metrics.total_sent,
                "open_rate": metrics.open_rate,
                "reply_rate": metrics.reply_rate,
                "meeting_rate": metrics.meeting_rate
            },
            insights=PerformanceInsights(),
            recommendations=OptimizationRecommendations(
                subject_strategy="Review subject lines with highest open rates",
                tone_adjustment="Analyze top-performing emails for tone patterns"
            ),
            action_items=[
                ActionItem(
                    priority="high",
                    action="Review and address any health alerts",
                    expected_impact="Maintain sender reputation"
                )
            ],
            health_alerts=health_alerts if health_alerts else None
        )
    
    def _generate_empty_report(
        self,
        period_start: datetime,
        period_end: datetime
    ) -> OptimizationReport:
        """Generate empty report when no data is available."""
        return OptimizationReport(
            period_start=period_start,
            period_end=period_end,
            performance_summary={
                "total_sent": 0,
                "open_rate": 0,
                "reply_rate": 0,
                "meeting_rate": 0
            },
            insights=PerformanceInsights(),
            recommendations=OptimizationRecommendations(
                subject_strategy="No data available - start sending emails to gather insights"
            ),
            action_items=[],
            health_alerts=["No campaign data available for the selected period"]
        )
    
    async def analyze_ab_test(
        self,
        variant_a_data: dict,
        variant_b_data: dict
    ) -> dict:
        """
        Analyze A/B test results.
        
        Args:
            variant_a_data: Metrics for variant A
            variant_b_data: Metrics for variant B
            
        Returns:
            Analysis with winner and confidence
        """
        # Calculate statistical significance (simplified)
        a_rate = variant_a_data.get("conversion_rate", 0)
        b_rate = variant_b_data.get("conversion_rate", 0)
        a_n = variant_a_data.get("sample_size", 0)
        b_n = variant_b_data.get("sample_size", 0)
        
        if a_n < 100 or b_n < 100:
            return {
                "winner": None,
                "confidence": 0,
                "recommendation": "Need more data (minimum 100 samples per variant)"
            }
        
        # Simple comparison
        if abs(a_rate - b_rate) < 0.5:
            return {
                "winner": None,
                "confidence": 0,
                "recommendation": "No significant difference between variants"
            }
        
        winner = "A" if a_rate > b_rate else "B"
        lift = abs(a_rate - b_rate) / max(a_rate, b_rate) * 100
        
        return {
            "winner": winner,
            "winner_rate": max(a_rate, b_rate),
            "loser_rate": min(a_rate, b_rate),
            "lift": f"{lift:.1f}%",
            "confidence": 0.95 if lift > 10 else 0.80,
            "recommendation": f"Variant {winner} shows {lift:.1f}% improvement. Consider implementing."
        }
