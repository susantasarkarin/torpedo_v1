"""
Funnel Analytics - Conversion Pipeline Analysis
Customizable stages, conversion rates, drop-off identification
"""

from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from bson import ObjectId
from database import db
import logging

logger = logging.getLogger(__name__)


class FunnelAnalyzer:
    """Analyze conversion funnels with customizable stages"""
    
    DEFAULT_FUNNELS = {
        'email_outreach': [
            'Email Sent',
            'Email Opened',
            'Link Clicked',
            'Reply Received',
            'Meeting Booked',
            'Deal Closed'
        ],
        'lead_lifecycle': [
            'Lead Created',
            'First Contact',
            'Engaged',
            'Qualified',
            'Proposal Sent',
            'Negotiation',
            'Closed Won'
        ],
        'campaign': [
            'Campaign Launched',
            'Leads Contacted',
            'Responses',
            'Qualified Opportunities',
            'Revenue Generated'
        ]
    }
    
    # Stage condition mappings
    STAGE_CONDITIONS = {
        'Email Sent': {'collection': 'email_tracking', 'field': 'status', 'value': 'sent'},
        'Email Opened': {'collection': 'email_tracking', 'field': 'opened', 'value': True},
        'Link Clicked': {'collection': 'email_tracking', 'field': 'clicked', 'value': True},
        'Reply Received': {'collection': 'email_tracking', 'field': 'replied', 'value': True},
        'Meeting Booked': {'collection': 'leads', 'field': 'meeting_booked', 'value': True},
        'Deal Closed': {'collection': 'leads', 'field': 'deal_closed', 'value': True},
        'Lead Created': {'collection': 'leads', 'field': '_id', 'value': '$exists'},
        'First Contact': {'collection': 'email_tracking', 'field': 'first_email_sent', 'value': True},
        'Engaged': {'collection': 'leads', 'field': 'engagement_score', 'value': {'$gte': 3}},
        'Qualified': {'collection': 'leads', 'field': 'qualified', 'value': True},
        'Proposal Sent': {'collection': 'leads', 'field': 'proposal_sent', 'value': True},
        'Negotiation': {'collection': 'leads', 'field': 'stage', 'value': 'negotiation'},
        'Closed Won': {'collection': 'leads', 'field': 'deal_closed', 'value': True}
    }
    
    def __init__(self):
        logger.info("FunnelAnalyzer initialized")
    
    def define_funnel(
        self,
        funnel_name: str,
        stages: List[str],
        conditions: Optional[List[Dict]] = None,
        funnel_type: str = 'custom'
    ) -> str:
        """
        Define a new conversion funnel
        
        Args:
            funnel_name: Display name for funnel
            stages: List of stage names in order
            conditions: Optional custom conditions for each stage
            funnel_type: Type of funnel (email_outreach, lead_lifecycle, campaign, custom)
        
        Returns:
            Funnel ID
        """
        try:
            if len(stages) < 2:
                raise ValueError("Funnel must have at least 2 stages")
            
            # Use default conditions if not provided
            if conditions is None:
                conditions = []
                for stage in stages:
                    if stage in self.STAGE_CONDITIONS:
                        conditions.append(self.STAGE_CONDITIONS[stage])
                    else:
                        # Default condition
                        conditions.append({
                            'collection': 'leads',
                            'field': 'stage',
                            'value': stage.lower().replace(' ', '_')
                        })
            
            if len(conditions) != len(stages):
                raise ValueError("Number of conditions must match number of stages")
            
            # Create funnel document
            funnel = {
                'funnel_id': str(ObjectId()),
                'name': funnel_name,
                'type': funnel_type,
                'stages': stages,
                'conditions': conditions,
                'created_at': datetime.utcnow(),
                'status': 'active'
            }
            
            db.funnels.insert_one(funnel)
            
            logger.info(f"Funnel created: {funnel['funnel_id']} with {len(stages)} stages")
            return funnel['funnel_id']
            
        except Exception as e:
            logger.error(f"Error defining funnel: {str(e)}")
            raise
    
    def analyze_funnel(
        self,
        funnel_id: str,
        date_range: Optional[Tuple[datetime, datetime]] = None,
        filters: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Analyze funnel performance
        
        Args:
            funnel_id: Funnel to analyze
            date_range: Optional (start_date, end_date) tuple
            filters: Optional additional filters (campaign_id, industry, etc.)
        
        Returns:
            Dict with stage counts, conversion rates, and visualizations
        """
        try:
            funnel = db.funnels.find_one({'funnel_id': funnel_id})
            if not funnel:
                raise ValueError(f"Funnel not found: {funnel_id}")
            
            # Build base query
            base_query = {}
            if date_range:
                start_date, end_date = date_range
                base_query['created_at'] = {'$gte': start_date, '$lte': end_date}
            
            if filters:
                base_query.update(filters)
            
            # Calculate counts for each stage
            stage_data = []
            previous_count = None
            
            for idx, (stage_name, condition) in enumerate(zip(funnel['stages'], funnel['conditions'])):
                # Build query for this stage
                stage_query = base_query.copy()
                
                # Add stage-specific condition
                if condition['value'] == '$exists':
                    stage_query[condition['field']] = {'$exists': True}
                elif isinstance(condition['value'], dict):
                    stage_query[condition['field']] = condition['value']
                else:
                    stage_query[condition['field']] = condition['value']
                
                # Query appropriate collection
                collection = db[condition['collection']]
                count = collection.count_documents(stage_query)
                
                # Calculate conversion rate
                conversion_rate = 0
                if idx == 0:
                    conversion_rate = 100  # First stage is always 100%
                elif previous_count and previous_count > 0:
                    conversion_rate = round(count / previous_count * 100, 2)
                
                # Calculate drop-off
                drop_off = 0
                drop_off_count = 0
                if previous_count is not None:
                    drop_off_count = previous_count - count
                    if previous_count > 0:
                        drop_off = round(drop_off_count / previous_count * 100, 2)
                
                stage_data.append({
                    'stage_number': idx + 1,
                    'stage_name': stage_name,
                    'count': count,
                    'conversion_rate': conversion_rate,
                    'drop_off': drop_off,
                    'drop_off_count': drop_off_count
                })
                
                previous_count = count
            
            # Calculate overall metrics
            total_entered = stage_data[0]['count'] if stage_data else 0
            total_completed = stage_data[-1]['count'] if stage_data else 0
            overall_conversion = round(total_completed / total_entered * 100, 2) if total_entered > 0 else 0
            
            analysis = {
                'funnel_id': funnel_id,
                'funnel_name': funnel['name'],
                'funnel_type': funnel['type'],
                'analyzed_at': datetime.utcnow().isoformat(),
                'date_range': {
                    'start': date_range[0].isoformat() if date_range else None,
                    'end': date_range[1].isoformat() if date_range else None
                },
                'filters': filters,
                'stages': stage_data,
                'summary': {
                    'total_stages': len(stage_data),
                    'total_entered': total_entered,
                    'total_completed': total_completed,
                    'overall_conversion_rate': overall_conversion,
                    'average_stage_conversion': round(
                        sum(s['conversion_rate'] for s in stage_data) / len(stage_data),
                        2
                    ) if stage_data else 0
                },
                'bottlenecks': self._identify_bottlenecks(stage_data),
                'recommendations': self._generate_recommendations(stage_data)
            }
            
            # Save analysis
            db.funnel_analyses.insert_one({
                **analysis,
                'created_at': datetime.utcnow()
            })
            
            logger.info(f"Funnel analyzed: {funnel_id}")
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing funnel: {str(e)}")
            raise
    
    def get_drop_off_points(
        self,
        funnel_id: str,
        threshold: float = 30.0
    ) -> List[Dict[str, Any]]:
        """
        Identify stages with significant drop-off
        
        Args:
            funnel_id: Funnel to analyze
            threshold: Drop-off percentage threshold (default 30%)
        
        Returns:
            List of stages with high drop-off
        """
        try:
            analysis = self.analyze_funnel(funnel_id)
            
            drop_off_points = []
            for stage in analysis['stages']:
                if stage['stage_number'] > 1 and stage['drop_off'] >= threshold:
                    drop_off_points.append({
                        'stage_number': stage['stage_number'],
                        'stage_name': stage['stage_name'],
                        'drop_off_percentage': stage['drop_off'],
                        'drop_off_count': stage['drop_off_count'],
                        'severity': self._classify_severity(stage['drop_off']),
                        'suggestions': self._get_drop_off_suggestions(stage['stage_name'])
                    })
            
            # Sort by drop-off percentage
            drop_off_points.sort(key=lambda x: x['drop_off_percentage'], reverse=True)
            
            logger.info(f"Found {len(drop_off_points)} drop-off points in funnel {funnel_id}")
            return drop_off_points
            
        except Exception as e:
            logger.error(f"Error getting drop-off points: {str(e)}")
            raise
    
    def compare_funnels(
        self,
        funnel_ids: List[str],
        date_range: Optional[Tuple[datetime, datetime]] = None
    ) -> Dict[str, Any]:
        """Compare performance across multiple funnels"""
        try:
            if len(funnel_ids) < 2:
                raise ValueError("Need at least 2 funnels to compare")
            
            comparison = {
                'funnels': [],
                'comparison_date': datetime.utcnow().isoformat()
            }
            
            for funnel_id in funnel_ids:
                analysis = self.analyze_funnel(funnel_id, date_range)
                comparison['funnels'].append({
                    'funnel_id': funnel_id,
                    'funnel_name': analysis['funnel_name'],
                    'overall_conversion': analysis['summary']['overall_conversion_rate'],
                    'total_entered': analysis['summary']['total_entered'],
                    'total_completed': analysis['summary']['total_completed']
                })
            
            # Find best performing
            best = max(comparison['funnels'], key=lambda f: f['overall_conversion'])
            comparison['best_performing'] = best
            
            return comparison
            
        except Exception as e:
            logger.error(f"Error comparing funnels: {str(e)}")
            raise
    
    def get_funnel_trends(
        self,
        funnel_id: str,
        num_periods: int = 12,
        period: str = 'week'
    ) -> Dict[str, Any]:
        """Track funnel performance over time"""
        try:
            funnel = db.funnels.find_one({'funnel_id': funnel_id})
            if not funnel:
                raise ValueError(f"Funnel not found: {funnel_id}")
            
            period_delta = {
                'day': timedelta(days=1),
                'week': timedelta(weeks=1),
                'month': timedelta(days=30)
            }.get(period, timedelta(weeks=1))
            
            trends = {
                'funnel_id': funnel_id,
                'funnel_name': funnel['name'],
                'period_type': period,
                'periods': []
            }
            
            end_date = datetime.utcnow()
            
            for i in range(num_periods):
                period_end = end_date - (period_delta * i)
                period_start = period_end - period_delta
                
                analysis = self.analyze_funnel(
                    funnel_id,
                    date_range=(period_start, period_end)
                )
                
                trends['periods'].insert(0, {
                    'period_number': num_periods - i,
                    'start': period_start.isoformat(),
                    'end': period_end.isoformat(),
                    'conversion_rate': analysis['summary']['overall_conversion_rate'],
                    'total_entered': analysis['summary']['total_entered'],
                    'total_completed': analysis['summary']['total_completed']
                })
            
            return trends
            
        except Exception as e:
            logger.error(f"Error getting funnel trends: {str(e)}")
            raise
    
    def list_funnels(self, funnel_type: Optional[str] = None) -> List[Dict]:
        """List all funnels with optional filtering"""
        query = {'status': 'active'}
        if funnel_type:
            query['type'] = funnel_type
        
        funnels = list(db.funnels.find(query).sort('created_at', -1))
        
        # Add summary data
        for funnel in funnels:
            funnel['_id'] = str(funnel['_id'])
            funnel['stage_count'] = len(funnel['stages'])
        
        return funnels
    
    def delete_funnel(self, funnel_id: str) -> bool:
        """Soft delete a funnel"""
        try:
            result = db.funnels.update_one(
                {'funnel_id': funnel_id},
                {'$set': {'status': 'deleted', 'deleted_at': datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error deleting funnel: {str(e)}")
            return False
    
    def create_default_funnels(self) -> List[str]:
        """Create default funnel templates"""
        created_funnels = []
        
        for funnel_type, stages in self.DEFAULT_FUNNELS.items():
            try:
                funnel_id = self.define_funnel(
                    funnel_name=funnel_type.replace('_', ' ').title(),
                    stages=stages,
                    funnel_type=funnel_type
                )
                created_funnels.append(funnel_id)
            except Exception as e:
                logger.error(f"Error creating default funnel {funnel_type}: {str(e)}")
        
        logger.info(f"Created {len(created_funnels)} default funnels")
        return created_funnels
    
    # Private helper methods
    
    def _identify_bottlenecks(self, stage_data: List[Dict]) -> List[Dict]:
        """Identify stages with poorest conversion"""
        bottlenecks = []
        
        for stage in stage_data:
            if stage['stage_number'] > 1:
                if stage['conversion_rate'] < 50:
                    bottlenecks.append({
                        'stage_name': stage['stage_name'],
                        'conversion_rate': stage['conversion_rate'],
                        'severity': 'high' if stage['conversion_rate'] < 25 else 'medium'
                    })
        
        return sorted(bottlenecks, key=lambda x: x['conversion_rate'])
    
    def _generate_recommendations(self, stage_data: List[Dict]) -> List[str]:
        """Generate improvement recommendations"""
        recommendations = []
        
        # Check overall performance
        if stage_data:
            first_stage = stage_data[0]
            last_stage = stage_data[-1]
            overall_conversion = last_stage['count'] / first_stage['count'] * 100 if first_stage['count'] > 0 else 0
            
            if overall_conversion < 5:
                recommendations.append("Overall conversion is very low. Review entire funnel strategy.")
            
            # Check for major drop-offs
            for stage in stage_data:
                if stage['stage_number'] > 1 and stage['drop_off'] > 50:
                    recommendations.append(
                        f"Focus on improving '{stage['stage_name']}' - {stage['drop_off']}% drop-off"
                    )
            
            # Check for stagnation
            mid_point = len(stage_data) // 2
            if stage_data[mid_point]['conversion_rate'] < 30:
                recommendations.append("Consider simplifying mid-funnel stages to improve flow")
        
        return recommendations if recommendations else ["Funnel performance is healthy"]
    
    def _classify_severity(self, drop_off: float) -> str:
        """Classify drop-off severity"""
        if drop_off >= 70:
            return 'critical'
        elif drop_off >= 50:
            return 'high'
        elif drop_off >= 30:
            return 'medium'
        else:
            return 'low'
    
    def _get_drop_off_suggestions(self, stage_name: str) -> List[str]:
        """Get suggestions for improving specific stage"""
        suggestions_map = {
            'Email Opened': [
                "Improve subject lines",
                "Test send times",
                "Verify email deliverability"
            ],
            'Link Clicked': [
                "Make CTAs more compelling",
                "Improve email content relevance",
                "Add urgency or scarcity"
            ],
            'Reply Received': [
                "Personalize emails more",
                "Ask engaging questions",
                "Provide clear value proposition"
            ],
            'Meeting Booked': [
                "Simplify scheduling process",
                "Offer more time slots",
                "Provide clear meeting value"
            ]
        }
        
        return suggestions_map.get(
            stage_name,
            ["Review stage criteria", "Analyze drop-off reasons", "A/B test improvements"]
        )


# Global instance
funnel_analyzer = FunnelAnalyzer()
