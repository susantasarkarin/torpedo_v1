"""
Lead Prioritizer Agent
Continuously re-ranks leads based on reply probability and engagement signals
"""

from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

class LeadPrioritizer:
    """
    Intelligent lead prioritization based on multiple signals
    Uses ML predictions and engagement data to rank leads
    """
    
    def __init__(self, db, reply_predictor=None):
        self.db = db
        self.reply_predictor = reply_predictor
        
        # Scoring weights
        self.weights = {
            'reply_probability': 0.35,
            'engagement_score': 0.25,
            'recency': 0.15,
            'profile_completeness': 0.10,
            'company_fit': 0.10,
            'timing': 0.05
        }
        
        # Priority thresholds
        self.thresholds = {
            'hot': 0.75,
            'warm': 0.50,
            'cold': 0.25
        }
    
    async def prioritize_leads(self, lead_ids: List[str]) -> List[str]:
        """
        Sort leads by likelihood of positive response
        
        Args:
            lead_ids: List of lead IDs to prioritize
            
        Returns:
            Sorted list of lead IDs (highest priority first)
        """
        # Fetch leads
        leads = await self.db.leads.find({
            '_id': {'$in': lead_ids}
        }).to_list(length=None)
        
        # Calculate priority score for each lead
        scored_leads = []
        
        for lead in leads:
            score = await self._calculate_priority_score(lead)
            scored_leads.append((str(lead['_id']), score))
        
        # Sort by score (descending)
        scored_leads.sort(key=lambda x: x[1], reverse=True)
        
        # Return just the IDs
        return [lead_id for lead_id, score in scored_leads]
    
    async def _calculate_priority_score(self, lead: Dict) -> float:
        """
        Calculate comprehensive priority score for lead
        
        Args:
            lead: Lead dictionary
            
        Returns:
            Priority score between 0.0 and 1.0
        """
        scores = {}
        
        # 1. Reply probability (ML model)
        if self.reply_predictor:
            scores['reply_probability'] = self.reply_predictor.predict_reply_probability(lead)
        else:
            scores['reply_probability'] = self._heuristic_reply_score(lead)
        
        # 2. Engagement score
        scores['engagement_score'] = self._calculate_engagement_score(lead)
        
        # 3. Recency score
        scores['recency'] = self._calculate_recency_score(lead)
        
        # 4. Profile completeness
        scores['profile_completeness'] = self._calculate_profile_completeness(lead)
        
        # 5. Company fit score
        scores['company_fit'] = self._calculate_company_fit(lead)
        
        # 6. Timing score
        scores['timing'] = self._calculate_timing_score(lead)
        
        # Calculate weighted total
        total_score = sum(
            scores[key] * self.weights[key]
            for key in scores.keys()
        )
        
        return min(total_score, 1.0)  # Cap at 1.0
    
    def _heuristic_reply_score(self, lead: Dict) -> float:
        """Fallback heuristic for reply probability"""
        score = 0.5  # Base score
        
        if lead.get('email_opens', 0) > 0:
            score += 0.15
        if lead.get('email_clicks', 0) > 0:
            score += 0.20
        if lead.get('previous_replies', 0) > 0:
            score += 0.15
        
        return min(score, 1.0)
    
    def _calculate_engagement_score(self, lead: Dict) -> float:
        """Calculate engagement score based on interactions"""
        score = 0.0
        
        # Email opens (up to 0.3)
        opens = lead.get('email_opens', 0)
        score += min(opens * 0.05, 0.3)
        
        # Email clicks (up to 0.3)
        clicks = lead.get('email_clicks', 0)
        score += min(clicks * 0.1, 0.3)
        
        # Link clicks (up to 0.2)
        link_clicks = lead.get('link_clicks', 0)
        score += min(link_clicks * 0.1, 0.2)
        
        # Previous replies (up to 0.2)
        replies = lead.get('previous_replies', 0)
        score += min(replies * 0.1, 0.2)
        
        return min(score, 1.0)
    
    def _calculate_recency_score(self, lead: Dict) -> float:
        """Score based on recent activity"""
        last_activity = lead.get('last_activity_date')
        
        if not last_activity:
            return 0.2  # Low score for inactive leads
        
        if isinstance(last_activity, str):
            last_activity = datetime.fromisoformat(last_activity)
        
        days_since_activity = (datetime.now() - last_activity).days
        
        # Score decreases with time
        if days_since_activity <= 1:
            return 1.0
        elif days_since_activity <= 3:
            return 0.8
        elif days_since_activity <= 7:
            return 0.6
        elif days_since_activity <= 14:
            return 0.4
        elif days_since_activity <= 30:
            return 0.2
        else:
            return 0.1
    
    def _calculate_profile_completeness(self, lead: Dict) -> float:
        """Score based on data completeness"""
        fields = [
            'first_name', 'last_name', 'email', 'company', 'title',
            'industry', 'seniority', 'company_size', 'phone', 'linkedin'
        ]
        
        filled_fields = sum(1 for field in fields if lead.get(field))
        
        return filled_fields / len(fields)
    
    def _calculate_company_fit(self, lead: Dict) -> float:
        """Score based on company characteristics"""
        score = 0.5  # Base score
        
        # Company size preference (adjust based on ICP)
        company_size = lead.get('company_size', '')
        if company_size in ['51-200', '201-500', '501-1000']:
            score += 0.2
        elif company_size in ['1001-5000', '5000+']:
            score += 0.1
        
        # Industry fit (would be customized per campaign)
        industry = lead.get('industry', '')
        target_industries = ['Technology', 'Software', 'SaaS', 'IT Services']
        if industry in target_industries:
            score += 0.2
        
        # Seniority level
        seniority = lead.get('seniority', '')
        if seniority in ['C-Level', 'VP', 'Director']:
            score += 0.15
        elif seniority in ['Manager', 'Senior']:
            score += 0.05
        
        return min(score, 1.0)
    
    def _calculate_timing_score(self, lead: Dict) -> float:
        """Score based on optimal timing factors"""
        now = datetime.now()
        
        # Check if it's a good time to reach out
        hour = now.hour
        day_of_week = now.weekday()
        
        score = 0.5
        
        # Best hours: 9-11 AM and 2-4 PM
        if (9 <= hour <= 11) or (14 <= hour <= 16):
            score += 0.3
        
        # Best days: Tuesday, Wednesday, Thursday
        if day_of_week in [1, 2, 3]:
            score += 0.2
        
        return min(score, 1.0)
    
    async def surface_hot_leads(self, limit: int = 10) -> List[Dict]:
        """
        Get top leads most likely to reply today
        
        Args:
            limit: Maximum number of leads to return
            
        Returns:
            List of hot lead details with priority scores
        """
        # Fetch active, engaged leads
        leads = await self.db.leads.find({
            'status': {'$in': ['active', 'engaged']},
            'emails_sent': {'$gt': 0},
            '$or': [
                {'last_activity_date': {'$gte': datetime.now() - timedelta(days=7)}},
                {'email_opens': {'$gt': 0}},
                {'email_clicks': {'$gt': 0}}
            ]
        }).to_list(length=None)
        
        hot_leads = []
        
        for lead in leads:
            score = await self._calculate_priority_score(lead)
            
            # Only include high-scoring leads
            if score >= self.thresholds['hot']:
                hot_leads.append({
                    'lead_id': str(lead['_id']),
                    'name': f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                    'company': lead.get('company', 'N/A'),
                    'title': lead.get('title', ''),
                    'email': lead.get('email', ''),
                    'priority_score': score,
                    'priority_level': 'hot',
                    'last_activity': lead.get('last_activity_date'),
                    'email_opens': lead.get('email_opens', 0),
                    'email_clicks': lead.get('email_clicks', 0),
                    'previous_replies': lead.get('previous_replies', 0),
                    'recommended_action': self._get_recommended_action(lead, score)
                })
        
        # Sort by score and limit
        hot_leads.sort(key=lambda x: x['priority_score'], reverse=True)
        
        return hot_leads[:limit]
    
    def _get_recommended_action(self, lead: Dict, score: float) -> str:
        """Get recommended next action for lead"""
        if lead.get('previous_replies', 0) > 0:
            return "Follow up on previous conversation"
        elif lead.get('email_opens', 0) > 2:
            return "Send value-focused message (showing interest)"
        elif lead.get('email_clicks', 0) > 0:
            return "Reference clicked content in follow-up"
        else:
            return "Send personalized outreach"
    
    async def identify_low_probability(self, threshold: float = 0.1) -> List[str]:
        """
        Identify leads with low reply probability
        
        Args:
            threshold: Maximum probability threshold (default 10%)
            
        Returns:
            List of low-probability lead IDs
        """
        # Fetch all active leads
        leads = await self.db.leads.find({
            'status': 'active',
            'emails_sent': {'$gte': 2}  # At least 2 emails sent
        }).to_list(length=None)
        
        low_probability_leads = []
        
        for lead in leads:
            score = await self._calculate_priority_score(lead)
            
            if score <= threshold:
                low_probability_leads.append(str(lead['_id']))
        
        return low_probability_leads
    
    async def segment_leads_by_priority(self) -> Dict[str, List[Dict]]:
        """
        Segment all active leads by priority level
        
        Returns:
            Dictionary with hot, warm, and cold lead segments
        """
        leads = await self.db.leads.find({
            'status': {'$in': ['active', 'engaged']}
        }).to_list(length=None)
        
        segments = {
            'hot': [],
            'warm': [],
            'cold': []
        }
        
        for lead in leads:
            score = await self._calculate_priority_score(lead)
            
            lead_info = {
                'lead_id': str(lead['_id']),
                'name': f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                'company': lead.get('company', 'N/A'),
                'score': score
            }
            
            if score >= self.thresholds['hot']:
                segments['hot'].append(lead_info)
            elif score >= self.thresholds['warm']:
                segments['warm'].append(lead_info)
            else:
                segments['cold'].append(lead_info)
        
        # Sort each segment by score
        for segment in segments.values():
            segment.sort(key=lambda x: x['score'], reverse=True)
        
        return segments
    
    async def update_lead_priorities(self) -> Dict:
        """
        Batch update priority scores for all leads
        
        Returns:
            Update statistics
        """
        leads = await self.db.leads.find({
            'status': {'$in': ['active', 'engaged']}
        }).to_list(length=None)
        
        updated_count = 0
        
        for lead in leads:
            score = await self._calculate_priority_score(lead)
            
            # Determine priority level
            if score >= self.thresholds['hot']:
                priority = 'hot'
            elif score >= self.thresholds['warm']:
                priority = 'warm'
            else:
                priority = 'cold'
            
            # Update lead
            await self.db.leads.update_one(
                {'_id': lead['_id']},
                {
                    '$set': {
                        'priority_score': score,
                        'priority_level': priority,
                        'priority_updated_at': datetime.now()
                    }
                }
            )
            
            updated_count += 1
        
        return {
            'updated_count': updated_count,
            'total_leads': len(leads),
            'updated_at': datetime.now().isoformat()
        }
    
    async def get_priority_distribution(self) -> Dict:
        """
        Get distribution of leads across priority levels
        
        Returns:
            Distribution statistics
        """
        total_leads = await self.db.leads.count_documents({'status': {'$in': ['active', 'engaged']}})
        
        hot_count = await self.db.leads.count_documents({
            'status': {'$in': ['active', 'engaged']},
            'priority_level': 'hot'
        })
        
        warm_count = await self.db.leads.count_documents({
            'status': {'$in': ['active', 'engaged']},
            'priority_level': 'warm'
        })
        
        cold_count = await self.db.leads.count_documents({
            'status': {'$in': ['active', 'engaged']},
            'priority_level': 'cold'
        })
        
        return {
            'total_leads': total_leads,
            'hot': {
                'count': hot_count,
                'percentage': (hot_count / total_leads * 100) if total_leads > 0 else 0
            },
            'warm': {
                'count': warm_count,
                'percentage': (warm_count / total_leads * 100) if total_leads > 0 else 0
            },
            'cold': {
                'count': cold_count,
                'percentage': (cold_count / total_leads * 100) if total_leads > 0 else 0
            }
        }


