"""
AGENT 8 - INTEGRATION GUIDE
============================

Step-by-step guide to integrate Multi-Channel Executor and Reply Sentiment
Classifier into the existing campaign platform.
"""

# ============================================================================
# PART 1: INSTALLATION
# ============================================================================

# Step 1: Install required packages
pip install openai>=1.0.0

# Step 2: Set environment variables
export OPENAI_API_KEY=sk-your-openai-api-key-here
export APP_BASE_URL=https://your-app-domain.com  # Optional

# Step 3: Verify installation
python -c "import openai; from backend.email_classification import ReplySentimentClassifier"


# ============================================================================
# PART 2: BASIC INTEGRATION
# ============================================================================

# Option A: Standalone Usage (No changes to existing code)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# In your email ingestion/processing code:

from backend.email_classification import ReplySentimentClassifier
from pymongo import MongoClient

db = MongoClient("mongodb://...").campaign_db

# Initialize classifier once (at app startup)
classifier = ReplySentimentClassifier()

# When you detect a reply to a campaign email:
async def process_campaign_reply(email_doc):
    # Get recipient context
    recipient = db["campaign_recipients"].find_one({
        "email": email_doc["from_address"]["email"]
    })
    
    if recipient:
        # Classify the reply
        result = classifier.classify_reply(
            reply_text=email_doc.get("body_plain", ""),
            lead_context={
                "name": f"{recipient.get('first_name', '')} {recipient.get('last_name', '')}",
                "company": recipient.get("company"),
                "title": recipient.get("title"),
                "email": recipient["email"]
            }
        )
        
        # Update recipient with sentiment
        db["campaign_recipients"].update_one(
            {"_id": recipient["_id"]},
            {"$set": {
                "reply_sentiment": result["sentiment"],
                "reply_intent": result["intent"],
                "reply_confidence": result["confidence"],
                "reply_text": email_doc.get("body_plain", ""),
                "reply_classified_at": datetime.utcnow()
            }}
        )
        
        # Take action based on intent
        if result["intent"] == "opt_out":
            # Stop the sequence
            db["campaign_recipients"].update_one(
                {"_id": recipient["_id"]},
                {"$set": {"status": "unsubscribed"}}
            )
        elif result["intent"] == "meeting_request":
            # Escalate to sales
            send_notification_to_sales(recipient, email_doc)


# Option B: Integrated with Multi-Channel Executor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import asyncio
from backend.campaigns.multi_channel_executor import MultiChannelExecutor
from backend.linkedin.service import LinkedInAutomationService

# Initialize at app startup
linkedin_service = LinkedInAutomationService(db)
executor = MultiChannelExecutor(db, linkedin_service, email_send_func)

# In your campaign processing loop:
async def process_campaign_step(campaign, recipient, step):
    result = await executor.execute_step(step, recipient, campaign)
    
    if result["success"]:
        # Record in database
        send_record = {
            "campaign_id": str(campaign["_id"]),
            "recipient_id": str(recipient["_id"]),
            "channel": result["channel"],
            "status": "sent",
            "sent_at": datetime.utcnow(),
            "message_id": result.get("message_id"),
            "step_id": str(step.get("_id"))
        }
        db["campaign_sends"].insert_one(send_record)
    else:
        # Handle error
        logger.error(f"Failed to execute {result['channel']} step: {result['error']}")


# ============================================================================
# PART 3: UPDATING CAMPAIGN EXECUTOR
# ============================================================================

# File: backend/campaigns/executor.py

# At the top of the file, add imports:
from .multi_channel_executor import MultiChannelExecutor
from backend.email_classification import ReplySentimentClassifier

# In __init__, initialize new components:
class CampaignExecutor:
    def __init__(self, db, send_function=None, poll_interval=30):
        # ... existing init code ...
        
        # Add multi-channel support
        try:
            from backend.linkedin.service import LinkedInAutomationService
            self.linkedin_service = LinkedInAutomationService(db)
            self.multi_channel_executor = MultiChannelExecutor(
                db, self.linkedin_service, send_function
            )
        except Exception as e:
            logger.warning(f"LinkedIn service not available: {e}")
            self.multi_channel_executor = None
        
        # Add sentiment classifier
        try:
            self.sentiment_classifier = ReplySentimentClassifier()
        except Exception as e:
            logger.warning(f"Sentiment classifier not available: {e}")
            self.sentiment_classifier = None

