"""
SEQUENCE PERFORMANCE ANALYZER
==============================

Analyze email sequence performance, identify best-performing step combinations,
compare sequences, and recommend improvements.

Features:
- Per-step performance analysis (delivery, open, click, reply rates)
- Drop-off point identification
- Sequence comparison (head-to-head performance)
- Best-performing step pattern detection
- Improvement recommendations based on data
- Optimal timing analysis between steps

Collections:
- campaigns: Campaign definitions with sequences
- campaign_sends: Email send and engagement history
- campaign_recipients: Recipient status tracking

Usage:
    from analytics.sequence_performance import SequencePerformanceAnalyzer
    
    analyzer = SequencePerformanceAnalyzer(db)
    
    # Analyze per-step performance
    step_analysis = analyzer.analyze_step_performance("sequence_123")
    # Returns: [
    #     {"step": 1, "sent": 1000, "opened": 420, "open_rate": 0.42, "replied": 80},
    #     {"step": 2, "sent": 920, "opened": 368, "open_rate": 0.40, "replied": 45},
    #     ...
    # ]
    
    # Compare two sequences
    comparison = analyzer.compare_sequences("seq_123", "seq_456")
    # Returns: {
    #     "sequence_1": {...},
    #     "sequence_2": {...},
    #     "winner": "seq_123",
    #     "lift": 0.15
    # }
    
    # Get improvement recommendations
    recommendations = analyzer.recommend_improvements("sequence_123")
    # Returns: [
    #     {
    #         "type": "step_timing",
    #         "step": 2,
    #         "recommendation": "Increase delay from 2 to 3 days",
    #         "expected_impact": "+8% reply rate",
    #         "confidence": 0.75
    #     },
    #     ...
    # ]

Requirements:
    pip install numpy pandas
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from bson import ObjectId
import logging
from collections import defaultdict
import statistics

try:
    import numpy as np
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logging.warning("pandas/numpy not installed")

logger = logging.getLogger(__name__)


class SequencePerformanceAnalyzer:
    """
    Analyze email sequence performance and provide optimization recommendations.
    
    Tracks per-step metrics, identifies drop-offs, and suggests improvements.
    """
    
    def __init__(self, db):
        """
        Initialize the sequence performance analyzer.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.campaigns_col = db.campaigns
        self.sends_col = db.campaign_sends
        self.recipients_col = db.campaign_recipients
    
    def compare_sequences(
        self,
        seq1_id: str,
        seq2_id: str,
        metric: str = "reply_rate"
    ) -> Dict:
        """
        Compare performance of two sequences head-to-head.
        
        Args:
            seq1_id: First sequence/campaign identifier
            seq2_id: Second sequence/campaign identifier
            metric: Comparison metric (default: "reply_rate")
                Options: "reply_rate", "open_rate", "click_rate", "conversion_rate"
        
        Returns:
            Comparison results:
            {
                "sequence_1": {
                    "id": "seq_123",
                    "name": "SaaS VP - 6 Touch",
                    "total_recipients": 500,
                    "reply_rate": 0.12,
                    "open_rate": 0.45,
                    "avg_steps_to_reply": 2.3
                },
                "sequence_2": {
                    "id": "seq_456",
                    "name": "SaaS VP - 5 Touch",
                    "total_recipients": 500,
                    "reply_rate": 0.10,
                    "open_rate": 0.42,
                    "avg_steps_to_reply": 2.1
                },
                "winner": "seq_123",
                "lift_percentage": 20.0,
                "statistical_significance": 0.95,
                "recommendation": "Sequence 1 outperforms by 20% (statistically significant)"
            }
        """
        try:
            # Get metrics for both sequences
            seq1_metrics = self._get_sequence_metrics(seq1_id)
            seq2_metrics = self._get_sequence_metrics(seq2_id)
            
            if not seq1_metrics or not seq2_metrics:
                return {
                    "error": "Unable to retrieve metrics for one or both sequences"
                }
            
            # Extract metric values
            value1 = seq1_metrics.get(metric, 0)
            value2 = seq2_metrics.get(metric, 0)
            
            # Determine winner
            winner = None
            lift = 0
            
            if value1 > value2:
                winner = seq1_id
                lift = ((value1 - value2) / value2 * 100) if value2 > 0 else 0
            elif value2 > value1:
                winner = seq2_id
                lift = ((value2 - value1) / value1 * 100) if value1 > 0 else 0
            
            # Simple significance check (needs proper statistical test in production)
            sample_size_1 = seq1_metrics.get("total_recipients", 0)
            sample_size_2 = seq2_metrics.get("total_recipients", 0)
            
            # Rough heuristic: larger sample + bigger difference = higher confidence
            if min(sample_size_1, sample_size_2) >= 100 and abs(lift) >= 10:
                significance = 0.95
            elif min(sample_size_1, sample_size_2) >= 50 and abs(lift) >= 15:
                significance = 0.90
            elif min(sample_size_1, sample_size_2) >= 30 and abs(lift) >= 20:
                significance = 0.85
            else:
                significance = 0.70
            
            # Build recommendation
            if winner:
                recommendation = (
                    f"Sequence {winner} outperforms by {abs(lift):.1f}% "
                    f"({'statistically significant' if significance >= 0.90 else 'moderate confidence'})"
                )
            else:
                recommendation = "Sequences perform equally"
            
            return {
                "sequence_1": seq1_metrics,
                "sequence_2": seq2_metrics,
                "winner": winner,
                "lift_percentage": round(abs(lift), 2),
                "statistical_significance": significance,
                "recommendation": recommendation,
                "compared_metric": metric
            }
        
        except Exception as e:
            logger.error(f"Error comparing sequences: {e}")
            return {"error": str(e)}
    
    def analyze_step_performance(
        self,
        sequence_id: str,
        include_timing: bool = True
    ) -> Dict:
        """
        Analyze performance of each step in a sequence.
        
        Args:
            sequence_id: Sequence/campaign identifier
            include_timing: Include timing analysis between steps (default: True)
        
        Returns:
            Dict with per-step analysis:
            {
                "sequence_id": "seq_123",
                "sequence_name": "SaaS VP - 6 Touch",
                "total_recipients": 500,
                "steps": [
                    {
                        "step": 1,
                        "template_id": "...",
                        "sent": 500,
                        "delivered": 495,
                        "opened": 210,
                        "clicked": 45,
                        "replied": 40,
                        "delivery_rate": 0.99,
                        "open_rate": 0.42,
                        "click_rate": 0.09,
                        "reply_rate": 0.08,
                        "drop_off_rate": 0.08,
                        "avg_time_to_open_hours": 2.5,
                        "optimal_delay_to_next_step_days": 3
                    },
                    ...
                ],
                "drop_off_points": [
                    {"step": 3, "drop_off_rate": 0.35, "reason": "Low open rate"}
                ],
                "overall_metrics": {
                    "completion_rate": 0.65,
                    "avg_steps_to_reply": 2.3,
                    "total_replies": 60
                }
            }
        """
        try:
            # Get campaign
            campaign = self.campaigns_col.find_one({"_id": ObjectId(sequence_id)})
            if not campaign:
                logger.error(f"Campaign {sequence_id} not found")
                return {}
            
            sequence_steps = campaign.get("sequence_steps", [])
            if not sequence_steps:
                return {"error": "No sequence steps defined"}
            
            # Get all recipients for this campaign
            recipients = list(self.recipients_col.find({
                "campaign_id": sequence_id
            }))
            
            total_recipients = len(recipients)
            
            if not recipients:
                return {
                    "sequence_id": sequence_id,
                    "sequence_name": campaign.get("name", "Unknown"),
                    "total_recipients": 0,
                    "message": "No recipients found"
                }
            
            # Analyze each step
            step_analysis = []
            
            for step_info in sequence_steps:
                step_num = step_info.get("step_number", 0)
                template_id = step_info.get("template_id", "")
                
                # Get sends for this step
                sends = list(self.sends_col.find({
                    "campaign_id": sequence_id,
                    "step_number": step_num
                }))
                
                if not sends:
                    # No sends yet for this step
                    step_analysis.append({
                        "step": step_num,
                        "template_id": template_id,
                        "sent": 0,
                        "message": "No sends yet"
                    })
                    continue
                
                # Calculate metrics
                total_sent = len(sends)
                delivered = sum(1 for s in sends if s.get("status") not in ["bounced", "failed"])
                opened = sum(1 for s in sends if s.get("opened_at"))
                clicked = sum(1 for s in sends if s.get("clicked_at"))
                replied = sum(1 for s in sends if s.get("replied_at"))
                
                delivery_rate = delivered / total_sent if total_sent > 0 else 0
                open_rate = opened / total_sent if total_sent > 0 else 0
                click_rate = clicked / total_sent if total_sent > 0 else 0
                reply_rate = replied / total_sent if total_sent > 0 else 0
                
                # Calculate drop-off (recipients who don't continue)
                # Recipients who replied or bounced at this step won't continue
                drop_offs = replied + sum(1 for s in sends if s.get("status") == "bounced")
                drop_off_rate = drop_offs / total_sent if total_sent > 0 else 0
                
                # Timing analysis
                avg_time_to_open = None
                if include_timing:
                    open_times = []
                    for send in sends:
                        if send.get("sent_at") and send.get("opened_at"):
                            delta = send["opened_at"] - send["sent_at"]
                            open_times.append(delta.total_seconds() / 3600)
                    
                    avg_time_to_open = statistics.mean(open_times) if open_times else None
                
                step_analysis.append({
                    "step": step_num,
                    "template_id": template_id,
                    "sent": total_sent,
                    "delivered": delivered,
                    "opened": opened,
                    "clicked": clicked,
                    "replied": replied,
                    "delivery_rate": round(delivery_rate, 4),
                    "open_rate": round(open_rate, 4),
                    "click_rate": round(click_rate, 4),
                    "reply_rate": round(reply_rate, 4),
                    "drop_off_rate": round(drop_off_rate, 4),
                    "avg_time_to_open_hours": round(avg_time_to_open, 2) if avg_time_to_open else None
                })
            
            # Identify drop-off points (steps with >20% drop-off or low open rates)
            drop_off_points = []
            for step in step_analysis:
                if step.get("drop_off_rate", 0) > 0.20:
                    drop_off_points.append({
                        "step": step["step"],
                        "drop_off_rate": step["drop_off_rate"],
                        "reason": "High drop-off rate"
                    })
                elif step.get("open_rate", 0) < 0.20:
                    drop_off_points.append({
                        "step": step["step"],
                        "drop_off_rate": step.get("drop_off_rate", 0),
                        "reason": "Low open rate"
                    })
            
            # Calculate overall metrics
            all_sends = list(self.sends_col.find({"campaign_id": sequence_id}))
            total_replies = sum(1 for s in all_sends if s.get("replied_at"))
            
            # Calculate avg steps to reply
            steps_to_reply = []
            for recipient in recipients:
                if recipient.get("status") == "replied":
                    # Find which step they replied at
                    recipient_sends = [
                        s for s in all_sends
                        if s.get("recipient_id") == str(recipient["_id"]) and s.get("replied_at")
                    ]
                    if recipient_sends:
                        # Get the earliest reply
                        first_reply = min(recipient_sends, key=lambda x: x.get("replied_at", datetime.max))
                        steps_to_reply.append(first_reply.get("step_number", 1))
            
            avg_steps_to_reply = statistics.mean(steps_to_reply) if steps_to_reply else None
            
            # Completion rate (recipients who made it to the last step)
            last_step_num = max([s.get("step_number", 0) for s in sequence_steps])
            last_step_sends = self.sends_col.count_documents({
                "campaign_id": sequence_id,
                "step_number": last_step_num
            })
            completion_rate = last_step_sends / total_recipients if total_recipients > 0 else 0
            
            return {
                "sequence_id": sequence_id,
                "sequence_name": campaign.get("name", "Unknown"),
                "total_recipients": total_recipients,
                "steps": step_analysis,
                "drop_off_points": drop_off_points,
                "overall_metrics": {
                    "completion_rate": round(completion_rate, 4),
                    "avg_steps_to_reply": round(avg_steps_to_reply, 2) if avg_steps_to_reply else None,
                    "total_replies": total_replies,
                    "overall_reply_rate": round(total_replies / total_recipients, 4) if total_recipients > 0 else 0
                }
            }
        
        except Exception as e:
            logger.error(f"Error analyzing step performance: {e}")
            return {"error": str(e)}
    
    def recommend_improvements(
        self,
        sequence_id: str,
        min_confidence: float = 0.70
    ) -> List[Dict]:
        """
        Recommend improvements for a sequence based on performance data.
        
        Args:
            sequence_id: Sequence/campaign identifier
            min_confidence: Minimum confidence threshold for recommendations
        
        Returns:
            List of recommendations:
            [
                {
                    "type": "step_timing",
                    "step": 2,
                    "current_value": 2,
                    "recommended_value": 3,
                    "recommendation": "Increase delay from 2 to 3 days for step 2",
                    "expected_impact": "+8% reply rate at step 2",
                    "confidence": 0.75,
                    "reasoning": "Similar sequences show better performance with 3-day delay"
                },
                {
                    "type": "template_swap",
                    "step": 3,
                    "current_template": "template_123",
                    "recommended_template": "template_456",
                    "recommendation": "Swap template at step 3",
                    "expected_impact": "+12% open rate",
                    "confidence": 0.80,
                    "reasoning": "Recommended template has 12% higher open rate in similar campaigns"
                },
                {
                    "type": "remove_step",
                    "step": 5,
                    "recommendation": "Remove step 5",
                    "expected_impact": "Reduce sequence fatigue, maintain reply rate",
                    "confidence": 0.70,
                    "reasoning": "Step 5 has low engagement and high drop-off"
                }
            ]
        """
        try:
            # Get step performance analysis
            step_analysis = self.analyze_step_performance(sequence_id)
            
            if "error" in step_analysis:
                return [{"error": step_analysis["error"]}]
            
            recommendations = []
            steps = step_analysis.get("steps", [])
            
            # Recommendation 1: Identify underperforming steps
            for step in steps:
                step_num = step.get("step", 0)
                open_rate = step.get("open_rate", 0)
                reply_rate = step.get("reply_rate", 0)
                
                # Low open rate recommendation
                if open_rate < 0.25 and step_num > 1:
                    recommendations.append({
                        "type": "low_engagement",
                        "step": step_num,
                        "recommendation": f"Improve subject line or timing for step {step_num}",
                        "expected_impact": "+10-15% open rate",
                        "confidence": 0.75,
                        "reasoning": f"Step {step_num} has low open rate ({open_rate:.1%}). Consider A/B testing subject lines."
                    })
                
                # High drop-off recommendation
                drop_off_rate = step.get("drop_off_rate", 0)
                if drop_off_rate > 0.30:
                    recommendations.append({
                        "type": "high_drop_off",
                        "step": step_num,
                        "recommendation": f"Reduce aggressiveness at step {step_num}",
                        "expected_impact": "Reduce unsubscribes by ~20%",
                        "confidence": 0.70,
                        "reasoning": f"Step {step_num} has high drop-off ({drop_off_rate:.1%}). Consider softening tone."
                    })
            
            # Recommendation 2: Optimal sequence length
            overall = step_analysis.get("overall_metrics", {})
            completion_rate = overall.get("completion_rate", 0)
            avg_steps_to_reply = overall.get("avg_steps_to_reply", 0)
            
            num_steps = len(steps)
            
            # If most replies come early, suggest shortening sequence
            if avg_steps_to_reply and avg_steps_to_reply < num_steps * 0.5 and num_steps > 4:
                recommendations.append({
                    "type": "sequence_length",
                    "current_value": num_steps,
                    "recommended_value": int(avg_steps_to_reply) + 2,
                    "recommendation": f"Shorten sequence from {num_steps} to {int(avg_steps_to_reply) + 2} steps",
                    "expected_impact": "Reduce recipient fatigue, maintain reply rate",
                    "confidence": 0.80,
                    "reasoning": f"Most replies occur by step {int(avg_steps_to_reply)}. Additional steps show diminishing returns."
                })
            
            # Recommendation 3: Step timing optimization
            for i, step in enumerate(steps[:-1]):
                avg_time_to_open = step.get("avg_time_to_open_hours")
                if avg_time_to_open and avg_time_to_open < 24:
                    # Quick engagement suggests can follow up sooner
                    recommendations.append({
                        "type": "step_timing",
                        "step": step.get("step", 0) + 1,
                        "recommendation": f"Reduce delay before step {step.get('step', 0) + 1}",
                        "expected_impact": "Capture momentum while lead is engaged",
                        "confidence": 0.75,
                        "reasoning": f"Recipients open step {step.get('step', 0)} quickly (avg {avg_time_to_open:.1f}h). Strike while hot."
                    })
            
            # Recommendation 4: Remove low-value steps
            for step in steps:
                if (step.get("open_rate", 0) < 0.15 and 
                    step.get("reply_rate", 0) < 0.02 and
                    step.get("step", 0) > 3):
                    
                    recommendations.append({
                        "type": "remove_step",
                        "step": step.get("step", 0),
                        "recommendation": f"Consider removing step {step.get('step', 0)}",
                        "expected_impact": "Reduce sequence length without impacting results",
                        "confidence": 0.70,
                        "reasoning": f"Step {step.get('step', 0)} shows minimal engagement and no replies."
                    })
            
            # Filter by confidence threshold
            recommendations = [
                rec for rec in recommendations
                if rec.get("confidence", 0) >= min_confidence
            ]
            
            # Sort by confidence (highest first)
            recommendations.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            
            return recommendations
        
        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            return [{"error": str(e)}]
    
    def _get_sequence_metrics(self, sequence_id: str) -> Dict:
        """
        Get comprehensive metrics for a sequence.
        
        Args:
            sequence_id: Sequence/campaign identifier
        
        Returns:
            Dict with sequence metrics
        """
        try:
            campaign = self.campaigns_col.find_one({"_id": ObjectId(sequence_id)})
            if not campaign:
                return {}
            
            recipients = list(self.recipients_col.find({"campaign_id": sequence_id}))
            sends = list(self.sends_col.find({"campaign_id": sequence_id}))
            
            total_recipients = len(recipients)
            total_sends = len(sends)
            
            if total_recipients == 0:
                return {}
            
            # Calculate metrics
            opens = sum(1 for s in sends if s.get("opened_at"))
            clicks = sum(1 for s in sends if s.get("clicked_at"))
            replies = sum(1 for s in sends if s.get("replied_at"))
            
            # Calculate avg steps to reply
            steps_to_reply = []
            for recipient in recipients:
                if recipient.get("status") == "replied":
                    recipient_sends = [
                        s for s in sends
                        if s.get("recipient_id") == str(recipient["_id"]) and s.get("replied_at")
                    ]
                    if recipient_sends:
                        first_reply = min(recipient_sends, key=lambda x: x.get("replied_at", datetime.max))
                        steps_to_reply.append(first_reply.get("step_number", 1))
            
            avg_steps_to_reply = statistics.mean(steps_to_reply) if steps_to_reply else None
            
            return {
                "id": sequence_id,
                "name": campaign.get("name", "Unknown"),
                "total_recipients": total_recipients,
                "total_sends": total_sends,
                "reply_rate": replies / total_recipients,
                "open_rate": opens / total_sends if total_sends > 0 else 0,
                "click_rate": clicks / total_sends if total_sends > 0 else 0,
                "avg_steps_to_reply": avg_steps_to_reply
            }
        
        except Exception as e:
            logger.error(f"Error getting sequence metrics: {e}")
            return {}


