"""
Campaign Autopilot Agent
Autonomous campaign optimization and management
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

class CampaignAutopilot:
    """
    Autonomous agent for campaign optimization
    Monitors performance and makes automatic adjustments
    """
    
    def __init__(self, db):
        self.db = db
        
        # Performance thresholds
        self.thresholds = {
            'min_open_rate': 0.15,      # 15% minimum open rate
            'min_reply_rate': 0.02,     # 2% minimum reply rate
            'max_bounce_rate': 0.05,    # 5% maximum bounce rate
            'max_unsubscribe_rate': 0.02,  # 2% max unsubscribe rate
            'min_engagement_score': 20.0
        }
        
        # Optimization strategies
        self.strategies = {
            'low_open_rate': ['improve_subject_lines', 'adjust_send_time', 'test_sender_name'],
            'low_reply_rate': ['enhance_personalization', 'adjust_cta', 'shorten_email'],
            'high_bounce_rate': ['verify_email_addresses', 'clean_list', 'check_domain_reputation'],
            'low_engagement': ['segment_audience', 'refresh_content', 'adjust_frequency']
        }
    
    async def auto_optimize_campaign(self, campaign_id: str) -> Dict:
        """
        Automatically optimize campaign based on performance
        
        Args:
            campaign_id: Campaign ID to optimize
            
        Returns:
            Optimization report with actions taken
        """
        # Fetch campaign data
        campaign = await self.db.campaigns.find_one({'_id': campaign_id})
        if not campaign:
            return {'error': 'Campaign not found'}
        
        # Analyze performance
        performance = await self._analyze_campaign_performance(campaign_id)
        
        # Identify issues
        issues = self._identify_issues(performance)
        
        # Generate improvements
        improvements = []
        actions_taken = []
        
        for issue in issues:
            suggestions = self._generate_improvements(issue, performance)
            improvements.extend(suggestions)
            
            # Auto-apply low-risk improvements
            auto_applied = await self._apply_safe_improvements(campaign_id, suggestions)
            actions_taken.extend(auto_applied)
        
        # Update campaign optimization log
        await self._log_optimization(campaign_id, {
            'timestamp': datetime.now(),
            'performance': performance,
            'issues_detected': issues,
            'improvements_suggested': improvements,
            'actions_taken': actions_taken
        })
        
        return {
            'campaign_id': campaign_id,
            'campaign_name': campaign.get('name', 'N/A'),
            'performance': performance,
            'issues_detected': issues,
            'improvements_suggested': improvements,
            'actions_taken': actions_taken,
            'optimized_at': datetime.now().isoformat()
        }
    
    async def _analyze_campaign_performance(self, campaign_id: str) -> Dict:
        """Analyze campaign performance metrics"""
        # Fetch campaign statistics
        stats = await self.db.campaign_stats.find_one({'campaign_id': campaign_id})
        
        if not stats:
            # Calculate from scratch
            leads = await self.db.leads.find({'campaign_id': campaign_id}).to_list(length=None)
            
            total_leads = len(leads)
            if total_leads == 0:
                return {'error': 'No leads in campaign'}
            
            emails_sent = sum(1 for l in leads if l.get('emails_sent', 0) > 0)
            opens = sum(l.get('email_opens', 0) for l in leads)
            clicks = sum(l.get('email_clicks', 0) for l in leads)
            replies = sum(l.get('previous_replies', 0) for l in leads)
            bounces = sum(1 for l in leads if l.get('bounced', False))
            unsubscribes = sum(1 for l in leads if l.get('unsubscribed', False))
            
            stats = {
                'total_leads': total_leads,
                'emails_sent': emails_sent,
                'opens': opens,
                'clicks': clicks,
                'replies': replies,
                'bounces': bounces,
                'unsubscribes': unsubscribes
            }
        
        # Calculate rates
        emails_sent = stats.get('emails_sent', 0)
        
        performance = {
            'total_leads': stats.get('total_leads', 0),
            'emails_sent': emails_sent,
            'open_rate': stats.get('opens', 0) / emails_sent if emails_sent > 0 else 0,
            'click_rate': stats.get('clicks', 0) / emails_sent if emails_sent > 0 else 0,
            'reply_rate': stats.get('replies', 0) / emails_sent if emails_sent > 0 else 0,
            'bounce_rate': stats.get('bounces', 0) / emails_sent if emails_sent > 0 else 0,
            'unsubscribe_rate': stats.get('unsubscribes', 0) / emails_sent if emails_sent > 0 else 0
        }
        
        # Calculate engagement score
        performance['engagement_score'] = (
            performance['open_rate'] * 20 +
            performance['click_rate'] * 30 +
            performance['reply_rate'] * 50
        )
        
        return performance
    
    def _identify_issues(self, performance: Dict) -> List[str]:
        """Identify performance issues"""
        issues = []
        
        if performance.get('open_rate', 0) < self.thresholds['min_open_rate']:
            issues.append('low_open_rate')
        
        if performance.get('reply_rate', 0) < self.thresholds['min_reply_rate']:
            issues.append('low_reply_rate')
        
        if performance.get('bounce_rate', 0) > self.thresholds['max_bounce_rate']:
            issues.append('high_bounce_rate')
        
        if performance.get('unsubscribe_rate', 0) > self.thresholds['max_unsubscribe_rate']:
            issues.append('high_unsubscribe_rate')
        
        if performance.get('engagement_score', 0) < self.thresholds['min_engagement_score']:
            issues.append('low_engagement')
        
        return issues
    
    def _generate_improvements(self, issue: str, performance: Dict) -> List[str]:
        """Generate improvement suggestions for issue"""
        suggestions = []
        
        if issue == 'low_open_rate':
            suggestions.extend([
                f"Current open rate: {performance['open_rate']:.1%} - Test A/B subject lines with emotional triggers",
                "Optimize send time based on lead timezone and industry",
                "Personalize sender name (use real person vs company name)",
                "Test shorter subject lines (under 50 characters)",
                "Add urgency or curiosity elements to subject"
            ])
        
        elif issue == 'low_reply_rate':
            suggestions.extend([
                f"Current reply rate: {performance['reply_rate']:.1%} - Increase personalization depth",
                "Make CTA more specific and easier to respond to",
                "Reduce email length by 30-40%",
                "Ask open-ended questions that require thought",
                "Test different value propositions"
            ])
        
        elif issue == 'high_bounce_rate':
            suggestions.extend([
                f"Current bounce rate: {performance['bounce_rate']:.1%} - Implement email verification before sending",
                "Remove role-based emails (info@, sales@, etc.)",
                "Verify domain MX records before sending",
                "Clean inactive emails from list"
            ])
        
        elif issue == 'high_unsubscribe_rate':
            suggestions.extend([
                f"Current unsubscribe rate: {performance['unsubscribe_rate']:.1%} - Reduce email frequency",
                "Improve targeting to reach more relevant prospects",
                "Review email content for spam triggers",
                "Add more value in each email"
            ])
        
        elif issue == 'low_engagement':
            suggestions.extend([
                f"Current engagement score: {performance['engagement_score']:.1f}/100 - Segment audience by behavior",
                "Refresh content with industry-specific insights",
                "Test different email formats (plain text vs HTML)",
                "Adjust follow-up timing based on engagement"
            ])
        
        return suggestions
    
    async def _apply_safe_improvements(self, campaign_id: str, suggestions: List[str]) -> List[str]:
        """Apply low-risk improvements automatically"""
        actions_taken = []
        
        # Auto-adjustments that are safe to apply
        campaign = await self.db.campaigns.find_one({'_id': campaign_id})
        
        # Adjust send time to optimal hours
        if any('send time' in s.lower() for s in suggestions):
            await self.db.campaigns.update_one(
                {'_id': campaign_id},
                {'$set': {'optimal_send_hour': 9}}  # 9 AM is generally best
            )
            actions_taken.append('Adjusted send time to 9 AM (optimal engagement window)')
        
        # Enable A/B testing if not already enabled
        if any('a/b' in s.lower() for s in suggestions):
            if not campaign.get('ab_testing_enabled'):
                await self.db.campaigns.update_one(
                    {'_id': campaign_id},
                    {'$set': {'ab_testing_enabled': True}}
                )
                actions_taken.append('Enabled A/B testing for subject lines')
        
        # Adjust email frequency for high unsubscribe rate
        if any('frequency' in s.lower() for s in suggestions):
            current_delay = campaign.get('follow_up_delay_days', 2)
            new_delay = min(current_delay + 1, 7)
            await self.db.campaigns.update_one(
                {'_id': campaign_id},
                {'$set': {'follow_up_delay_days': new_delay}}
            )
            actions_taken.append(f'Increased follow-up delay from {current_delay} to {new_delay} days')
        
        return actions_taken
    
    async def pause_underperformers(self, threshold: float = 0.05) -> List[Dict]:
        """
        Automatically pause underperforming campaigns
        
        Args:
            threshold: Minimum engagement score threshold (default 5%)
            
        Returns:
            List of paused campaigns
        """
        # Fetch active campaigns
        campaigns = await self.db.campaigns.find({
            'status': 'active',
            'emails_sent': {'$gte': 50}  # Only consider campaigns with sufficient data
        }).to_list(length=None)
        
        paused_campaigns = []
        
        for campaign in campaigns:
            campaign_id = str(campaign['_id'])
            performance = await self._analyze_campaign_performance(campaign_id)
            
            # Calculate combined engagement metric
            engagement = (
                performance.get('open_rate', 0) * 0.3 +
                performance.get('click_rate', 0) * 0.3 +
                performance.get('reply_rate', 0) * 0.4
            )
            
            # Pause if below threshold and bounce rate is high
            if engagement < threshold or performance.get('bounce_rate', 0) > 0.1:
                await self.db.campaigns.update_one(
                    {'_id': campaign['_id']},
                    {
                        '$set': {
                            'status': 'paused',
                            'auto_paused': True,
                            'pause_reason': f'Low engagement ({engagement:.2%}) or high bounce rate',
                            'paused_at': datetime.now()
                        }
                    }
                )
                
                paused_campaigns.append({
                    'campaign_id': campaign_id,
                    'campaign_name': campaign.get('name', 'N/A'),
                    'engagement': engagement,
                    'performance': performance,
                    'reason': 'Underperformance'
                })
        
        return paused_campaigns
    
    async def suggest_improvements(self, campaign_id: str) -> List[str]:
        """
        Generate improvement suggestions without applying them
        
        Args:
            campaign_id: Campaign ID
            
        Returns:
            List of improvement suggestions
        """
        # Analyze performance
        performance = await self._analyze_campaign_performance(campaign_id)
        
        # Identify issues
        issues = self._identify_issues(performance)
        
        # Generate all suggestions
        all_suggestions = []
        for issue in issues:
            suggestions = self._generate_improvements(issue, performance)
            all_suggestions.extend(suggestions)
        
        # Add best practices if no issues
        if not issues:
            all_suggestions.extend([
                "Campaign performing well! Consider:",
                "- Scale to similar audience segments",
                "- Document winning elements for future campaigns",
                "- Test advanced personalization techniques",
                "- Increase sending volume gradually"
            ])
        
        return all_suggestions
    
    async def _log_optimization(self, campaign_id: str, optimization_data: Dict):
        """Log optimization event"""
        await self.db.campaign_optimizations.insert_one({
            'campaign_id': campaign_id,
            'timestamp': datetime.now(),
            **optimization_data
        })
    
    async def get_optimization_history(self, campaign_id: str, days: int = 30) -> List[Dict]:
        """
        Get optimization history for campaign
        
        Args:
            campaign_id: Campaign ID
            days: Number of days to look back
            
        Returns:
            List of optimization events
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        optimizations = await self.db.campaign_optimizations.find({
            'campaign_id': campaign_id,
            'timestamp': {'$gte': cutoff_date}
        }).sort('timestamp', -1).to_list(length=None)
        
        return optimizations
    
    async def run_autopilot_cycle(self) -> Dict:
        """
        Run complete autopilot optimization cycle for all campaigns
        
        Returns:
            Summary of autopilot actions
        """
        print("Starting autopilot optimization cycle...")
        
        # Get active campaigns
        campaigns = await self.db.campaigns.find({
            'status': 'active',
            'emails_sent': {'$gte': 20}
        }).to_list(length=None)
        
        optimized = []
        paused = []
        errors = []
        
        for campaign in campaigns:
            campaign_id = str(campaign['_id'])
            
            try:
                # Optimize campaign
                result = await self.auto_optimize_campaign(campaign_id)
                optimized.append({
                    'campaign_id': campaign_id,
                    'name': campaign.get('name'),
                    'actions': len(result.get('actions_taken', []))
                })
                
                # Check if should be paused
                if result.get('performance', {}).get('engagement_score', 100) < 10:
                    await self.db.campaigns.update_one(
                        {'_id': campaign['_id']},
                        {'$set': {'status': 'paused', 'auto_paused': True}}
                    )
                    paused.append(campaign_id)
                
            except Exception as e:
                errors.append({
                    'campaign_id': campaign_id,
                    'error': str(e)
                })
        
        return {
            'cycle_completed_at': datetime.now().isoformat(),
            'campaigns_analyzed': len(campaigns),
            'campaigns_optimized': len(optimized),
            'campaigns_paused': len(paused),
            'errors': len(errors),
            'optimized_campaigns': optimized,
            'paused_campaigns': paused,
            'errors': errors
        }


