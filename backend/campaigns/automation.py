"""
CAMPAIGN AUTOMATION SCRIPT
==========================

Automated campaign creation and management for surveyfieldwork and cogentixresearch.
This script implements:
1. Service identification for both companies
2. Highly personalized outreach emails with appropriate signatures
3. Weekly follow-up sequences
4. Email status tracking (open, bounce, not opened)
5. Automatic bounce status updates
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from bson import ObjectId

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_client

from campaigns.models import (
    CampaignManager,
    CampaignStatus,
    RecipientStatus,
    SendStatus,
    SequenceCondition
)
from campaigns.services_config import get_company_config, list_all_services
from campaigns.email_templates import get_template_config, render_template, list_templates


class CampaignAutomation:
    """
    Main class for campaign automation operations.
    """
    
    def __init__(self, mongo_uri: str = None):
        """
        Initialize campaign automation.
        
        Args:
            mongo_uri: MongoDB connection string
        """
        mongo_uri = mongo_uri or os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        self.client = get_client()
        self.db = self.client['email_automation']
        self.campaign_manager = CampaignManager(self.db)
    
    def create_outreach_campaign(
        self,
        company: str,
        campaign_name: str,
        recipients: List[Dict[str, Any]],
        mailbox_id: str = None,
        start_immediately: bool = False
    ) -> str:
        """
        Create a complete outreach campaign with weekly follow-ups.
        
        Args:
            company: Company identifier ('surveyfieldwork' or 'cogentixresearch')
            campaign_name: Name for the campaign
            recipients: List of recipient dictionaries with email, first_name, company, etc.
            mailbox_id: Mailbox ID to send from (optional, will use default)
            start_immediately: Whether to start campaign immediately
        
        Returns:
            Campaign ID
        """
        # Get company configuration
        company_config = get_company_config(company)
        
        # Create templates if they don't exist
        template_ids = self._ensure_templates_exist(company)
        
        # Create sequence with weekly follow-ups
        sequence_steps = [
            {
                "template_id": template_ids["initial_outreach"],
                "delay_days": 0,
                "delay_hours": 0,
                "condition": "always"
            },
            {
                "template_id": template_ids["follow_up_week1"],
                "delay_days": 7,  # Week 1
                "delay_hours": 0,
                "condition": "no_reply"
            },
            {
                "template_id": template_ids["follow_up_week2"],
                "delay_days": 14,  # Week 2 (7 days after first follow-up)
                "delay_hours": 0,
                "condition": "no_reply"
            },
            {
                "template_id": template_ids["follow_up_week3"],
                "delay_days": 21,  # Week 3 (7 days after second follow-up)
                "delay_hours": 0,
                "condition": "no_reply"
            }
        ]
        
        # Create campaign
        campaign_id = self.campaign_manager.create_campaign(
            name=campaign_name,
            from_mailbox_id=mailbox_id or "default",
            from_email=company_config["sender_email"],
            from_name=company_config["sender_name"],
            description=f"Automated outreach campaign for {company_config['company_name']}",
            sequence_steps=sequence_steps,
            settings={
                "daily_send_limit": 100,
                "hourly_send_limit": 20,
                "track_opens": True,
                "track_clicks": True,
                "stop_on_any_reply": True,
                "include_unsubscribe_link": True
            }
        )
        
        # Add recipients
        self.campaign_manager.add_recipients(
            campaign_id=campaign_id,
            recipients=recipients,
            deduplicate=True
        )
        
        # Start campaign if requested
        if start_immediately:
            self.campaign_manager.update_campaign_status(
                campaign_id,
                CampaignStatus.ACTIVE
            )
        
        return campaign_id
    
    def _ensure_templates_exist(self, company: str) -> Dict[str, str]:
        """
        Ensure email templates exist in database, create if missing.
        
        Args:
            company: Company identifier
        
        Returns:
            Dictionary mapping template names to IDs
        """
        from campaigns.email_templates import get_template_config
        
        template_names = ["initial_outreach", "follow_up_week1", "follow_up_week2", "follow_up_week3"]
        template_ids = {}
        
        for template_name in template_names:
            # Get template config
            template_config = get_template_config(company, template_name)
            
            # Check if template exists by name
            existing = self.db.email_templates.find_one({
                "name": template_config["name"]
            })
            
            if existing:
                template_ids[template_name] = str(existing["_id"])
            else:
                # Create template
                template_id = self.campaign_manager.create_template(
                    name=template_config["name"],
                    subject=template_config["subject"],
                    body_html=template_config.get("body_html_with_signature", template_config["body_html"]),
                    category=template_config["category"],
                    tags=[company]
                )
                template_ids[template_name] = template_id
        
        return template_ids
    
    def process_email_tracking_updates(self, tracking_data: List[Dict[str, Any]]):
        """
        Process email tracking updates (opens, bounces, etc.).
        
        Args:
            tracking_data: List of tracking events with format:
                [
                    {
                        "email": "recipient@example.com",
                        "campaign_id": "...",
                        "event": "opened|bounced|clicked",
                        "timestamp": datetime,
                        "send_id": "..." (optional)
                    }
                ]
        """
        for event in tracking_data:
            email = event.get("email")
            campaign_id = event.get("campaign_id")
            event_type = event.get("event")
            timestamp = event.get("timestamp", datetime.utcnow())
            send_id = event.get("send_id")
            
            if not email or not campaign_id or not event_type:
                continue
            
            # Find recipient
            recipient = self.db.campaign_recipients.find_one({
                "campaign_id": campaign_id,
                "email": email
            })
            
            if not recipient:
                continue
            
            recipient_id = str(recipient["_id"])
            
            # Update based on event type
            if event_type == "bounced":
                # Update recipient status to BOUNCED
                self.campaign_manager.update_recipient_status(
                    recipient_id,
                    RecipientStatus.BOUNCED
                )
                
                # Update send status if send_id provided
                if send_id:
                    self.db.campaign_sends.update_one(
                        {"_id": ObjectId(send_id)},
                        {
                            "$set": {
                                "status": SendStatus.BOUNCED.value,
                                "bounced_at": timestamp
                            }
                        }
                    )
            
            elif event_type == "opened":
                # Update send status
                if send_id:
                    self.db.campaign_sends.update_one(
                        {"_id": ObjectId(send_id)},
                        {
                            "$set": {
                                "status": SendStatus.OPENED.value,
                                "opened_at": timestamp
                            },
                            "$inc": {"open_count": 1}
                        }
                    )
            
            elif event_type == "clicked":
                # Update send status
                if send_id:
                    self.db.campaign_sends.update_one(
                        {"_id": ObjectId(send_id)},
                        {
                            "$set": {
                                "status": SendStatus.CLICKED.value,
                                "clicked_at": timestamp
                            },
                            "$inc": {"click_count": 1}
                        }
                    )
    
    def get_campaign_status_report(self, campaign_id: str) -> Dict[str, Any]:
        """
        Generate detailed status report for a campaign including tracking metrics.
        
        Args:
            campaign_id: Campaign ID
        
        Returns:
            Comprehensive status report
        """
        campaign = self.campaign_manager.get_campaign(campaign_id)
        if not campaign:
            return {"error": "Campaign not found"}
        
        # Get recipient status breakdown
        recipients = list(self.db.campaign_recipients.find({"campaign_id": campaign_id}))
        
        status_breakdown = {
            "total": len(recipients),
            "pending": 0,
            "in_sequence": 0,
            "completed": 0,
            "replied": 0,
            "bounced": 0,
            "unsubscribed": 0,
            "interested": 0,
            "not_interested": 0
        }
        
        for recipient in recipients:
            status = recipient.get("status", "pending")
            if status in status_breakdown:
                status_breakdown[status] += 1
        
        # Get send status breakdown
        sends = list(self.db.campaign_sends.find({"campaign_id": campaign_id}))
        
        send_breakdown = {
            "total_sends": len(sends),
            "queued": 0,
            "sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "bounced": 0,
            "failed": 0,
            "not_opened": 0
        }
        
        for send in sends:
            status = send.get("status", "queued")
            if status in send_breakdown:
                send_breakdown[status] += 1
        
        # Calculate not opened (sent but not opened)
        send_breakdown["not_opened"] = (
            send_breakdown["sent"] + 
            send_breakdown["delivered"] - 
            send_breakdown["opened"] - 
            send_breakdown["clicked"]
        )
        
        # Calculate rates
        total_delivered = send_breakdown["delivered"] + send_breakdown["opened"] + send_breakdown["clicked"]
        
        rates = {
            "open_rate": round(send_breakdown["opened"] / total_delivered * 100, 2) if total_delivered > 0 else 0,
            "click_rate": round(send_breakdown["clicked"] / total_delivered * 100, 2) if total_delivered > 0 else 0,
            "bounce_rate": round(send_breakdown["bounced"] / send_breakdown["total_sends"] * 100, 2) if send_breakdown["total_sends"] > 0 else 0,
            "reply_rate": round(status_breakdown["replied"] / status_breakdown["total"] * 100, 2) if status_breakdown["total"] > 0 else 0
        }
        
        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name"),
            "status": campaign.get("status"),
            "created_at": campaign.get("created_at"),
            "started_at": campaign.get("started_at"),
            "recipient_status": status_breakdown,
            "send_status": send_breakdown,
            "rates": rates,
            "sequence_steps": len(campaign.get("sequence_steps", [])),
            "from_email": campaign.get("from_email")
        }
    
    def list_services(self) -> Dict[str, Any]:
        """
        List all services offered by both companies.
        
        Returns:
            Dictionary with services for both companies
        """
        return list_all_services()
    
    def get_service_details(self, company: str, service_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific service.
        
        Args:
            company: Company identifier
            service_id: Service identifier
        
        Returns:
            Service details
        """
        from campaigns.services_config import get_service_by_id
        return get_service_by_id(company, service_id)


