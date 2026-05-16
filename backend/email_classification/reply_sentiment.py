"""
REPLY SENTIMENT CLASSIFIER
===========================

AI-powered sentiment and intent analysis for campaign replies using GPT-4o-mini.

Features:
- Few-shot sentiment classification (positive | neutral | negative | unsubscribe)
- Intent detection (meeting_request, more_info, not_interested, wrong_person, opt_out)
- Confidence scores for each classification
- Integration with campaign recipient updates
- Batch processing support for efficiency
- Caching of classified replies

Sentiment Classes:
- positive: Shows genuine interest or positive engagement
- neutral: Generic response without clear intent
- negative: Negative or dismissive response
- unsubscribe: Explicit opt-out request

Intent Classes:
- meeting_request: Wants to schedule meeting/call
- more_info: Requesting additional information
- not_interested: Clearly not interested
- wrong_person: Contacted wrong person
- opt_out: Explicit unsubscribe/opt-out
- general_inquiry: General question or comment
- other: Unclear or mixed intent

Usage:
    classifier = ReplySentimentClassifier(api_key="sk-...")
    
    result = classifier.classify_reply(
        reply_text="Thanks! I'd love to schedule a call.",
        lead_context={"name": "John", "company": "Acme"}
    )
    
    # Result:
    # {
    #     "sentiment": "positive",
    #     "intent": "meeting_request",
    #     "confidence": 0.95,
    #     "explanation": "..."
    # }
"""

import os
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from enum import Enum

try:
    import openai
except ImportError:
    openai = None

logger = logging.getLogger(__name__)


class Sentiment(str, Enum):
    """Sentiment classifications"""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNSUBSCRIBE = "unsubscribe"


class Intent(str, Enum):
    """Intent classifications"""
    MEETING_REQUEST = "meeting_request"
    MORE_INFO = "more_info"
    NOT_INTERESTED = "not_interested"
    WRONG_PERSON = "wrong_person"
    OPT_OUT = "opt_out"
    GENERAL_INQUIRY = "general_inquiry"
    OTHER = "other"