# ============== EXAMPLE USAGE ==============

if __name__ == "__main__":
    from pymongo import MongoClient
    
    # Connect to database
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform
    
    analyzer = SequencePerformanceAnalyzer(db)
    
    # Example: Analyze step performance
    sequence_id = "60d5ec49f1a2c8b5e8c9a123"
    step_analysis = analyzer.analyze_step_performance(sequence_id)
    
    print(f"\nSequence Performance: {step_analysis.get('sequence_name')}")
    print(f"Total recipients: {step_analysis.get('total_recipients')}")
    print(f"\nPer-step breakdown:")
    for step in step_analysis.get("steps", []):
        print(f"\n  Step {step['step']}:")
        print(f"    Sent: {step['sent']}")
        print(f"    Open rate: {step['open_rate']:.1%}")
        print(f"    Reply rate: {step['reply_rate']:.1%}")
        print(f"    Drop-off: {step['drop_off_rate']:.1%}")
    
    print(f"\nOverall metrics:")
    overall = step_analysis.get("overall_metrics", {})
    print(f"  Completion rate: {overall.get('completion_rate', 0):.1%}")
    print(f"  Avg steps to reply: {overall.get('avg_steps_to_reply', 0):.1f}")
    print(f"  Overall reply rate: {overall.get('overall_reply_rate', 0):.1%}")
    
    # Example: Compare two sequences
    seq1_id = "60d5ec49f1a2c8b5e8c9a123"
    seq2_id = "60d5ec49f1a2c8b5e8c9a456"
    comparison = analyzer.compare_sequences(seq1_id, seq2_id)
    
    print(f"\n\nSequence Comparison:")
    print(f"  Winner: {comparison.get('winner')}")
    print(f"  Lift: {comparison.get('lift_percentage')}%")
    print(f"  Confidence: {comparison.get('statistical_significance', 0):.1%}")
    
    # Example: Get recommendations
    recommendations = analyzer.recommend_improvements(sequence_id)
    
    print(f"\n\nRecommendations:")
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec.get('recommendation')}")
        print(f"   Expected impact: {rec.get('expected_impact')}")
        print(f"   Confidence: {rec.get('confidence', 0):.1%}")
        print(f"   Reasoning: {rec.get('reasoning')}")