# ============== CLI FUNCTIONS ==============

def create_sample_campaign(company: str = "surveyfieldwork"):
    """
    Create a sample campaign for testing.
    
    Args:
        company: Company to create campaign for
    """
    automation = CampaignAutomation()
    
    # Sample recipients
    recipients = [
        {
            "email": "john.doe@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "company": "Acme Corp",
            "title": "Research Director",
            "custom_variables": {
                "industry": "Technology"
            }
        },
        {
            "email": "jane.smith@example.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "company": "Global Insights Inc",
            "title": "VP of Research",
            "custom_variables": {
                "industry": "Market Research"
            }
        }
    ]
    
    campaign_id = automation.create_outreach_campaign(
        company=company,
        campaign_name=f"Q1 2024 Outreach - {company}",
        recipients=recipients,
        start_immediately=False
    )
    
    print(f"✅ Created sample campaign: {campaign_id}")
    print(f"   Company: {company}")
    print(f"   Recipients: {len(recipients)}")
    print(f"   Sequence: 4 steps (initial + 3 weekly follow-ups)")
    
    return campaign_id


def show_services():
    """Display all services for both companies."""
    automation = CampaignAutomation()
    services = automation.list_services()
    
    print("\n" + "="*80)
    print("SERVICES OFFERED")
    print("="*80)
    
    for company, service_list in services.items():
        print(f"\n{company.upper()}")
        print("-" * 80)
        for service in service_list:
            print(f"  • {service['name']}")
            print(f"    {service['description']}")
            print()