# Update _process_send_queue to support multi-channel:
def _process_send_queue(self, campaign):
    """Process sends for a campaign"""
    campaign_id = str(campaign["_id"])
    
    # Get pending sends
    pending_sends = list(self.db["campaign_sends"].find({
        "campaign_id": campaign_id,
        "status": SendStatus.QUEUED.value,
        "scheduled_at": {"$lte": datetime.utcnow()}
    }).limit(20))
    
    for send in pending_sends:
        # Get step info
        step = self.db["campaign_sequences"].find_one({
            "_id": ObjectId(send.get("step_id"))
        })
        
        if not step:
            continue
        
        # Route based on channel
        channel = step.get("channel", "email")
        
        if channel == "linkedin" and self.multi_channel_executor:
            # Use multi-channel executor
            recipient = self.manager.get_recipient(send["recipient_id"])
            asyncio.run(
                self.multi_channel_executor.execute_step(
                    step, recipient, campaign
                )
            )
        else:
            # Use existing email send logic
            self._execute_send(send, campaign)

# Update _detect_replies to use sentiment classifier:
def _detect_replies(self):
    """Detect and classify replies to campaign emails"""
    # Get recently sent emails
    recent_sends = self.db["campaign_sends"].find({
        "status": {"$in": [SendStatus.SENT.value, SendStatus.DELIVERED.value]},
        "sent_at": {"$gte": datetime.utcnow() - timedelta(days=7)},
        "replied_at": {"$exists": False}
    }).limit(100)
    
    for send in recent_sends:
        self._check_for_reply(send)

def _check_for_reply(self, send):
    """Check if there's a reply to a specific send"""
    # ... existing code ...
    
    if reply:
        # Classify using AI if available
        if self.sentiment_classifier:
            recipient = self.manager.get_recipient(send["recipient_id"])
            
            result = self.sentiment_classifier.classify_reply(
                reply_text=reply.get("body_plain", ""),
                lead_context={
                    "name": f"{recipient.get('first_name', '')} {recipient.get('last_name', '')}",
                    "company": recipient.get("company"),
                    "email": recipient.get("email")
                }
            )
            
            # Update with sentiment
            self.db["campaign_recipients"].update_one(
                {"_id": ObjectId(send["recipient_id"])},
                {"$set": {
                    "reply_sentiment": result["sentiment"],
                    "reply_intent": result["intent"],
                    "reply_confidence": result["confidence"]
                }}
            )
        
        # Update send record
        self.db["campaign_sends"].update_one(
            {"_id": send["_id"]},
            {
                "$set": {
                    "status": SendStatus.REPLIED.value,
                    "replied_at": reply["timestamp"],
                    "reply_email_id": str(reply["_id"])
                }
            }
        )


# ============================================================================
# PART 4: CAMPAIGN CONFIGURATION
# ============================================================================

# Example campaign with multi-channel sequence:

campaign = {
    "name": "Product Launch - Multi-Channel",
    "from_mailbox_id": "company@example.com",
    "from_email": "company@example.com",
    "linkedin_session_id": "linkedin_account@example.com",  # NEW
    "settings": {
        "hourly_send_limit": 20,
        "min_delay_between_sends_seconds": 60,
        "include_unsubscribe_link": True,
        "linkedin_rate_limits": {  # NEW
            "connections_per_day": 100,
            "messages_per_day": 50
        }
    },
    "sequence": [
        {
            # Day 0: LinkedIn connection request
            "day": 0,
            "channel": "linkedin",
            "linkedin_action_type": "connection_request",
            "connection_note": "Hi {{first_name}}, I noticed your work in {{company}} and thought we should connect on LinkedIn."
        },
        {
            # Day 1: Email introduction
            "day": 1,
            "channel": "email",
            "template_id": "product_launch_intro"
        },
        {
            # Day 3: LinkedIn message (if connected)
            "day": 3,
            "channel": "linkedin",
            "linkedin_action_type": "message",
            "message_content": "Hi {{first_name}}, thanks for accepting my connection. I wanted to share something about {{company}}'s {{title}} role..."
        },
        {
            # Day 5: Follow-up email
            "day": 5,
            "channel": "email",
            "template_id": "follow_up_1",
            "condition": "no_reply"
        },
        {
            # Day 7: LinkedIn profile view
            "day": 7,
            "channel": "linkedin",
            "linkedin_action_type": "profile_view"
        }
    ]
}

