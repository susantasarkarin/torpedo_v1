"""
AUTO RESPONSE DRAFTING
======================

Automated response drafting system for campaign replies.
Analyzes reply content and generates contextual responses.

Features:
- Content analysis and intent understanding
- Integration with OutreachComposerAgent
- Context-aware response generation
- Multiple response options
- Suggested action recommendations

Usage:
    drafter = AutoResponseDrafter()
    
    result = drafter.draft_response(
        reply="Thanks for reaching out! I'd like to learn more.",
        lead={"name": "John", "company": "Acme"},
        campaign={"value_proposition": "AI-powered sales automation"}
    )
    
    # Returns:
    # {
    #     "response": "Hi John, great to hear...",
    #     "suggested_action": "send_now",
    #     "confidence": 0.92,
    #     "alternatives": [...]
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

# Import our other classification systems
from ..email_classification.reply_intent import ReplyIntentClassifier
from ..agents.objection_handler_agent import ObjectionHandlerAgent

logger = logging.getLogger(__name__)


class ResponseAction(str, Enum):
    """Suggested actions for responses"""
    SEND_NOW = "send_now"
    REVIEW_FIRST = "review_first"
    SCHEDULE_CALL = "schedule_call"
    SEND_INFO = "send_info"
    DEFER = "defer"
    UPDATE_CONTACT = "update_contact"


class ResponseTone(str, Enum):
    """Response tone options"""
    ENTHUSIASTIC = "enthusiastic"
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    FORMAL = "formal"


class AutoResponseDrafter:
    """
    Automatically draft contextual responses to campaign replies.
    
    Integrates with:
    - ReplyIntentClassifier for intent detection
    - ObjectionHandlerAgent for objection handling
    - OutreachComposerAgent patterns for response generation
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        default_tone: ResponseTone = ResponseTone.PROFESSIONAL
    ):
        """
        Initialize the auto response drafter.
        
        Args:
            api_key: OpenAI API key
            model: Model to use for generation
            default_tone: Default response tone
        """
        if api_key:
            self.api_key = api_key
        else:
            try:
                from leads.openai_rotator import get_pipeline_rotator
                _, self.api_key = get_pipeline_rotator("mail").get_available_key()
            except Exception:
                self.api_key = os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OpenAI API key required")
        
        if openai is None:
            raise ImportError("openai package required")
        
        self.model = model
        self.default_tone = default_tone
        self.client = openai.OpenAI(api_key=self.api_key)
        
        # Initialize sub-systems
        self.intent_classifier = ReplyIntentClassifier(api_key=self.api_key, model=model)
        self.objection_handler = ObjectionHandlerAgent()
        
        logger.info(f"AutoResponseDrafter initialized with model: {model}")
    
    def draft_response(
        self,
        reply: str,
        lead: Dict[str, Any],
        campaign: Dict[str, Any],
        tone: Optional[ResponseTone] = None,
        include_alternatives: bool = True
    ) -> Dict[str, Any]:
        """
        Draft a contextual response to a reply.
        
        Args:
            reply: The reply text to respond to
            lead: Lead information
            campaign: Campaign context
            tone: Response tone (defaults to default_tone)
            include_alternatives: Generate alternative responses
            
        Returns:
            Dict with response draft:
            {
                "response": "Hi John...",
                "suggested_action": "send_now",
                "confidence": 0.92,
                "alternatives": [...],
                "metadata": {...}
            }
        """
        if not reply or not reply.strip():
            return {
                "response": None,
                "suggested_action": None,
                "confidence": 0.0,
                "error": "Empty reply text"
            }
        
        tone = tone or self.default_tone
        
        try:
            # Step 1: Classify intent
            intent_result = self.intent_classifier.classify_intent(reply, lead)
            intent = intent_result.get("intent")
            
            logger.info(f"Reply intent: {intent} (confidence: {intent_result.get('confidence', 0):.2f})")
            
            # Step 2: Check for objections
            objection_result = None
            if intent == "objection":
                objection_result = self.objection_handler.detect_objection(reply)
                logger.info(f"Objection detected: {objection_result.get('objection_type')}")
            
            # Step 3: Generate response based on intent
            response_data = self._generate_response(
                reply=reply,
                lead=lead,
                campaign=campaign,
                intent=intent,
                intent_result=intent_result,
                objection_result=objection_result,
                tone=tone
            )
            
            # Step 4: Generate alternatives if requested
            alternatives = []
            if include_alternatives and response_data.get("response"):
                alternatives = self._generate_alternatives(
                    reply, lead, campaign, intent, tone
                )
            
            # Step 5: Determine suggested action
            suggested_action = self._determine_action(intent, intent_result, objection_result)
            
            return {
                "response": response_data.get("response"),
                "subject": response_data.get("subject"),
                "suggested_action": suggested_action,
                "confidence": response_data.get("confidence", 0.8),
                "alternatives": alternatives,
                "metadata": {
                    "intent": intent,
                    "intent_confidence": intent_result.get("confidence"),
                    "objection_type": objection_result.get("objection_type") if objection_result else None,
                    "tone": tone,
                    "timestamp": datetime.utcnow().isoformat(),
                    "model": self.model
                }
            }
            
        except Exception as e:
            logger.error(f"Response drafting failed: {e}")
            return {
                "response": None,
                "suggested_action": None,
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _generate_response(
        self,
        reply: str,
        lead: Dict[str, Any],
        campaign: Dict[str, Any],
        intent: str,
        intent_result: Dict,
        objection_result: Optional[Dict],
        tone: ResponseTone
    ) -> Dict[str, Any]:
        """Generate the main response."""
        
        # For objections, use objection handler
        if intent == "objection" and objection_result:
            objection_response = self.objection_handler.generate_objection_response(
                objection_result, lead, campaign
            )
            if objection_response:
                try:
                    resp_data = json.loads(objection_response) if isinstance(objection_response, str) and objection_response.startswith("{") else {"response": objection_response}
                    return {
                        "response": resp_data.get("response", objection_response),
                        "confidence": 0.85
                    }
                except:
                    return {"response": objection_response, "confidence": 0.85}
        
        # Otherwise, generate custom response
        prompt = self._build_response_prompt(reply, lead, campaign, intent, tone)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert sales professional writing personalized email responses."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=600
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        
        result = json.loads(result_text.strip())
        
        return result
    
    def _build_response_prompt(
        self,
        reply: str,
        lead: Dict[str, Any],
        campaign: Dict[str, Any],
        intent: str,
        tone: ResponseTone
    ) -> str:
        """Build prompt for response generation."""
        
        lead_name = lead.get("name", "there")
        company = lead.get("company", "your company")
        value_prop = campaign.get("value_proposition", "our solution")
        
        tone_guidelines = {
            ResponseTone.ENTHUSIASTIC: "enthusiastic and energetic, showing excitement",
            ResponseTone.PROFESSIONAL: "professional and polished, business-appropriate",
            ResponseTone.FRIENDLY: "warm and friendly, conversational but professional",
            ResponseTone.FORMAL: "formal and respectful, suitable for executives"
        }
        
        tone_desc = tone_guidelines.get(tone, tone_guidelines[ResponseTone.PROFESSIONAL])
        
        # Intent-specific guidelines
        intent_guidelines = {
            "meeting_request": "Confirm interest, suggest specific times, keep it simple",
            "question": "Answer thoroughly but concisely, offer to elaborate",
            "referral": "Thank them, ask for introduction details",
            "not_now": "Acknowledge timing, suggest future follow-up",
            "competitor_mention": "Ask about gaps/pain points, offer comparison",
            "wrong_person": "Thank them, request correct contact info"
        }
        
        intent_guide = intent_guidelines.get(intent, "Respond appropriately to their message")
        
        return f"""Write a personalized email response to this reply.

ORIGINAL REPLY: "{reply}"

LEAD INFO:
Name: {lead_name}
Company: {company}
Title: {lead.get('title', 'N/A')}

CAMPAIGN VALUE PROPOSITION: {value_prop}

REPLY INTENT: {intent}
INTENT GUIDELINE: {intent_guide}

TONE: {tone_desc}

RESPONSE REQUIREMENTS:
1. Reference their specific message/concern
2. Keep it under 120 words
3. Use their name naturally
4. Provide value or insight
5. Include clear next step
6. Match the requested tone
7. Be genuine and helpful, not pushy

Respond with ONLY valid JSON:
{{
    "response": "<the full email response text>",
    "subject": "<optional subject line if needed>",
    "confidence": <float 0-1 indicating quality>
}}"""
    
    def _generate_alternatives(
        self,
        reply: str,
        lead: Dict[str, Any],
        campaign: Dict[str, Any],
        intent: str,
        tone: ResponseTone
    ) -> List[Dict[str, Any]]:
        """Generate alternative response options."""
        
        try:
            # Generate 2 alternative responses with different approaches
            alternatives = []
            
            # Alternative 1: More direct
            alt1_prompt = self._build_response_prompt(
                reply, lead, campaign, intent, tone
            ) + "\n\nMake this response MORE DIRECT and action-oriented."
            
            resp1 = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": alt1_prompt}],
                temperature=0.8,
                max_tokens=400
            )
            
            # Alternative 2: More consultative
            alt2_prompt = self._build_response_prompt(
                reply, lead, campaign, intent, tone
            ) + "\n\nMake this response MORE CONSULTATIVE and question-based."
            
            resp2 = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": alt2_prompt}],
                temperature=0.8,
                max_tokens=400
            )
            
            for resp in [resp1, resp2]:
                result_text = resp.choices[0].message.content.strip()
                if result_text.startswith("```json"):
                    result_text = result_text[7:]
                if result_text.startswith("```"):
                    result_text = result_text[3:]
                if result_text.endswith("```"):
                    result_text = result_text[:-3]
                
                try:
                    result = json.loads(result_text.strip())
                    alternatives.append(result)
                except:
                    pass
            
            return alternatives
            
        except Exception as e:
            logger.warning(f"Failed to generate alternatives: {e}")
            return []
    
    def _determine_action(
        self,
        intent: str,
        intent_result: Dict,
        objection_result: Optional[Dict]
    ) -> str:
        """Determine suggested action based on intent and objection."""
        
        # High confidence meeting request = send now
        if intent == "meeting_request" and intent_result.get("confidence", 0) > 0.85:
            return ResponseAction.SEND_NOW.value
        
        # Hard objection = review first
        if objection_result and objection_result.get("severity", 0) > 0.7:
            return ResponseAction.REVIEW_FIRST.value
        
        # Questions = send info
        if intent == "question":
            return ResponseAction.SEND_INFO.value
        
        # Not now = defer
        if intent == "not_now":
            return ResponseAction.DEFER.value
        
        # Wrong person = update contact
        if intent == "wrong_person":
            return ResponseAction.UPDATE_CONTACT.value
        
        # Default = review first for safety
        return ResponseAction.REVIEW_FIRST.value
    
    def draft_batch(
        self,
        replies: List[Dict[str, Any]],
        batch_size: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Draft responses for multiple replies in batches.
        
        Args:
            replies: List of dicts with 'reply', 'lead', 'campaign'
            batch_size: Batch size for processing
            
        Returns:
            List of response drafts
        """
        results = []
        
        for i in range(0, len(replies), batch_size):
            batch = replies[i:i+batch_size]
            
            for item in batch:
                result = self.draft_response(
                    reply=item.get("reply", ""),
                    lead=item.get("lead", {}),
                    campaign=item.get("campaign", {}),
                    include_alternatives=False  # Skip alternatives in batch mode
                )
                result["reply_id"] = item.get("id")
                results.append(result)
            
            logger.info(f"Processed batch {i//batch_size + 1}/{(len(replies) + batch_size - 1)//batch_size}")
        
        return results


# Convenience function
def draft_auto_response(
    reply: str,
    lead: Dict[str, Any],
    campaign: Dict[str, Any],
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to draft a single response.
    
    Args:
        reply: Reply text
        lead: Lead information
        campaign: Campaign context
        api_key: Optional OpenAI API key
        
    Returns:
        Response draft dict
    """
    drafter = AutoResponseDrafter(api_key=api_key)
    return drafter.draft_response(reply, lead, campaign)


if __name__ == "__main__":
    # Test the auto response drafter
    logging.basicConfig(level=logging.INFO)
    
    test_cases = [
        {
            "reply": "Thanks for reaching out! I'd love to schedule a call. What times work for you?",
            "lead": {"name": "John Smith", "company": "Acme Corp", "title": "VP Sales"},
            "campaign": {"value_proposition": "AI-powered sales automation that increases conversions by 40%"}
        },
        {
            "reply": "This looks interesting but we're currently using Salesforce.",
            "lead": {"name": "Jane Doe", "company": "Tech Inc", "title": "Marketing Director"},
            "campaign": {"value_proposition": "Next-gen CRM with AI insights"}
        }
    ]
    
    drafter = AutoResponseDrafter()
    
    print("\n=== Auto Response Drafting Test ===\n")
    
    for i, test in enumerate(test_cases):
        print(f"\nTest {i+1}:")
        print(f"Reply: {test['reply']}")
        
        result = drafter.draft_response(
            test['reply'],
            test['lead'],
            test['campaign']
        )
        
        if result.get("response"):
            print(f"\nDrafted Response:")
            print(result['response'])
            print(f"\nSuggested Action: {result.get('suggested_action')}")
            print(f"Confidence: {result.get('confidence', 0):.2f}")
            
            if result.get("alternatives"):
                print(f"\n{len(result['alternatives'])} alternative(s) generated")