def show_campaign_report(campaign_id: str):
    """
    Display campaign status report.
    
    Args:
        campaign_id: Campaign ID
    """
    automation = CampaignAutomation()
    report = automation.get_campaign_status_report(campaign_id)
    
    print("\n" + "="*80)
    print(f"CAMPAIGN STATUS REPORT")
    print("="*80)
    print(f"Campaign: {report.get('campaign_name')}")
    print(f"Status: {report.get('status')}")
    print(f"From: {report.get('from_email')}")
    print(f"Created: {report.get('created_at')}")
    print()
    
    print("RECIPIENT STATUS:")
    print("-" * 80)
    for status, count in report.get('recipient_status', {}).items():
        print(f"  {status.ljust(20)}: {count}")
    print()
    
    print("SEND STATUS:")
    print("-" * 80)
    for status, count in report.get('send_status', {}).items():
        print(f"  {status.ljust(20)}: {count}")
    print()
    
    print("ENGAGEMENT RATES:")
    print("-" * 80)
    for rate, value in report.get('rates', {}).items():
        print(f"  {rate.ljust(20)}: {value}%")
    print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Campaign Automation CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # List services command
    subparsers.add_parser("list-services", help="List all services")
    
    # Create campaign command
    create_parser = subparsers.add_parser("create-campaign", help="Create sample campaign")
    create_parser.add_argument(
        "--company",
        choices=["surveyfieldwork", "cogentixresearch"],
        default="surveyfieldwork",
        help="Company to create campaign for"
    )
    
    # Show report command
    report_parser = subparsers.add_parser("report", help="Show campaign report")
    report_parser.add_argument("campaign_id", help="Campaign ID")
    
    args = parser.parse_args()
    
    if args.command == "list-services":
        show_services()
    elif args.command == "create-campaign":
        create_sample_campaign(args.company)
    elif args.command == "report":
        show_campaign_report(args.campaign_id)
    else:
        parser.print_help()