# Create campaign
campaign_id = db["campaigns"].insert_one(campaign).inserted_id


# ============================================================================
# PART 5: RECIPIENT SETUP
# ============================================================================

# Recipients must include linkedin_url for LinkedIn actions:

recipient = {
    "campaign_id": str(campaign_id),
    "email": "john@company.com",
    "first_name": "John",
    "last_name": "Doe",
    "company": "Acme Corp",
    "title": "VP Sales",
    "linkedin_url": "https://linkedin.com/in/johndoe",  # NEW - Required for LinkedIn steps
    "status": "pending",
    "added_at": datetime.utcnow(),
    "custom_variables": {
        "department": "Sales",
        "product_interest": "Enterprise"
    }
}

db["campaign_recipients"].insert_one(recipient)


# ============================================================================
# PART 6: DATABASE INDEXES
# ============================================================================

# Add these indexes for performance:

def create_indexes(db):
    # linkedin_connections indexes
    db["linkedin_connections"].create_index("recipient_id")
    db["linkedin_connections"].create_index("campaign_id")
    db["linkedin_connections"].create_index([("status", 1), ("campaign_id", 1)])
    
    # linkedin_messages indexes
    db["linkedin_messages"].create_index("recipient_id")
    db["linkedin_messages"].create_index("campaign_id")
    db["linkedin_messages"].create_index("connection_id")
    
    # linkedin_activity indexes
    db["linkedin_activity"].create_index([("session_id", 1), ("date", 1)], unique=True)
    
    # campaign_recipients indexes
    db["campaign_recipients"].create_index("reply_sentiment")
    db["campaign_recipients"].create_index("reply_intent")
    
    # campaign_sends indexes
    db["campaign_sends"].create_index([("campaign_id", 1), ("channel", 1)])

# Call at startup
create_indexes(db)


# ============================================================================
# PART 7: SENTIMENT-BASED ROUTING
# ============================================================================

# Implement conditional routing based on reply sentiment:

async def handle_reply_sentiment(recipient_id, campaign_id, sentiment_result):
    """Route campaign based on reply sentiment"""
    
    recipient = db["campaign_recipients"].find_one({"_id": ObjectId(recipient_id)})
    campaign = db["campaigns"].find_one({"_id": ObjectId(campaign_id)})
    
    if sentiment_result["sentiment"] == "positive":
        if sentiment_result["intent"] == "meeting_request":
            # Send calendar link or mark for sales follow-up
            send_calendar_link(recipient, campaign)
            
            db["campaign_recipients"].update_one(
                {"_id": ObjectId(recipient_id)},
                {"$set": {"status": "qualified_meeting_request"}}
            )
        elif sentiment_result["intent"] == "more_info":
            # Send detailed information
            trigger_follow_up_sequence(recipient_id, campaign_id, "detailed_info")
    
    elif sentiment_result["sentiment"] == "negative":
        if sentiment_result["intent"] == "opt_out":
            # Stop campaign and mark as unsubscribed
            db["campaign_recipients"].update_one(
                {"_id": ObjectId(recipient_id)},
                {"$set": {"status": "unsubscribed", "unsubscribed_at": datetime.utcnow()}}
            )
            log_unsubscribe(recipient_id, "reply_indicates_opt_out")
        else:
            # Stop sequence but keep in database
            db["campaign_recipients"].update_one(
                {"_id": ObjectId(recipient_id)},
                {"$set": {"status": "not_interested"}}
            )
    
    elif sentiment_result["sentiment"] == "neutral":
        if sentiment_result["intent"] == "wrong_person":
            # Mark for manual review - wrong contact
            db["campaign_recipients"].update_one(
                {"_id": ObjectId(recipient_id)},
                {"$set": {"status": "wrong_contact", "notes": "Indicates wrong person"}}
            )
            notify_sales_wrong_contact(recipient)


# ============================================================================
# PART 8: MONITORING & REPORTING
# ============================================================================