class AutopilotService:
    """Service layer for campaign autopilot"""
    
    def __init__(self, db):
        self.db = db
        self.autopilot = CampaignAutopilot(db)
    
    async def enable_autopilot(self, campaign_id: str, settings: Dict = None) -> Dict:
        """Enable autopilot for campaign"""
        settings = settings or {}
        
        await self.db.campaigns.update_one(
            {'_id': campaign_id},
            {
                '$set': {
                    'autopilot_enabled': True,
                    'autopilot_settings': settings,
                    'autopilot_enabled_at': datetime.now()
                }
            }
        )
        
        return {
            'status': 'enabled',
            'campaign_id': campaign_id,
            'settings': settings
        }
    
    async def disable_autopilot(self, campaign_id: str) -> Dict:
        """Disable autopilot for campaign"""
        await self.db.campaigns.update_one(
            {'_id': campaign_id},
            {
                '$set': {
                    'autopilot_enabled': False,
                    'autopilot_disabled_at': datetime.now()
                }
            }
        )
        
        return {
            'status': 'disabled',
            'campaign_id': campaign_id
        }
    
    async def get_autopilot_status(self) -> Dict:
        """Get overall autopilot status"""
        enabled_count = await self.db.campaigns.count_documents({'autopilot_enabled': True})
        total_campaigns = await self.db.campaigns.count_documents({'status': 'active'})
        
        recent_optimizations = await self.db.campaign_optimizations.count_documents({
            'timestamp': {'$gte': datetime.now() - timedelta(days=7)}
        })
        
        return {
            'autopilot_enabled_campaigns': enabled_count,
            'total_active_campaigns': total_campaigns,
            'recent_optimizations': recent_optimizations,
            'coverage': f"{enabled_count}/{total_campaigns}" if total_campaigns > 0 else "0/0"
        }
