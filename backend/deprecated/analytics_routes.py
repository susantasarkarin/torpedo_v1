"""
Analytics API Routes - Advanced Reporting and Analytics
"""

from flask import Blueprint, request, jsonify, send_file
from datetime import datetime, timedelta
from analytics.report_builder import report_builder
from analytics.cohort_analysis import cohort_analyzer
from analytics.funnel import funnel_analyzer
from analytics.export import export_pdf, export_excel
import logging

logger = logging.getLogger(__name__)

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


# ===== REPORT BUILDER ROUTES =====

@analytics_bp.route('/build-report', methods=['POST'])
def build_report():
    """Build custom report with selected metrics and filters"""
    try:
        data = request.json
        
        metrics = data.get('metrics', [])
        filters = data.get('filters', {})
        date_range_raw = data.get('date_range', [])
        group_by = data.get('group_by', None)
        
        # Parse date range
        date_range = (
            datetime.fromisoformat(date_range_raw[0].replace('Z', '+00:00')),
            datetime.fromisoformat(date_range_raw[1].replace('Z', '+00:00'))
        )
        
        report = report_builder.build_report(
            metrics=metrics,
            filters=filters,
            date_range=date_range,
            group_by=group_by
        )
        
        return jsonify(report), 200
        
    except Exception as e:
        logger.error(f"Error building report: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/schedule-report', methods=['POST'])
def schedule_report():
    """Schedule recurring report delivery"""
    try:
        data = request.json
        
        job_id = report_builder.schedule_report(
            report_config=data.get('report_config'),
            frequency=data.get('frequency'),
            recipients=data.get('recipients'),
            format=data.get('format', 'pdf')
        )
        
        return jsonify({'job_id': job_id, 'status': 'scheduled'}), 201
        
    except Exception as e:
        logger.error(f"Error scheduling report: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/export-report/<report_id>', methods=['GET'])
def export_report(report_id):
    """Export report to specified format"""
    try:
        format = request.args.get('format', 'pdf')
        
        file_data = report_builder.export_report(report_id, format)
        
        mimetype = {
            'pdf': 'application/pdf',
            'csv': 'text/csv',
            'excel': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }.get(format, 'application/octet-stream')
        
        return send_file(
            io.BytesIO(file_data),
            mimetype=mimetype,
            as_attachment=True,
            download_name=f'report_{report_id}.{format}'
        )
        
    except Exception as e:
        logger.error(f"Error exporting report: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/reports', methods=['GET'])
def get_reports():
    """Get list of all reports"""
    try:
        from database import db
        
        reports = list(db.reports.find().sort('created_at', -1).limit(50))
        
        # Convert ObjectId to string
        for report in reports:
            report['_id'] = str(report['_id'])
        
        return jsonify(reports), 200
        
    except Exception as e:
        logger.error(f"Error getting reports: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/scheduled-reports', methods=['GET'])
def get_scheduled_reports():
    """Get list of scheduled reports"""
    try:
        user_id = request.args.get('user_id')
        reports = report_builder.get_scheduled_reports(user_id)
        
        return jsonify(reports), 200
        
    except Exception as e:
        logger.error(f"Error getting scheduled reports: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/scheduled-reports/<job_id>', methods=['DELETE'])
def cancel_scheduled_report(job_id):
    """Cancel a scheduled report"""
    try:
        success = report_builder.cancel_scheduled_report(job_id)
        
        if success:
            return jsonify({'message': 'Report cancelled'}), 200
        else:
            return jsonify({'error': 'Failed to cancel report'}), 400
            
    except Exception as e:
        logger.error(f"Error cancelling report: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ===== COHORT ANALYSIS ROUTES =====

@analytics_bp.route('/cohorts', methods=['POST'])
def create_cohort():
    """Create new cohort"""
    try:
        data = request.json
        
        cohort_id = cohort_analyzer.create_cohort(
            cohort_name=data.get('name'),
            criteria=data.get('criteria'),
            cohort_type=data.get('type', 'custom')
        )
        
        return jsonify({'cohort_id': cohort_id}), 201
        
    except Exception as e:
        logger.error(f"Error creating cohort: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/cohorts', methods=['GET'])
def list_cohorts():
    """List all cohorts"""
    try:
        cohort_type = request.args.get('type')
        cohorts = cohort_analyzer.list_cohorts(cohort_type)
        
        return jsonify(cohorts), 200
        
    except Exception as e:
        logger.error(f"Error listing cohorts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/cohorts/<cohort_id>', methods=['GET'])
def get_cohort_performance(cohort_id):
    """Get cohort performance metrics"""
    try:
        performance = cohort_analyzer.get_cohort_performance(cohort_id)
        
        return jsonify(performance), 200
        
    except Exception as e:
        logger.error(f"Error getting cohort performance: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/cohorts/<cohort_id>', methods=['DELETE'])
def delete_cohort(cohort_id):
    """Delete cohort"""
    try:
        success = cohort_analyzer.delete_cohort(cohort_id)
        
        if success:
            return jsonify({'message': 'Cohort deleted'}), 200
        else:
            return jsonify({'error': 'Cohort not found'}), 404
            
    except Exception as e:
        logger.error(f"Error deleting cohort: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/cohorts/compare', methods=['POST'])
def compare_cohorts():
    """Compare multiple cohorts"""
    try:
        data = request.json
        cohort_ids = data.get('cohort_ids', [])
        
        comparison = cohort_analyzer.compare_cohorts(cohort_ids)
        
        return jsonify(comparison), 200
        
    except Exception as e:
        logger.error(f"Error comparing cohorts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/cohorts/<cohort_id>/retention', methods=['GET'])
def get_cohort_retention(cohort_id):
    """Get cohort retention rates over time"""
    try:
        period = request.args.get('period', 'week')
        num_periods = int(request.args.get('num_periods', 12))
        
        retention = cohort_analyzer.get_cohort_retention(
            cohort_id=cohort_id,
            period=period,
            num_periods=num_periods
        )
        
        return jsonify(retention), 200
        
    except Exception as e:
        logger.error(f"Error getting retention: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/cohorts/auto-create', methods=['POST'])
def auto_create_cohorts():
    """Auto-create cohorts by type"""
    try:
        data = request.json
        cohort_type = data.get('type')
        
        cohort_ids = cohort_analyzer.auto_create_cohorts(cohort_type)
        
        return jsonify({
            'created_count': len(cohort_ids),
            'cohort_ids': cohort_ids
        }), 201
        
    except Exception as e:
        logger.error(f"Error auto-creating cohorts: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ===== FUNNEL ANALYSIS ROUTES =====

@analytics_bp.route('/funnels', methods=['POST'])
def create_funnel():
    """Define new funnel"""
    try:
        data = request.json
        
        funnel_id = funnel_analyzer.define_funnel(
            funnel_name=data.get('name'),
            stages=data.get('stages'),
            conditions=data.get('conditions'),
            funnel_type=data.get('type', 'custom')
        )
        
        return jsonify({'funnel_id': funnel_id}), 201
        
    except Exception as e:
        logger.error(f"Error creating funnel: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels', methods=['GET'])
def list_funnels():
    """List all funnels"""
    try:
        funnel_type = request.args.get('type')
        funnels = funnel_analyzer.list_funnels(funnel_type)
        
        return jsonify(funnels), 200
        
    except Exception as e:
        logger.error(f"Error listing funnels: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels/<funnel_id>/analyze', methods=['POST'])
def analyze_funnel(funnel_id):
    """Analyze funnel performance"""
    try:
        data = request.json
        
        # Parse date range if provided
        date_range = None
        if 'date_range' in data:
            date_range = (
                datetime.fromisoformat(data['date_range'][0].replace('Z', '+00:00')),
                datetime.fromisoformat(data['date_range'][1].replace('Z', '+00:00'))
            )
        
        analysis = funnel_analyzer.analyze_funnel(
            funnel_id=funnel_id,
            date_range=date_range,
            filters=data.get('filters')
        )
        
        return jsonify(analysis), 200
        
    except Exception as e:
        logger.error(f"Error analyzing funnel: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels/<funnel_id>/drop-offs', methods=['GET'])
def get_drop_off_points(funnel_id):
    """Get funnel drop-off points"""
    try:
        threshold = float(request.args.get('threshold', 30.0))
        
        drop_offs = funnel_analyzer.get_drop_off_points(funnel_id, threshold)
        
        return jsonify(drop_offs), 200
        
    except Exception as e:
        logger.error(f"Error getting drop-offs: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels/<funnel_id>', methods=['DELETE'])
def delete_funnel(funnel_id):
    """Delete funnel"""
    try:
        success = funnel_analyzer.delete_funnel(funnel_id)
        
        if success:
            return jsonify({'message': 'Funnel deleted'}), 200
        else:
            return jsonify({'error': 'Funnel not found'}), 404
            
    except Exception as e:
        logger.error(f"Error deleting funnel: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels/compare', methods=['POST'])
def compare_funnels():
    """Compare multiple funnels"""
    try:
        data = request.json
        funnel_ids = data.get('funnel_ids', [])
        
        date_range = None
        if 'date_range' in data:
            date_range = (
                datetime.fromisoformat(data['date_range'][0].replace('Z', '+00:00')),
                datetime.fromisoformat(data['date_range'][1].replace('Z', '+00:00'))
            )
        
        comparison = funnel_analyzer.compare_funnels(funnel_ids, date_range)
        
        return jsonify(comparison), 200
        
    except Exception as e:
        logger.error(f"Error comparing funnels: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels/<funnel_id>/trends', methods=['GET'])
def get_funnel_trends(funnel_id):
    """Get funnel performance trends"""
    try:
        num_periods = int(request.args.get('num_periods', 12))
        period = request.args.get('period', 'week')
        
        trends = funnel_analyzer.get_funnel_trends(
            funnel_id=funnel_id,
            num_periods=num_periods,
            period=period
        )
        
        return jsonify(trends), 200
        
    except Exception as e:
        logger.error(f"Error getting trends: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/funnels/create-defaults', methods=['POST'])
def create_default_funnels():
    """Create default funnel templates"""
    try:
        funnel_ids = funnel_analyzer.create_default_funnels()
        
        return jsonify({
            'created_count': len(funnel_ids),
            'funnel_ids': funnel_ids
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating default funnels: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ===== EXECUTIVE DASHBOARD ROUTES =====

@analytics_bp.route('/executive-dashboard', methods=['GET'])
def get_executive_dashboard():
    """Get executive dashboard data"""
    try:
        from database import db
        
        days = int(request.args.get('days', 30))
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Calculate KPIs
        kpis = {}
        
        # Total leads
        kpis['total_leads'] = db.leads.count_documents({
            'created_at': {'$gte': start_date, '$lte': end_date}
        })
        
        # Email metrics
        emails_sent = db.email_tracking.count_documents({
            'created_at': {'$gte': start_date, '$lte': end_date}
        })
        opens = db.email_tracking.count_documents({
            'created_at': {'$gte': start_date, '$lte': end_date},
            'opened': True
        })
        replies = db.email_tracking.count_documents({
            'created_at': {'$gte': start_date, '$lte': end_date},
            'replied': True
        })
        
        kpis['open_rate'] = round(opens / emails_sent * 100, 2) if emails_sent > 0 else 0
        kpis['reply_rate'] = round(replies / emails_sent * 100, 2) if emails_sent > 0 else 0
        
        # Meetings
        kpis['meetings_booked'] = db.leads.count_documents({
            'meeting_booked': True,
            'meeting_booked_at': {'$gte': start_date, '$lte': end_date}
        })
        
        # Revenue
        revenue_pipeline = [
            {
                '$match': {
                    'deal_closed': True,
                    'deal_closed_at': {'$gte': start_date, '$lte': end_date}
                }
            },
            {'$group': {'_id': None, 'total': {'$sum': '$deal_value'}}}
        ]
        revenue_result = list(db.leads.aggregate(revenue_pipeline))
        kpis['revenue'] = revenue_result[0]['total'] if revenue_result else 0
        
        # Calculate trends (simplified)
        trends = []
        # You would calculate daily/weekly trends here
        
        # Top campaigns
        top_campaigns = []
        # You would aggregate campaign performance here
        
        # Goals
        goals = {
            'monthly_meetings': {
                'name': 'Monthly Meetings',
                'target': 100,
                'current': kpis['meetings_booked'],
                'expected_progress': 50
            },
            'revenue_target': {
                'name': 'Revenue Target',
                'target': 500000,
                'current': kpis['revenue'],
                'expected_progress': 50
            }
        }
        
        return jsonify({
            'kpis': kpis,
            'trends': trends,
            'top_campaigns': top_campaigns,
            'goals': goals
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard: {str(e)}")
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/export-dashboard', methods=['GET'])
def export_dashboard():
    """Export dashboard to PDF/Excel"""
    try:
        format = request.args.get('format', 'pdf')
        days = int(request.args.get('days', 30))
        
        # Build dashboard report
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        report_data = {
            'title': 'Executive Dashboard',
            'generated_at': datetime.utcnow().isoformat(),
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': days
            },
            'kpis': {}  # Would populate from dashboard query
        }
        
        if format == 'pdf':
            file_data = export_pdf(report_data)
        else:
            file_data = export_excel(report_data)
        
        mimetype = {
            'pdf': 'application/pdf',
            'excel': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }.get(format, 'application/octet-stream')
        
        import io
        return send_file(
            io.BytesIO(file_data),
            mimetype=mimetype,
            as_attachment=True,
            download_name=f'dashboard_{datetime.utcnow().date()}.{format}'
        )
        
    except Exception as e:
        logger.error(f"Error exporting dashboard: {str(e)}")
        return jsonify({'error': str(e)}), 500
