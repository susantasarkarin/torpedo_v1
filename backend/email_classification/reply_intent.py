"""
REPLY INTENT CLASSIFIER
=======================

Advanced intent classification beyond sentiment for campaign replies.
Classifies specific intent types to enable targeted response strategies.

Intent Types:
- meeting_request: Wants to schedule meeting/call
- objection: Raised concern/objection (price, timing, etc)
- referral: Suggests another contact/department
- question: Asking specific question
- not_now: Interested but not ready (timing issue)
- competitor_mention: Mentions competitor/alternative
- wrong_person: Not the right contact

Features:
- GPT-4o-mini powered classification
- Few-shot learning examples
- Confidence scoring
- Suggested action recommendations
- Lead context awareness

Usage:
    classifier = ReplyIntentClassifier(api_key="sk-...")
    
    result = classifier.classify_intent(
        reply_text="We're currently using Salesforce for this.",
        lead_context={"name": "John", "company": "Acme"}
    )
    
    # Returns:
    # {
    #     "intent": "competitor_mention",
    #     "confidence": 0.92,
    #     "suggested_action": "send_comparison",
    #     "competitors_mentioned": ["Salesforce"],
    #     "explanation": "Lead mentioned existing solution"
    # }
"""

import os
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

try:
    import openai
except ImportError:
    openai = None

logger = logging.getLogger(__name__)


class ReplyIntent(str, Enum):
    """Reply intent classifications"""
    MEETING_REQUEST = "meeting_request"
    OBJECTION = "objection"
    REFERRAL = "referral"
    QUESTION = "question"
    NOT_NOW = "not_now"
    COMPETITOR_MENTION = "competitor_mention"
    WRONG_PERSON = "wrong_person"


class SuggestedAction(str, Enum):
    """Suggested follow-up actions"""
    SCHEDULE_CALL = "schedule_call"
    ADDRESS_OBJECTION = "address_objection"
    CONTACT_REFERRAL = "contact_referral"
    ANSWER_QUESTION = "answer_question"
    SCHEDULE_FOLLOWUP = "schedule_followup"
    SEND_COMPARISON = "send_comparison"
    UPDATE_CONTACT = "update_contact"