class ReplySentimentClassifier:
    """
    Classifies reply sentiment and intent using GPT-4o-mini with few-shot examples.
    """
    
    # Few-shot training examples
    FEW_SHOT_EXAMPLES = [
        {
            "reply": "Thanks for reaching out! I'd love to schedule a call with you next week.",
            "sentiment": Sentiment.POSITIVE.value,
            "intent": Intent.MEETING_REQUEST.value,
            "explanation": "Enthusiastic response with explicit interest in meeting"
        },
        {
            "reply": "Can you send me more information about your pricing plans?",
            "sentiment": Sentiment.NEUTRAL.value,
            "intent": Intent.MORE_INFO.value,
            "explanation": "Polite request for additional details without clear commitment"
        },
        {
            "reply": "Not interested, please remove me from your list.",
            "sentiment": Sentiment.NEGATIVE.value,
            "intent": Intent.OPT_OUT.value,
            "explanation": "Clear opt-out request with rejection"
        },
        {
            "reply": "I think you have the wrong person. Contact John in sales instead.",
            "sentiment": Sentiment.NEUTRAL.value,
            "intent": Intent.WRONG_PERSON.value,
            "explanation": "Helpful redirect but indicates recipient is not the right target"
        },
        {
            "reply": "This looks interesting. Tell me more about how it works.",
            "sentiment": Sentiment.POSITIVE.value,
            "intent": Intent.MORE_INFO.value,
            "explanation": "Positive sentiment with request for more information"
        },
        {
            "reply": "Already have a similar solution in place. Thanks anyway.",
            "sentiment": Sentiment.NEGATIVE.value,
            "intent": Intent.NOT_INTERESTED.value,
            "explanation": "Not interested but polite - already using alternative"
        },
        {
            "reply": "What's your availability for a demo this week?",
            "sentiment": Sentiment.POSITIVE.value,
            "intent": Intent.MEETING_REQUEST.value,
            "explanation": "Direct meeting request showing engagement"
        },
        {
            "reply": "Unsubscribe",
            "sentiment": Sentiment.UNSUBSCRIBE.value,
            "intent": Intent.OPT_OUT.value,
            "explanation": "Direct unsubscribe request"
        },
        {
            "reply": "Interesting product. We're in evaluation mode for similar tools.",
            "sentiment": Sentiment.POSITIVE.value,
            "intent": Intent.GENERAL_INQUIRY.value,
            "explanation": "Positive engagement indicating they're evaluating solutions"
        },
        {
            "reply": "Our budget is frozen until Q3. Reach out then.",
            "sentiment": Sentiment.NEUTRAL.value,
            "intent": Intent.MORE_INFO.value,
            "explanation": "Not a rejection, but indicates timing constraint"
        }
    ]
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize the classifier.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o-mini for cost efficiency)
        """
        if openai is None:
            raise ImportError(
                "openai package required. Install with: pip install openai"
            )
        
        if api_key:
            self.api_key = api_key
        else:
            try:
                from leads.openai_rotator import get_pipeline_rotator
                _, self.api_key = get_pipeline_rotator("mail").get_available_key()
            except Exception:
                self.api_key = os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY or pass api_key parameter."
            )
        
        self.model = model
        self.client = openai.OpenAI(api_key=self.api_key)
        
        logger.info(f"ReplySentimentClassifier initialized (model: {model})")
    
    def classify_reply(
        self,
        reply_text: str,
        lead_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Classify a reply's sentiment and intent.
        
        Args:
            reply_text: The reply email text
            lead_context: Optional lead/context information
                         {
                         "name": "John Doe",
                         "company": "Acme Corp",
                         "title": "VP Sales",
                         "previous_emails": [...]
                         }
        
        Returns:
            Classification result:
            {
                "sentiment": "positive" | "neutral" | "negative" | "unsubscribe",
                "intent": "meeting_request" | "more_info" | "not_interested" | ...,
                "confidence": 0.95,  # 0.0 to 1.0
                "explanation": "Why this classification",
                "raw_response": {...}  # Full API response
            }
        """
        if not reply_text or not reply_text.strip():
            return {
                "sentiment": Sentiment.NEUTRAL.value,
                "intent": Intent.OTHER.value,
                "confidence": 0.0,
                "explanation": "Empty or whitespace-only reply",
                "error": "No reply text provided"
            }
        
        try:
            # Clean and truncate reply text
            reply_text = reply_text.strip()[:2000]
            
            # Build the prompt with few-shot examples
            prompt = self._build_prompt(reply_text, lead_context)
            
            # Call GPT-4o-mini
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Low temperature for consistent classification
                max_tokens=500,
                response_format={"type": "json_object"}  # Structured output
            )
            
            # Parse response
            content = response.choices[0].message.content
            result = json.loads(content)
            
            # Validate and normalize result
            classification = {
                "sentiment": result.get("sentiment", Sentiment.NEUTRAL.value),
                "intent": result.get("intent", Intent.OTHER.value),
                "confidence": float(result.get("confidence", 0.5)),
                "explanation": result.get("explanation", ""),
                "raw_response": result
            }
            
            # Ensure valid enum values
            if classification["sentiment"] not in [s.value for s in Sentiment]:
                classification["sentiment"] = Sentiment.NEUTRAL.value
            
            if classification["intent"] not in [i.value for i in Intent]:
                classification["intent"] = Intent.OTHER.value
            
            # Clamp confidence to 0-1
            classification["confidence"] = max(0.0, min(1.0, classification["confidence"]))
            
            logger.info(
                f"Classified reply: sentiment={classification['sentiment']}, "
                f"intent={classification['intent']}, "
                f"confidence={classification['confidence']}"
            )
            
            return classification
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return {
                "sentiment": Sentiment.NEUTRAL.value,
                "intent": Intent.OTHER.value,
                "confidence": 0.0,
                "explanation": "Failed to parse AI response",
                "error": str(e)
            }
        
        except Exception as e:
            logger.error(f"Classification error: {e}", exc_info=True)
            return {
                "sentiment": Sentiment.NEUTRAL.value,
                "intent": Intent.OTHER.value,
                "confidence": 0.0,
                "explanation": "Classification service error",
                "error": str(e)
            }
    
    def classify_batch(
        self,
        replies: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Classify multiple replies efficiently.
        
        Args:
            replies: List of {"text": "...", "context": {...}} dicts
        
        Returns:
            List of classification results
        """
        results = []
        for reply_data in replies:
            result = self.classify_reply(
                reply_text=reply_data.get("text", ""),
                lead_context=reply_data.get("context")
            )
            results.append(result)
        
        return results
    
    def update_lead_sentiment(
        self,
        db,
        lead_id: str,
        reply_text: str,
        lead_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Classify a reply and update the lead's reply_sentiment field.
        
        Args:
            db: MongoDB database instance
            lead_id: Lead/recipient ID
            reply_text: Reply text to classify
            lead_context: Optional context about the lead
        
        Returns:
            Updated lead document
        """
        from bson import ObjectId
        
        # Classify the reply
        classification = self.classify_reply(reply_text, lead_context)
        
        # Update lead document
        update_result = db["leads"].update_one(
            {"_id": ObjectId(lead_id)},
            {
                "$set": {
                    "reply_sentiment": classification["sentiment"],
                    "reply_intent": classification["intent"],
                    "reply_confidence": classification["confidence"],
                    "reply_explanation": classification["explanation"],
                    "reply_classified_at": datetime.utcnow(),
                    "reply_text": reply_text
                }
            }
        )
        
        if update_result.matched_count:
            logger.info(
                f"Updated lead {lead_id} with reply sentiment: {classification['sentiment']}"
            )
            
            # Return updated document
            return db["leads"].find_one({"_id": ObjectId(lead_id)})
        
        return None
    
    def update_campaign_recipient_sentiment(
        self,
        db,
        campaign_id: str,
        recipient_id: str,
        reply_text: str
    ) -> Dict[str, Any]:
        """
        Classify a campaign reply and update campaign_recipients.
        
        Args:
            db: MongoDB database instance
            campaign_id: Campaign ID
            recipient_id: Recipient ID
            reply_text: Reply text to classify
        
        Returns:
            Classification result
        """
        from bson import ObjectId
        
        # Get recipient context
        recipient = db["campaign_recipients"].find_one({
            "_id": ObjectId(recipient_id),
            "campaign_id": campaign_id
        })
        
        lead_context = {
            "name": f"{recipient.get('first_name', '')} {recipient.get('last_name', '')}".strip(),
            "company": recipient.get("company"),
            "title": recipient.get("title"),
            "email": recipient.get("email")
        } if recipient else None
        
        # Classify
        classification = self.classify_reply(reply_text, lead_context)
        
        # Update recipient
        if recipient:
            db["campaign_recipients"].update_one(
                {"_id": recipient["_id"]},
                {
                    "$set": {
                        "reply_sentiment": classification["sentiment"],
                        "reply_intent": classification["intent"],
                        "reply_confidence": classification["confidence"],
                        "reply_text": reply_text,
                        "reply_classified_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(
                f"Updated campaign recipient {recipient_id} with reply sentiment: "
                f"{classification['sentiment']}"
            )
        
        return classification
    
    def get_sentiment_summary(
        self,
        db,
        campaign_id: str
    ) -> Dict[str, Any]:
        """
        Get sentiment distribution for a campaign.
        
        Args:
            db: MongoDB database instance
            campaign_id: Campaign ID
        
        Returns:
            Summary with counts and percentages
        """
        pipeline = [
            {
                "$match": {
                    "campaign_id": campaign_id,
                    "reply_sentiment": {"$exists": True}
                }
            },
            {
                "$group": {
                    "_id": "$reply_sentiment",
                    "count": {"$sum": 1}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ]
        
        results = list(db["campaign_recipients"].aggregate(pipeline))
        
        total = sum(r["count"] for r in results)
        
        summary = {
            "campaign_id": campaign_id,
            "total_with_sentiment": total,
            "distribution": {}
        }
        
        for result in results:
            sentiment = result["_id"]
            count = result["count"]
            percentage = (count / total * 100) if total > 0 else 0
            
            summary["distribution"][sentiment] = {
                "count": count,
                "percentage": round(percentage, 1)
            }
        
        return summary
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for GPT."""
        return """You are an expert in analyzing email replies for sales outreach campaigns.
Your task is to classify reply emails into sentiment and intent categories.

SENTIMENT CATEGORIES:
- positive: Shows genuine interest, enthusiasm, or positive engagement
- neutral: Generic or non-committal response without clear interest
- negative: Dismissive, rejected, or clearly not interested
- unsubscribe: Explicit request to unsubscribe or opt-out

INTENT CATEGORIES:
- meeting_request: Wants to schedule a call, meeting, or demo
- more_info: Requesting additional information or details
- not_interested: Explicitly states they're not interested
- wrong_person: Indicates you reached the wrong person
- opt_out: Explicit unsubscribe or opt-out request
- general_inquiry: General question or comment
- other: Unclear or mixed intent

Respond with a JSON object containing:
{
  "sentiment": "positive|neutral|negative|unsubscribe",
  "intent": "meeting_request|more_info|not_interested|wrong_person|opt_out|general_inquiry|other",
  "confidence": 0.0-1.0,
  "explanation": "Brief explanation of your classification"
}"""
    
    def _build_prompt(
        self,
        reply_text: str,
        lead_context: Optional[Dict]
    ) -> str:
        """Build the classification prompt with few-shot examples."""
        
        # Add few-shot examples
        examples_section = "EXAMPLES:\n"
        for i, example in enumerate(self.FEW_SHOT_EXAMPLES, 1):
            examples_section += f"\nExample {i}:\n"
            examples_section += f'Reply: "{example["reply"]}"\n'
            examples_section += f"Sentiment: {example['sentiment']}\n"
            examples_section += f"Intent: {example['intent']}\n"
            examples_section += f"Explanation: {example['explanation']}\n"
        
        # Build context section
        context_section = ""
        if lead_context:
            context_section = "\nLEAD CONTEXT:\n"
            if lead_context.get("name"):
                context_section += f"Name: {lead_context['name']}\n"
            if lead_context.get("company"):
                context_section += f"Company: {lead_context['company']}\n"
            if lead_context.get("title"):
                context_section += f"Title: {lead_context['title']}\n"
            if lead_context.get("email"):
                context_section += f"Email: {lead_context['email']}\n"
        
        # Build final prompt
        prompt = f"""{examples_section}

{context_section}

TASK:
Classify the following reply email:

Reply: "{reply_text}"

Provide your classification in JSON format."""
        
        return prompt