class LeadPrioritizerService:
    """Service layer for lead prioritization"""
    
    def __init__(self, db, reply_predictor=None):
        self.db = db
        self.prioritizer = LeadPrioritizer(db, reply_predictor)
    
    async def get_daily_priority_list(self, user_id: str = None) -> Dict:
        """
        Get daily priority list for user
        
        Args:
            user_id: Optional user ID to filter leads
            
        Returns:
            Prioritized daily action list
        """
        hot_leads = await self.prioritizer.surface_hot_leads(limit=20)
        
        # Group by recommended action
        by_action = defaultdict(list)
        for lead in hot_leads:
            action = lead.get('recommended_action', 'other')
            by_action[action].append(lead)
        
        return {
            'date': datetime.now().date().isoformat(),
            'total_hot_leads': len(hot_leads),
            'by_action': dict(by_action),
            'top_priorities': hot_leads[:10],
            'generated_at': datetime.now().isoformat()
        }
    
    async def run_prioritization_cycle(self) -> Dict:
        """
        Run complete prioritization cycle
        
        Returns:
            Cycle results
        """
        print("Starting lead prioritization cycle...")
        
        # Update all lead priorities
        update_result = await self.prioritizer.update_lead_priorities()
        
        # Get distribution
        distribution = await self.prioritizer.get_priority_distribution()
        
        # Get hot leads
        hot_leads = await self.prioritizer.surface_hot_leads(limit=20)
        
        return {
            'cycle_completed_at': datetime.now().isoformat(),
            'update_result': update_result,
            'distribution': distribution,
            'hot_leads_count': len(hot_leads),
            'top_hot_leads': hot_leads[:5]
        }