class ReplyIntentClassifier:
    """
    Classifies reply intent using GPT-4o-mini with few-shot examples.
    Goes beyond sentiment to identify specific intent types for targeted responses.
    """
    
    # Few-shot training examples
    FEW_SHOT_EXAMPLES = [
        {
            "reply": "Thanks for reaching out! I'd love to schedule a call to discuss this. What times work for you next week?",
            "intent": ReplyIntent.MEETING_REQUEST.value,
            "confidence": 0.98,
            "suggested_action": SuggestedAction.SCHEDULE_CALL.value,
            "explanation": "Explicit request to schedule a meeting with time availability inquiry"
        },
        {
            "reply": "This looks interesting but the pricing seems high for our budget right now.",
            "intent": ReplyIntent.OBJECTION.value,
            "confidence": 0.95,
            "suggested_action": SuggestedAction.ADDRESS_OBJECTION.value,
            "explanation": "Price objection identified - lead shows interest but concerned about cost"
        },
        {
            "reply": "I'm not the right person for this. You should reach out to our CTO, Sarah Johnson.",
            "intent": ReplyIntent.REFERRAL.value,
            "confidence": 0.97,
            "suggested_action": SuggestedAction.CONTACT_REFERRAL.value,
            "explanation": "Lead referred to another contact (CTO Sarah Johnson)"
        },
        {
            "reply": "How does your solution integrate with our existing CRM system?",
            "intent": ReplyIntent.QUESTION.value,
            "confidence": 0.96,
            "suggested_action": SuggestedAction.ANSWER_QUESTION.value,
            "explanation": "Technical question about integration capabilities"
        },
        {
            "reply": "This could be useful but we're in the middle of Q4 closing. Can we revisit in January?",
            "intent": ReplyIntent.NOT_NOW.value,
            "confidence": 0.94,
            "suggested_action": SuggestedAction.SCHEDULE_FOLLOWUP.value,
            "explanation": "Timing objection - interested but not ready now, specific follow-up date suggested"
        },
        {
            "reply": "We're currently using HubSpot and it's working well for us.",
            "intent": ReplyIntent.COMPETITOR_MENTION.value,
            "confidence": 0.93,
            "suggested_action": SuggestedAction.SEND_COMPARISON.value,
            "explanation": "Mentions competitor (HubSpot) - opportunity for comparison"
        },
        {
            "reply": "I'm no longer with the company. Please remove me from your list.",
            "intent": ReplyIntent.WRONG_PERSON.value,
            "confidence": 0.99,
            "suggested_action": SuggestedAction.UPDATE_CONTACT.value,
            "explanation": "Contact no longer at company - need to update records"
        }
    ]
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize the intent classifier.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use (default: gpt-4o-mini)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required (set OPENAI_API_KEY env var)")
        
        if openai is None:
            raise ImportError("openai package required: pip install openai")
        
        self.model = model
        self.client = openai.OpenAI(api_key=self.api_key)
        
        logger.info(f"ReplyIntentClassifier initialized with model: {model}")
    
    def _build_classification_prompt(self, reply_text: str, lead_context: Dict) -> str:
        """Build the prompt for intent classification."""
        
        # Format few-shot examples
        examples_text = "\n\n".join([
            f"Example {i+1}:\n"
            f"Reply: \"{ex['reply']}\"\n"
            f"Intent: {ex['intent']}\n"
            f"Confidence: {ex['confidence']}\n"
            f"Suggested Action: {ex['suggested_action']}\n"
            f"Explanation: {ex['explanation']}"
            for i, ex in enumerate(self.FEW_SHOT_EXAMPLES)
        ])
        
        # Format lead context
        context_text = ", ".join([
            f"{k}: {v}" for k, v in lead_context.items() 
            if v and k in ["name", "company", "title", "industry"]
        ])
        
        prompt = f"""You are an expert at analyzing sales email replies to determine the lead's intent.

Analyze the following reply and classify it into one of these intent types:

INTENT TYPES:
- meeting_request: Lead wants to schedule a meeting or call
- objection: Lead raised a concern or objection (price, timing, features, etc)
- referral: Lead suggests contacting another person/department
- question: Lead is asking a specific question
- not_now: Lead is interested but timing isn't right (defer to future)
- competitor_mention: Lead mentions they use a competitor or alternative
- wrong_person: Lead says they're not the right contact

SUGGESTED ACTIONS:
- schedule_call: Schedule a meeting/call
- address_objection: Respond to objection with tailored answer
- contact_referral: Reach out to referred contact
- answer_question: Provide detailed answer
- schedule_followup: Set reminder for future follow-up
- send_comparison: Send competitor comparison
- update_contact: Update contact information

FEW-SHOT EXAMPLES:
{examples_text}

NOW ANALYZE THIS REPLY:

Lead Context: {context_text}
Reply Text: "{reply_text}"

Respond with ONLY a valid JSON object in this exact format:
{{
    "intent": "<one of the intent types>",
    "confidence": <float between 0 and 1>,
    "suggested_action": "<one of the suggested actions>",
    "explanation": "<brief explanation of why this intent was chosen>",
    "secondary_intent": "<optional secondary intent if applicable>",
    "key_phrases": ["<key phrases that indicate this intent>"]
}}"""
        
        return prompt
    
    def classify_intent(
        self,
        reply_text: str,
        lead_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Classify the intent of a reply.
        
        Args:
            reply_text: The reply text to classify
            lead_context: Optional context about the lead (name, company, etc)
            
        Returns:
            Dict with intent classification results:
            {
                "intent": "meeting_request",
                "confidence": 0.95,
                "suggested_action": "schedule_call",
                "explanation": "...",
                "secondary_intent": "question",
                "key_phrases": ["schedule a call", "next week"],
                "timestamp": "2024-01-20T10:30:00",
                "model": "gpt-4o-mini"
            }
        """
        if not reply_text or not reply_text.strip():
            return {
                "intent": None,
                "confidence": 0.0,
                "suggested_action": None,
                "explanation": "Empty reply text",
                "error": "No content to classify"
            }
        
        lead_context = lead_context or {}
        
        try:
            prompt = self._build_classification_prompt(reply_text, lead_context)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at analyzing sales email replies. Always respond with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Lower temperature for more consistent classifications
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            
            # Add metadata
            result["timestamp"] = datetime.utcnow().isoformat()
            result["model"] = self.model
            result["reply_text"] = reply_text[:200]  # First 200 chars for reference
            
            logger.info(
                f"Classified reply intent: {result['intent']} "
                f"(confidence: {result['confidence']:.2f})"
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw response: {result_text}")
            return {
                "intent": None,
                "confidence": 0.0,
                "suggested_action": None,
                "explanation": "Failed to parse AI response",
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return {
                "intent": None,
                "confidence": 0.0,
                "suggested_action": None,
                "explanation": "Classification error",
                "error": str(e)
            }
    
    def classify_batch(
        self,
        replies: List[Dict[str, Any]],
        batch_size: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Classify multiple replies in batches.
        
        Args:
            replies: List of dicts with 'text' and optional 'lead_context'
            batch_size: Number of replies to process at once
            
        Returns:
            List of classification results
        """
        results = []
        
        for i in range(0, len(replies), batch_size):
            batch = replies[i:i+batch_size]
            
            for reply in batch:
                result = self.classify_intent(
                    reply_text=reply.get("text", ""),
                    lead_context=reply.get("lead_context", {})
                )
                result["reply_id"] = reply.get("id")
                results.append(result)
            
            logger.info(f"Processed batch {i//batch_size + 1}/{(len(replies) + batch_size - 1)//batch_size}")
        
        return results
    
    def get_intent_stats(self, classifications: List[Dict]) -> Dict[str, Any]:
        """
        Get statistics from a list of classifications.
        
        Args:
            classifications: List of classification results
            
        Returns:
            Dict with stats about intents, actions, confidence
        """
        if not classifications:
            return {"total": 0}
        
        intent_counts = {}
        action_counts = {}
        confidence_scores = []
        
        for c in classifications:
            intent = c.get("intent")
            if intent:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            
            action = c.get("suggested_action")
            if action:
                action_counts[action] = action_counts.get(action, 0) + 1
            
            conf = c.get("confidence")
            if conf:
                confidence_scores.append(conf)
        
        return {
            "total": len(classifications),
            "intent_counts": intent_counts,
            "action_counts": action_counts,
            "avg_confidence": sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0,
            "high_confidence_count": len([c for c in confidence_scores if c >= 0.8]),
            "low_confidence_count": len([c for c in confidence_scores if c < 0.6])
        }


# Convenience function
def classify_reply_intent(
    reply_text: str,
    lead_context: Optional[Dict] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to classify a single reply.
    
    Args:
        reply_text: The reply text
        lead_context: Optional lead context
        api_key: Optional OpenAI API key
        
    Returns:
        Classification result dict
    """
    classifier = ReplyIntentClassifier(api_key=api_key)
    return classifier.classify_intent(reply_text, lead_context)


if __name__ == "__main__":
    # Test the classifier
    logging.basicConfig(level=logging.INFO)
    
    test_replies = [
        {
            "text": "This looks great! Can we schedule a demo for next Tuesday?",
            "lead_context": {"name": "John Smith", "company": "Acme Corp"}
        },
        {
            "text": "We're already using Salesforce and happy with it.",
            "lead_context": {"name": "Jane Doe", "company": "Tech Inc"}
        },
        {
            "text": "The pricing is too high for our current budget.",
            "lead_context": {"name": "Bob Johnson", "company": "StartupXYZ"}
        }
    ]
    
    classifier = ReplyIntentClassifier()
    
    print("\n=== Reply Intent Classification Test ===\n")
    
    for i, reply in enumerate(test_replies):
        print(f"Test {i+1}:")
        print(f"Reply: {reply['text']}")
        result = classifier.classify_intent(reply['text'], reply['lead_context'])
        print(f"Intent: {result.get('intent')}")
        print(f"Confidence: {result.get('confidence'):.2f}")
        print(f"Action: {result.get('suggested_action')}")
        print(f"Explanation: {result.get('explanation')}")
        print()