def get_campaign_sentiment_report(campaign_id):
    """Generate sentiment report for a campaign"""
    
    classifier = ReplySentimentClassifier()
    summary = classifier.get_sentiment_summary(db, campaign_id)
    
    # Add additional metrics
    total_recipients = db["campaign_recipients"].count_documents({
        "campaign_id": campaign_id
    })
    
    recipients_with_replies = db["campaign_recipients"].count_documents({
        "campaign_id": campaign_id,
        "reply_sentiment": {"$exists": True}
    })
    
    reply_rate = (recipients_with_replies / total_recipients * 100) if total_recipients > 0 else 0
    
    return {
        "campaign_id": campaign_id,
        "total_recipients": total_recipients,
        "recipients_with_replies": recipients_with_replies,
        "reply_rate_percent": round(reply_rate, 1),
        "sentiment_distribution": summary.get("distribution", {}),
        "generated_at": datetime.utcnow()
    }


# ============================================================================
# PART 9: TESTING
# ============================================================================

async def test_multi_channel_executor():
    """Test multi-channel executor"""
    
    from backend.campaigns.multi_channel_executor import MultiChannelExecutor
    
    executor = MultiChannelExecutor(db, None, mock_email_send)  # None for linkedin_service to test email only
    
    # Test recipient
    recipient = {
        "_id": ObjectId(),
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
        "company": "Test Corp"
    }
    
    # Test campaign
    campaign = {
        "_id": ObjectId(),
        "from_email": "company@example.com",
        "settings": {"include_unsubscribe_link": True}
    }
    
    # Test email step
    email_step = {
        "_id": ObjectId(),
        "channel": "email",
        "template_id": "test_template"
    }
    
    result = await executor.execute_step(email_step, recipient, campaign)
    
    assert result["success"] is True
    assert result["channel"] == "email"
    print("✅ Email step test passed")


def test_sentiment_classifier():
    """Test sentiment classifier"""
    
    from backend.email_classification import ReplySentimentClassifier
    
    classifier = ReplySentimentClassifier()
    
    test_cases = [
        ("Thanks! I'd love to schedule a call.", "positive", "meeting_request"),
        ("Can you send more information?", "neutral", "more_info"),
        ("Not interested.", "negative", "not_interested"),
        ("Unsubscribe", "unsubscribe", "opt_out"),
    ]
    
    for reply, expected_sentiment, expected_intent in test_cases:
        result = classifier.classify_reply(reply)
        assert result["sentiment"] == expected_sentiment, f"Expected {expected_sentiment}, got {result['sentiment']}"
        assert result["intent"] == expected_intent, f"Expected {expected_intent}, got {result['intent']}"
        print(f"✅ {reply[:30]}... → {result['sentiment']} / {result['intent']}")


# ============================================================================
# PART 10: DEPLOYMENT CHECKLIST
# ============================================================================

deployment_checklist = """
Pre-Deployment:
  [ ] pip install openai>=1.0.0
  [ ] Set OPENAI_API_KEY environment variable
  [ ] Set APP_BASE_URL environment variable (optional)
  [ ] Review campaign configuration format
  [ ] Ensure recipients have linkedin_url field (for LinkedIn steps)
  [ ] Create database indexes

Code Integration:
  [ ] Add imports to executor
  [ ] Initialize MultiChannelExecutor and ReplySentimentClassifier
  [ ] Update _process_send_queue to route by channel
  [ ] Update _detect_replies to use sentiment classifier
  [ ] Update _check_for_reply to classify replies
  [ ] Implement sentiment-based routing logic

Database:
  [ ] Create new collections (linkedin_connections, etc.)
  [ ] Create indexes for performance
  [ ] Add new fields to campaign_recipients
  [ ] Add new fields to campaign_sends

Testing:
  [ ] Test email channel (without LinkedIn)
  [ ] Test LinkedIn connection request (with mock service)
  [ ] Test sentiment classifier with sample replies
  [ ] Test batch classification
  [ ] Test database updates
  [ ] Test rate limiting logic
  [ ] Run integration tests with real campaign

Monitoring:
  [ ] Set up logging for multi-channel executions
  [ ] Monitor OpenAI API usage and costs
  [ ] Monitor LinkedIn rate limiting
  [ ] Create sentiment dashboard
  [ ] Set up alerts for high opt-out rates

Documentation:
  [ ] Document new campaign configuration format
  [ ] Document sentiment enum values
  [ ] Document LinkedIn rate limits
  [ ] Document API key setup
  [ ] Update team on new features

Production:
  [ ] Gradual rollout (start with email-only campaigns)
  [ ] Monitor error rates
  [ ] Monitor API costs
  [ ] Collect user feedback
  [ ] Optimize based on metrics
  [ ] Enable LinkedIn steps
"""

print(deployment_checklist)

# ============================================================================
