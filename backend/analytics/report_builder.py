"""
Report Builder - Custom Analytics Reports
Drag-drop metrics, custom filters, scheduled delivery, multi-format export
"""

from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timedelta
from bson import ObjectId
import pandas as pd
from database import db
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Build custom analytics reports with flexible metrics and filters"""
    
    AVAILABLE_METRICS = [
        'total_leads',
        'total_campaigns',
        'emails_sent',
        'opens',
        'clicks',
        'replies',
        'meetings_booked',
        'open_rate',
        'click_rate',
        'reply_rate',
        'meeting_rate',
        'bounce_rate',
        'unsubscribe_rate',
        'revenue_generated',
        'avg_deal_size',
        'conversion_rate',
        'roi',
        'cost_per_lead',
        'cost_per_meeting',
        'pipeline_value'
    ]
    
    AVAILABLE_FILTERS = [
        'campaign_type',
        'industry',
        'seniority',
        'lead_source',
        'campaign_id',
        'team_member',
        'lead_status',
        'email_status',
        'company_size',
        'location'
    ]
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        logger.info("ReportBuilder initialized with scheduler")
    
    def build_report(
        self,
        metrics: List[str],
        filters: Dict[str, Any],
        date_range: Tuple[datetime, datetime],
        group_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build custom report with selected metrics and filters
        
        Args:
            metrics: List of metric names to include
            filters: Dict of filter criteria
            date_range: (start_date, end_date) tuple
            group_by: Optional grouping field (day, week, month, campaign, etc.)
        
        Returns:
            Dict containing report data with KPIs, charts, and raw data
        """
        try:
            logger.info(f"Building report: metrics={metrics}, filters={filters}")
            
            # Validate inputs
            invalid_metrics = [m for m in metrics if m not in self.AVAILABLE_METRICS]
            if invalid_metrics:
                raise ValueError(f"Invalid metrics: {invalid_metrics}")
            
            start_date, end_date = date_range
            
            # Build MongoDB query from filters
            query = self._build_query(filters, start_date, end_date)
            
            # Calculate requested metrics
            kpis = {}
            chart_data = {}
            
            if 'total_leads' in metrics:
                kpis['total_leads'] = self._get_total_leads(query)
            
            if 'total_campaigns' in metrics:
                kpis['total_campaigns'] = self._get_total_campaigns(query)
            
            if 'emails_sent' in metrics:
                kpis['emails_sent'] = self._get_emails_sent(query)
            
            if any(m in metrics for m in ['opens', 'open_rate']):
                opens = self._get_opens(query)
                kpis['opens'] = opens
                if 'emails_sent' in kpis and kpis['emails_sent'] > 0:
                    kpis['open_rate'] = round(opens / kpis['emails_sent'] * 100, 2)
            
            if any(m in metrics for m in ['clicks', 'click_rate']):
                clicks = self._get_clicks(query)
                kpis['clicks'] = clicks
                if 'emails_sent' in kpis and kpis['emails_sent'] > 0:
                    kpis['click_rate'] = round(clicks / kpis['emails_sent'] * 100, 2)
            
            if any(m in metrics for m in ['replies', 'reply_rate']):
                replies = self._get_replies(query)
                kpis['replies'] = replies
                if 'emails_sent' in kpis and kpis['emails_sent'] > 0:
                    kpis['reply_rate'] = round(replies / kpis['emails_sent'] * 100, 2)
            
            if any(m in metrics for m in ['meetings_booked', 'meeting_rate']):
                meetings = self._get_meetings(query)
                kpis['meetings_booked'] = meetings
                if 'emails_sent' in kpis and kpis['emails_sent'] > 0:
                    kpis['meeting_rate'] = round(meetings / kpis['emails_sent'] * 100, 2)
            
            if 'bounce_rate' in metrics:
                bounces = self._get_bounces(query)
                if 'emails_sent' in kpis and kpis['emails_sent'] > 0:
                    kpis['bounce_rate'] = round(bounces / kpis['emails_sent'] * 100, 2)
            
            if 'unsubscribe_rate' in metrics:
                unsubs = self._get_unsubscribes(query)
                if 'emails_sent' in kpis and kpis['emails_sent'] > 0:
                    kpis['unsubscribe_rate'] = round(unsubs / kpis['emails_sent'] * 100, 2)
            
            if 'revenue_generated' in metrics:
                kpis['revenue_generated'] = self._get_revenue(query)
            
            if 'avg_deal_size' in metrics:
                kpis['avg_deal_size'] = self._get_avg_deal_size(query)
            
            if 'conversion_rate' in metrics:
                kpis['conversion_rate'] = self._get_conversion_rate(query)
            
            if 'roi' in metrics:
                kpis['roi'] = self._calculate_roi(query)
            
            if 'cost_per_lead' in metrics:
                kpis['cost_per_lead'] = self._get_cost_per_lead(query)
            
            if 'cost_per_meeting' in metrics:
                kpis['cost_per_meeting'] = self._get_cost_per_meeting(query)
            
            if 'pipeline_value' in metrics:
                kpis['pipeline_value'] = self._get_pipeline_value(query)
            
            # Generate time series data if group_by specified
            if group_by:
                chart_data = self._generate_time_series(metrics, query, start_date, end_date, group_by)
            
            # Build report structure
            report = {
                'report_id': str(ObjectId()),
                'title': self._generate_title(metrics, filters),
                'generated_at': datetime.utcnow().isoformat(),
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'days': (end_date - start_date).days
                },
                'filters': filters,
                'metrics': metrics,
                'kpis': kpis,
                'charts': chart_data,
                'summary': self._generate_summary(kpis, metrics)
            }
            
            # Save report to database
            db.reports.insert_one({
                **report,
                'created_at': datetime.utcnow()
            })
            
            logger.info(f"Report built successfully: {report['report_id']}")
            return report
            
        except Exception as e:
            logger.error(f"Error building report: {str(e)}")
            raise
    
    def schedule_report(
        self,
        report_config: Dict[str, Any],
        frequency: str,
        recipients: List[str],
        format: str = 'pdf'
    ) -> str:
        """
        Schedule recurring report delivery
        
        Args:
            report_config: Report configuration (metrics, filters, etc.)
            frequency: 'daily', 'weekly', 'monthly', 'quarterly'
            recipients: List of email addresses
            format: 'pdf', 'csv', or 'excel'
        
        Returns:
            Scheduled job ID
        """
        try:
            job_id = str(ObjectId())
            
            # Create cron trigger based on frequency
            triggers = {
                'daily': CronTrigger(hour=8, minute=0),
                'weekly': CronTrigger(day_of_week='mon', hour=8, minute=0),
                'monthly': CronTrigger(day=1, hour=8, minute=0),
                'quarterly': CronTrigger(month='1,4,7,10', day=1, hour=8, minute=0)
            }
            
            if frequency not in triggers:
                raise ValueError(f"Invalid frequency: {frequency}")
            
            # Schedule job
            self.scheduler.add_job(
                func=self._send_scheduled_report,
                trigger=triggers[frequency],
                args=[report_config, recipients, format],
                id=job_id,
                name=f"Scheduled Report - {report_config.get('title', 'Custom Report')}"
            )
            
            # Save schedule to database
            db.scheduled_reports.insert_one({
                'job_id': job_id,
                'report_config': report_config,
                'frequency': frequency,
                'recipients': recipients,
                'format': format,
                'created_at': datetime.utcnow(),
                'status': 'active'
            })
            
            logger.info(f"Report scheduled: {job_id} ({frequency})")
            return job_id
            
        except Exception as e:
            logger.error(f"Error scheduling report: {str(e)}")
            raise
    
    def export_report(self, report_id: str, format: str) -> bytes:
        """
        Export report to specified format
        
        Args:
            report_id: Report ID to export
            format: 'pdf', 'csv', or 'excel'
        
        Returns:
            Bytes of exported file
        """
        try:
            report = db.reports.find_one({'report_id': report_id})
            if not report:
                raise ValueError(f"Report not found: {report_id}")
            
            if format == 'pdf':
                from .export import export_pdf
                return export_pdf(report)
            elif format == 'csv':
                return self._export_csv(report)
            elif format == 'excel':
                from .export import export_excel
                return export_excel(report)
            else:
                raise ValueError(f"Invalid format: {format}")
                
        except Exception as e:
            logger.error(f"Error exporting report: {str(e)}")
            raise
    
    def get_scheduled_reports(self, user_id: Optional[str] = None) -> List[Dict]:
        """Get list of scheduled reports"""
        query = {'status': 'active'}
        if user_id:
            query['report_config.created_by'] = user_id
        
        return list(db.scheduled_reports.find(query))
    
    def cancel_scheduled_report(self, job_id: str) -> bool:
        """Cancel a scheduled report"""
        try:
            self.scheduler.remove_job(job_id)
            db.scheduled_reports.update_one(
                {'job_id': job_id},
                {'$set': {'status': 'cancelled', 'cancelled_at': datetime.utcnow()}}
            )
            logger.info(f"Scheduled report cancelled: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling report: {str(e)}")
            return False
    
    # Private helper methods
    
    def _build_query(self, filters: Dict, start_date: datetime, end_date: datetime) -> Dict:
        """Build MongoDB query from filters"""
        query = {
            'created_at': {'$gte': start_date, '$lte': end_date}
        }
        
        for key, value in filters.items():
            if key in self.AVAILABLE_FILTERS and value:
                if isinstance(value, list):
                    query[key] = {'$in': value}
                else:
                    query[key] = value
        
        return query
    
    def _get_total_leads(self, query: Dict) -> int:
        return db.leads.count_documents(query)
    
    def _get_total_campaigns(self, query: Dict) -> int:
        return db.campaigns.count_documents(query)
    
    def _get_emails_sent(self, query: Dict) -> int:
        return db.email_tracking.count_documents({**query, 'status': 'sent'})
    
    def _get_opens(self, query: Dict) -> int:
        return db.email_tracking.count_documents({**query, 'opened': True})
    
    def _get_clicks(self, query: Dict) -> int:
        return db.email_tracking.count_documents({**query, 'clicked': True})
    
    def _get_replies(self, query: Dict) -> int:
        return db.email_tracking.count_documents({**query, 'replied': True})
    
    def _get_meetings(self, query: Dict) -> int:
        return db.leads.count_documents({**query, 'meeting_booked': True})
    
    def _get_bounces(self, query: Dict) -> int:
        return db.email_tracking.count_documents({**query, 'bounced': True})
    
    def _get_unsubscribes(self, query: Dict) -> int:
        return db.leads.count_documents({**query, 'unsubscribed': True})
    
    def _get_revenue(self, query: Dict) -> float:
        pipeline = [
            {'$match': {**query, 'deal_closed': True}},
            {'$group': {'_id': None, 'total': {'$sum': '$deal_value'}}}
        ]
        result = list(db.leads.aggregate(pipeline))
        return result[0]['total'] if result else 0.0
    
    def _get_avg_deal_size(self, query: Dict) -> float:
        pipeline = [
            {'$match': {**query, 'deal_closed': True}},
            {'$group': {'_id': None, 'avg': {'$avg': '$deal_value'}}}
        ]
        result = list(db.leads.aggregate(pipeline))
        return round(result[0]['avg'], 2) if result else 0.0
    
    def _get_conversion_rate(self, query: Dict) -> float:
        total = db.leads.count_documents(query)
        converted = db.leads.count_documents({**query, 'deal_closed': True})
        return round(converted / total * 100, 2) if total > 0 else 0.0
    
    def _calculate_roi(self, query: Dict) -> float:
        revenue = self._get_revenue(query)
        # Assuming campaign cost stored in campaigns collection
        pipeline = [
            {'$match': query},
            {'$group': {'_id': None, 'cost': {'$sum': '$budget'}}}
        ]
        result = list(db.campaigns.aggregate(pipeline))
        cost = result[0]['cost'] if result else 1
        return round((revenue - cost) / cost * 100, 2) if cost > 0 else 0.0
    
    def _get_cost_per_lead(self, query: Dict) -> float:
        total_leads = self._get_total_leads(query)
        pipeline = [
            {'$match': query},
            {'$group': {'_id': None, 'cost': {'$sum': '$budget'}}}
        ]
        result = list(db.campaigns.aggregate(pipeline))
        total_cost = result[0]['cost'] if result else 0
        return round(total_cost / total_leads, 2) if total_leads > 0 else 0.0
    
    def _get_cost_per_meeting(self, query: Dict) -> float:
        meetings = self._get_meetings(query)
        pipeline = [
            {'$match': query},
            {'$group': {'_id': None, 'cost': {'$sum': '$budget'}}}
        ]
        result = list(db.campaigns.aggregate(pipeline))
        total_cost = result[0]['cost'] if result else 0
        return round(total_cost / meetings, 2) if meetings > 0 else 0.0
    
    def _get_pipeline_value(self, query: Dict) -> float:
        pipeline = [
            {'$match': {**query, 'in_pipeline': True}},
            {'$group': {'_id': None, 'total': {'$sum': '$deal_value'}}}
        ]
        result = list(db.leads.aggregate(pipeline))
        return result[0]['total'] if result else 0.0
    
    def _generate_time_series(
        self,
        metrics: List[str],
        query: Dict,
        start_date: datetime,
        end_date: datetime,
        group_by: str
    ) -> Dict[str, List]:
        """Generate time series data for charts"""
        # Group by day, week, or month
        date_format = {
            'day': '%Y-%m-%d',
            'week': '%Y-W%U',
            'month': '%Y-%m'
        }.get(group_by, '%Y-%m-%d')
        
        pipeline = [
            {'$match': query},
            {
                '$group': {
                    '_id': {'$dateToString': {'format': date_format, 'date': '$created_at'}},
                    'count': {'$sum': 1}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        # This is simplified - in production, you'd aggregate each metric separately
        result = list(db.email_tracking.aggregate(pipeline))
        
        return {
            'labels': [r['_id'] for r in result],
            'datasets': [
                {
                    'label': 'Activity',
                    'data': [r['count'] for r in result]
                }
            ]
        }
    
    def _generate_title(self, metrics: List[str], filters: Dict) -> str:
        """Generate report title from metrics and filters"""
        metric_str = ', '.join(metrics[:3])
        if len(metrics) > 3:
            metric_str += f' +{len(metrics) - 3} more'
        
        filter_str = ''
        if filters:
            filter_str = f" - Filtered by {', '.join(filters.keys())}"
        
        return f"Custom Report: {metric_str}{filter_str}"
    
    def _generate_summary(self, kpis: Dict, metrics: List[str]) -> str:
        """Generate text summary of key findings"""
        summary_parts = []
        
        if 'total_leads' in kpis:
            summary_parts.append(f"{kpis['total_leads']:,} total leads")
        
        if 'open_rate' in kpis:
            summary_parts.append(f"{kpis['open_rate']}% open rate")
        
        if 'reply_rate' in kpis:
            summary_parts.append(f"{kpis['reply_rate']}% reply rate")
        
        if 'meetings_booked' in kpis:
            summary_parts.append(f"{kpis['meetings_booked']} meetings booked")
        
        if 'revenue_generated' in kpis:
            summary_parts.append(f"${kpis['revenue_generated']:,.2f} revenue")
        
        return "Report shows: " + ", ".join(summary_parts)
    
    def _export_csv(self, report: Dict) -> bytes:
        """Export report as CSV"""
        df = pd.DataFrame([report['kpis']])
        return df.to_csv(index=False).encode('utf-8')
    
    def _send_scheduled_report(
        self,
        report_config: Dict,
        recipients: List[str],
        format: str
    ):
        """Send scheduled report (called by scheduler)"""
        try:
            # Build report with current date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30)  # Default to last 30 days
            
            report = self.build_report(
                metrics=report_config['metrics'],
                filters=report_config.get('filters', {}),
                date_range=(start_date, end_date)
            )
            
            # Export to specified format
            file_data = self.export_report(report['report_id'], format)
            
            # Send email (implement your email sending logic)
            from email_sender import send_email_with_attachment
            
            for recipient in recipients:
                send_email_with_attachment(
                    to=recipient,
                    subject=f"Scheduled Report: {report['title']}",
                    body=report['summary'],
                    attachment_data=file_data,
                    attachment_name=f"report_{report['report_id']}.{format}"
                )
            
            logger.info(f"Scheduled report sent to {len(recipients)} recipients")
            
        except Exception as e:
            logger.error(f"Error sending scheduled report: {str(e)}")


# Global instance
report_builder = ReportBuilder()
