"""
Cohort Analysis - Track Lead Groups Over Time
Group leads by import date/source, track performance, compare cohorts
"""

from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from bson import ObjectId
from database import db
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class CohortAnalyzer:
    """Analyze lead cohorts and track performance over time"""
    
    COHORT_TYPES = [
        'import_date',
        'lead_source',
        'campaign_type',
        'industry',
        'seniority',
        'company_size',
        'location',
        'custom'
    ]
    
    def __init__(self):
        logger.info("CohortAnalyzer initialized")
    
    def create_cohort(
        self,
        cohort_name: str,
        criteria: Dict[str, Any],
        cohort_type: str = 'custom'
    ) -> str:
        """
        Create a new cohort based on criteria
        
        Args:
            cohort_name: Display name for cohort
            criteria: MongoDB query criteria for cohort members
            cohort_type: Type of cohort (import_date, lead_source, etc.)
        
        Returns:
            Cohort ID
        """
        try:
            if cohort_type not in self.COHORT_TYPES:
                raise ValueError(f"Invalid cohort type: {cohort_type}")
            
            # Count members matching criteria
            member_count = db.leads.count_documents(criteria)
            
            if member_count == 0:
                logger.warning(f"No leads match cohort criteria: {criteria}")
            
            # Create cohort document
            cohort = {
                'cohort_id': str(ObjectId()),
                'name': cohort_name,
                'type': cohort_type,
                'criteria': criteria,
                'member_count': member_count,
                'created_at': datetime.utcnow(),
                'status': 'active'
            }
            
            db.cohorts.insert_one(cohort)
            
            # Calculate initial metrics
            self._calculate_cohort_metrics(cohort['cohort_id'])
            
            logger.info(f"Cohort created: {cohort['cohort_id']} ({member_count} members)")
            return cohort['cohort_id']
            
        except Exception as e:
            logger.error(f"Error creating cohort: {str(e)}")
            raise
    
    def compare_cohorts(self, cohort_ids: List[str]) -> Dict[str, Any]:
        """
        Compare performance across multiple cohorts
        
        Args:
            cohort_ids: List of cohort IDs to compare
        
        Returns:
            Dict with comparison metrics and analysis
        """
        try:
            if len(cohort_ids) < 2:
                raise ValueError("Need at least 2 cohorts to compare")
            
            cohorts = []
            for cohort_id in cohort_ids:
                cohort = db.cohorts.find_one({'cohort_id': cohort_id})
                if not cohort:
                    raise ValueError(f"Cohort not found: {cohort_id}")
                cohorts.append(cohort)
            
            # Calculate metrics for each cohort
            comparison = {
                'cohorts': [],
                'comparison_date': datetime.utcnow().isoformat(),
                'metrics_compared': [
                    'member_count',
                    'emails_sent',
                    'open_rate',
                    'click_rate',
                    'reply_rate',
                    'meeting_rate',
                    'conversion_rate',
                    'avg_deal_size',
                    'revenue_per_lead'
                ]
            }
            
            for cohort in cohorts:
                metrics = self._get_cohort_metrics(cohort['cohort_id'])
                
                comparison['cohorts'].append({
                    'cohort_id': cohort['cohort_id'],
                    'name': cohort['name'],
                    'type': cohort['type'],
                    'member_count': cohort['member_count'],
                    'created_at': cohort['created_at'].isoformat(),
                    'metrics': metrics
                })
            
            # Add insights
            comparison['insights'] = self._generate_comparison_insights(comparison['cohorts'])
            
            # Save comparison
            db.cohort_comparisons.insert_one({
                **comparison,
                'created_at': datetime.utcnow()
            })
            
            logger.info(f"Compared {len(cohort_ids)} cohorts")
            return comparison
            
        except Exception as e:
            logger.error(f"Error comparing cohorts: {str(e)}")
            raise
    
    def get_cohort_retention(
        self,
        cohort_id: str,
        period: str = 'week',
        num_periods: int = 12
    ) -> Dict[str, Any]:
        """
        Calculate retention rates over time for a cohort
        
        Args:
            cohort_id: Cohort to analyze
            period: 'day', 'week', or 'month'
            num_periods: Number of periods to track
        
        Returns:
            Dict with retention data by period
        """
        try:
            cohort = db.cohorts.find_one({'cohort_id': cohort_id})
            if not cohort:
                raise ValueError(f"Cohort not found: {cohort_id}")
            
            # Get cohort creation date
            cohort_start = cohort['created_at']
            
            # Calculate period length
            period_delta = {
                'day': timedelta(days=1),
                'week': timedelta(weeks=1),
                'month': timedelta(days=30)
            }.get(period, timedelta(weeks=1))
            
            # Track activity by period
            retention_data = {
                'cohort_id': cohort_id,
                'cohort_name': cohort['name'],
                'cohort_start': cohort_start.isoformat(),
                'period_type': period,
                'initial_size': cohort['member_count'],
                'periods': []
            }
            
            # Get lead IDs in cohort
            lead_ids = [
                doc['_id'] 
                for doc in db.leads.find(cohort['criteria'], {'_id': 1})
            ]
            
            # Calculate retention for each period
            for period_num in range(num_periods):
                period_start = cohort_start + (period_delta * period_num)
                period_end = period_start + period_delta
                
                # Count active leads (those with email activity) in this period
                active_count = db.email_tracking.count_documents({
                    'lead_id': {'$in': [str(lid) for lid in lead_ids]},
                    'created_at': {'$gte': period_start, '$lt': period_end}
                })
                
                # Count engaged leads (opens, clicks, replies)
                engaged_count = db.email_tracking.count_documents({
                    'lead_id': {'$in': [str(lid) for lid in lead_ids]},
                    'created_at': {'$gte': period_start, '$lt': period_end},
                    '$or': [
                        {'opened': True},
                        {'clicked': True},
                        {'replied': True}
                    ]
                })
                
                # Count converted leads
                converted_count = db.leads.count_documents({
                    '_id': {'$in': lead_ids},
                    'deal_closed': True,
                    'deal_closed_at': {'$gte': period_start, '$lt': period_end}
                })
                
                retention_data['periods'].append({
                    'period_number': period_num,
                    'period_start': period_start.isoformat(),
                    'period_end': period_end.isoformat(),
                    'active_count': active_count,
                    'engaged_count': engaged_count,
                    'converted_count': converted_count,
                    'retention_rate': round(active_count / cohort['member_count'] * 100, 2) if cohort['member_count'] > 0 else 0,
                    'engagement_rate': round(engaged_count / cohort['member_count'] * 100, 2) if cohort['member_count'] > 0 else 0,
                    'conversion_rate': round(converted_count / cohort['member_count'] * 100, 2) if cohort['member_count'] > 0 else 0
                })
            
            # Calculate average retention
            retention_data['avg_retention_rate'] = round(
                sum(p['retention_rate'] for p in retention_data['periods']) / len(retention_data['periods']),
                2
            )
            
            logger.info(f"Retention calculated for cohort {cohort_id}")
            return retention_data
            
        except Exception as e:
            logger.error(f"Error calculating retention: {str(e)}")
            raise
    
    def get_cohort_performance(self, cohort_id: str) -> Dict[str, Any]:
        """Get detailed performance metrics for a cohort"""
        try:
            cohort = db.cohorts.find_one({'cohort_id': cohort_id})
            if not cohort:
                raise ValueError(f"Cohort not found: {cohort_id}")
            
            metrics = self._get_cohort_metrics(cohort_id)
            
            return {
                'cohort_id': cohort_id,
                'name': cohort['name'],
                'type': cohort['type'],
                'member_count': cohort['member_count'],
                'created_at': cohort['created_at'].isoformat(),
                'metrics': metrics,
                'performance_grade': self._calculate_performance_grade(metrics)
            }
            
        except Exception as e:
            logger.error(f"Error getting cohort performance: {str(e)}")
            raise
    
    def list_cohorts(
        self,
        cohort_type: Optional[str] = None,
        status: str = 'active'
    ) -> List[Dict]:
        """List all cohorts with optional filtering"""
        query = {'status': status}
        if cohort_type:
            query['type'] = cohort_type
        
        cohorts = list(db.cohorts.find(query).sort('created_at', -1))
        
        # Add summary metrics
        for cohort in cohorts:
            cohort['_id'] = str(cohort['_id'])
            metrics = self._get_cohort_metrics(cohort['cohort_id'])
            cohort['summary'] = {
                'open_rate': metrics.get('open_rate', 0),
                'reply_rate': metrics.get('reply_rate', 0),
                'conversion_rate': metrics.get('conversion_rate', 0)
            }
        
        return cohorts
    
    def delete_cohort(self, cohort_id: str) -> bool:
        """Soft delete a cohort"""
        try:
            result = db.cohorts.update_one(
                {'cohort_id': cohort_id},
                {'$set': {'status': 'deleted', 'deleted_at': datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error deleting cohort: {str(e)}")
            return False
    
    def auto_create_cohorts(self, cohort_type: str) -> List[str]:
        """
        Automatically create cohorts based on type
        E.g., create cohorts for each month's imports, each lead source, etc.
        """
        try:
            created_cohorts = []
            
            if cohort_type == 'import_date':
                # Create monthly cohorts
                pipeline = [
                    {
                        '$group': {
                            '_id': {
                                '$dateToString': {
                                    'format': '%Y-%m',
                                    'date': '$created_at'
                                }
                            },
                            'count': {'$sum': 1}
                        }
                    }
                ]
                
                months = list(db.leads.aggregate(pipeline))
                
                for month_data in months:
                    month = month_data['_id']
                    year, month_num = month.split('-')
                    
                    criteria = {
                        'created_at': {
                            '$gte': datetime(int(year), int(month_num), 1),
                            '$lt': datetime(int(year), int(month_num) + 1, 1) if int(month_num) < 12 else datetime(int(year) + 1, 1, 1)
                        }
                    }
                    
                    cohort_id = self.create_cohort(
                        cohort_name=f"Imports - {month}",
                        criteria=criteria,
                        cohort_type='import_date'
                    )
                    created_cohorts.append(cohort_id)
            
            elif cohort_type == 'lead_source':
                # Create cohorts by lead source
                sources = db.leads.distinct('source')
                
                for source in sources:
                    cohort_id = self.create_cohort(
                        cohort_name=f"Source: {source}",
                        criteria={'source': source},
                        cohort_type='lead_source'
                    )
                    created_cohorts.append(cohort_id)
            
            elif cohort_type == 'industry':
                # Create cohorts by industry
                industries = db.leads.distinct('industry')
                
                for industry in industries:
                    cohort_id = self.create_cohort(
                        cohort_name=f"Industry: {industry}",
                        criteria={'industry': industry},
                        cohort_type='industry'
                    )
                    created_cohorts.append(cohort_id)
            
            logger.info(f"Auto-created {len(created_cohorts)} cohorts of type {cohort_type}")
            return created_cohorts
            
        except Exception as e:
            logger.error(f"Error auto-creating cohorts: {str(e)}")
            raise
    
    # Private helper methods
    
    def _calculate_cohort_metrics(self, cohort_id: str):
        """Calculate and cache metrics for a cohort"""
        try:
            cohort = db.cohorts.find_one({'cohort_id': cohort_id})
            metrics = self._get_cohort_metrics(cohort_id)
            
            db.cohorts.update_one(
                {'cohort_id': cohort_id},
                {
                    '$set': {
                        'metrics': metrics,
                        'metrics_updated_at': datetime.utcnow()
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error calculating cohort metrics: {str(e)}")
    
    def _get_cohort_metrics(self, cohort_id: str) -> Dict[str, Any]:
        """Calculate performance metrics for a cohort"""
        cohort = db.cohorts.find_one({'cohort_id': cohort_id})
        criteria = cohort['criteria']
        
        # Get lead IDs in cohort
        lead_ids = [str(doc['_id']) for doc in db.leads.find(criteria, {'_id': 1})]
        
        # Calculate email metrics
        emails_sent = db.email_tracking.count_documents({'lead_id': {'$in': lead_ids}})
        opens = db.email_tracking.count_documents({'lead_id': {'$in': lead_ids}, 'opened': True})
        clicks = db.email_tracking.count_documents({'lead_id': {'$in': lead_ids}, 'clicked': True})
        replies = db.email_tracking.count_documents({'lead_id': {'$in': lead_ids}, 'replied': True})
        
        # Calculate conversion metrics
        meetings = db.leads.count_documents({**criteria, 'meeting_booked': True})
        deals_closed = db.leads.count_documents({**criteria, 'deal_closed': True})
        
        # Calculate revenue
        revenue_pipeline = [
            {'$match': {**criteria, 'deal_closed': True}},
            {'$group': {'_id': None, 'total': {'$sum': '$deal_value'}}}
        ]
        revenue_result = list(db.leads.aggregate(revenue_pipeline))
        total_revenue = revenue_result[0]['total'] if revenue_result else 0
        
        return {
            'emails_sent': emails_sent,
            'opens': opens,
            'clicks': clicks,
            'replies': replies,
            'meetings': meetings,
            'deals_closed': deals_closed,
            'total_revenue': total_revenue,
            'open_rate': round(opens / emails_sent * 100, 2) if emails_sent > 0 else 0,
            'click_rate': round(clicks / emails_sent * 100, 2) if emails_sent > 0 else 0,
            'reply_rate': round(replies / emails_sent * 100, 2) if emails_sent > 0 else 0,
            'meeting_rate': round(meetings / cohort['member_count'] * 100, 2) if cohort['member_count'] > 0 else 0,
            'conversion_rate': round(deals_closed / cohort['member_count'] * 100, 2) if cohort['member_count'] > 0 else 0,
            'avg_deal_size': round(total_revenue / deals_closed, 2) if deals_closed > 0 else 0,
            'revenue_per_lead': round(total_revenue / cohort['member_count'], 2) if cohort['member_count'] > 0 else 0
        }
    
    def _generate_comparison_insights(self, cohort_data: List[Dict]) -> List[str]:
        """Generate insights from cohort comparison"""
        insights = []
        
        # Find best performing cohort
        best_reply_rate = max(c['metrics']['reply_rate'] for c in cohort_data)
        best_reply_cohort = next(c for c in cohort_data if c['metrics']['reply_rate'] == best_reply_rate)
        insights.append(f"{best_reply_cohort['name']} has the highest reply rate at {best_reply_rate}%")
        
        # Find best revenue per lead
        best_rpl = max(c['metrics']['revenue_per_lead'] for c in cohort_data)
        best_rpl_cohort = next(c for c in cohort_data if c['metrics']['revenue_per_lead'] == best_rpl)
        insights.append(f"{best_rpl_cohort['name']} generates the most revenue per lead at ${best_rpl:.2f}")
        
        # Find largest cohort
        largest = max(cohort_data, key=lambda c: c['member_count'])
        insights.append(f"{largest['name']} is the largest cohort with {largest['member_count']} members")
        
        return insights
    
    def _calculate_performance_grade(self, metrics: Dict) -> str:
        """Calculate performance grade based on metrics"""
        score = 0
        
        # Open rate
        if metrics['open_rate'] >= 40:
            score += 25
        elif metrics['open_rate'] >= 25:
            score += 15
        elif metrics['open_rate'] >= 15:
            score += 10
        
        # Reply rate
        if metrics['reply_rate'] >= 5:
            score += 25
        elif metrics['reply_rate'] >= 3:
            score += 15
        elif metrics['reply_rate'] >= 1:
            score += 10
        
        # Meeting rate
        if metrics['meeting_rate'] >= 2:
            score += 25
        elif metrics['meeting_rate'] >= 1:
            score += 15
        elif metrics['meeting_rate'] >= 0.5:
            score += 10
        
        # Conversion rate
        if metrics['conversion_rate'] >= 1:
            score += 25
        elif metrics['conversion_rate'] >= 0.5:
            score += 15
        elif metrics['conversion_rate'] >= 0.1:
            score += 10
        
        # Grade based on score
        if score >= 85:
            return 'A'
        elif score >= 70:
            return 'B'
        elif score >= 55:
            return 'C'
        elif score >= 40:
            return 'D'
        else:
            return 'F'


# Global instance
cohort_analyzer = CohortAnalyzer()
