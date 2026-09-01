"""
OBJECTION HANDLER AGENT
========================

AI-powered objection detection and response generation for campaign replies.

Detects common objection types and generates tailored responses to address concerns.

Objection Types:
- price: Cost/budget concerns
- timing: Not ready now, bad timing
- wrong_person: Not decision maker
- already_have_solution: Using competitor/alternative
- no_budget: Budget constraints
- no_authority: Can't make decision
- need_more_info: Insufficient information

Features:
- Extends BaseAgent pattern
- GPT-4o-mini powered detection and response
- Severity scoring (0-1 scale)
- Contextual response generation
- Integration with lead data

Usage:
    agent = ObjectionHandlerAgent()
    
    # Detect objection
    objection = agent.detect_objection(
        "Your pricing is too high for us right now."
    )
    # Returns: {"objection_type": "price", "severity": 0.8, ...}
    
    # Generate response
    response = agent.generate_objection_response(
        objection=objection,
        lead={"name": "John", "company": "Acme"}
    )
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ObjectionType(str, Enum):
    """Types of sales objections"""
    PRICE = "price"
    TIMING = "timing"
    WRONG_PERSON = "wrong_person"
    ALREADY_HAVE_SOLUTION = "already_have_solution"
    NO_BUDGET = "no_budget"
    NO_AUTHORITY = "no_authority"
    NEED_MORE_INFO = "need_more_info"
    NOT_INTERESTED = "not_interested"
    NO_OBJECTION = "no_objection"


class ObjectionDetectionResult(BaseModel):
    """Result of objection detection"""
    objection_type: str = Field(..., description="Type of objection detected")
    severity: float = Field(..., description="Severity score 0-1 (1 = hard objection)")
    confidence: float = Field(..., description="Confidence in detection 0-1")
    explanation: str = Field(..., description="Why this objection was identified")
    key_phrases: List[str] = Field(default_factory=list, description="Phrases indicating objection")
    is_soft_objection: bool = Field(default=False, description="Can be easily addressed")


class ObjectionResponseResult(BaseModel):
    """Result of objection response generation"""
    response: str = Field(..., description="Generated response text")
    strategy: str = Field(..., description="Response strategy used")
    call_to_action: str = Field(..., description="Suggested next step")
    alternative_approaches: List[str] = Field(default_factory=list, description="Alternative response angles")


class ObjectionHandlerResult(BaseModel):
    """Combined objection handling result"""
    success: bool = True
    objection_detection: Optional[ObjectionDetectionResult] = None
    objection_response: Optional[ObjectionResponseResult] = None
    error: Optional[str] = None


class ObjectionHandlerAgent(BaseAgent[ObjectionHandlerResult]):
    """
    Agent that detects objections in replies and generates appropriate responses.
    
    Extends BaseAgent with specialized objection handling capabilities.
    """
    
    agent_name = "objection_handler"
    agent_description = "Detects and handles sales objections in replies"
    output_model = ObjectionHandlerResult
    
    # Objection response strategies
    RESPONSE_STRATEGIES = {
        ObjectionType.PRICE: "roi_value",
        ObjectionType.TIMING: "defer_and_nurture",
        ObjectionType.WRONG_PERSON: "referral_request",
        ObjectionType.ALREADY_HAVE_SOLUTION: "differentiation",
        ObjectionType.NO_BUDGET: "roi_justification",
        ObjectionType.NO_AUTHORITY: "stakeholder_involvement",
        ObjectionType.NEED_MORE_INFO: "information_provision",
        ObjectionType.NOT_INTERESTED: "pain_point_exploration"
    }
    
    def detect_objection(self, reply: str) -> Dict[str, Any]:
        """
        Detect objection type and severity in a reply.
        
        Args:
            reply: The reply text to analyze
            
        Returns:
            Dict with objection detection results
        """
        prompt = self._build_objection_detection_prompt(reply)
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at analyzing sales objections. Always respond with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse JSON
            import json
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            
            logger.info(
                f"Detected objection: {result.get('objection_type')} "
                f"(severity: {result.get('severity', 0):.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Objection detection failed: {e}")
            return {
                "objection_type": ObjectionType.NO_OBJECTION.value,
                "severity": 0.0,
                "confidence": 0.0,
                "explanation": f"Detection error: {str(e)}",
                "key_phrases": [],
                "is_soft_objection": False
            }
    
    def _build_objection_detection_prompt(self, reply: str) -> str:
        """Build prompt for objection detection."""
        
        examples = [
            {
                "reply": "This is way too expensive for us.",
                "objection_type": "price",
                "severity": 0.9,
                "explanation": "Direct price objection with strong negative language"
            },
            {
                "reply": "We're in the middle of Q4. Can we revisit this in January?",
                "objection_type": "timing",
                "severity": 0.4,
                "explanation": "Soft timing objection with specific follow-up suggestion"
            },
            {
                "reply": "I'm not the decision maker for this. Talk to our VP of Sales.",
                "objection_type": "wrong_person",
                "severity": 0.7,
                "explanation": "Wrong contact but provided referral"
            },
            {
                "reply": "We're already using Salesforce and it works fine for us.",
                "objection_type": "already_have_solution",
                "severity": 0.8,
                "explanation": "Has existing solution and satisfied with it"
            }
        ]
        
        examples_text = "\n\n".join([
            f"Example {i+1}:\n"
            f"Reply: \"{ex['reply']}\"\n"
            f"Objection Type: {ex['objection_type']}\n"
            f"Severity: {ex['severity']}\n"
            f"Explanation: {ex['explanation']}"
            for i, ex in enumerate(examples)
        ])
        
        return f"""Analyze this sales reply for objections.

OBJECTION TYPES:
- price: Cost/budget concerns
- timing: Not ready now, bad timing
- wrong_person: Not the decision maker
- already_have_solution: Using competitor/alternative
- no_budget: No budget allocated
- no_authority: Can't make the decision
- need_more_info: Need more information first
- not_interested: General disinterest
- no_objection: No objection detected

SEVERITY SCALE:
0.0-0.3: Very soft objection (easily addressable)
0.4-0.6: Moderate objection (requires good response)
0.7-0.9: Hard objection (significant barrier)
1.0: Deal killer (unlikely to overcome)

EXAMPLES:
{examples_text}

NOW ANALYZE:
Reply: "{reply}"

Respond with ONLY valid JSON:
{{
    "objection_type": "<one of the objection types>",
    "severity": <float 0-1>,
    "confidence": <float 0-1>,
    "explanation": "<why this objection was identified>",
    "key_phrases": ["<phrases indicating objection>"],
    "is_soft_objection": <true if severity < 0.5>
}}"""
    
    def generate_objection_response(
        self,
        objection: Dict[str, Any],
        lead: Dict[str, Any],
        campaign_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a tailored response to address the objection.
        
        Args:
            objection: Objection detection result
            lead: Lead information
            campaign_context: Optional campaign context
            
        Returns:
            Generated response text
        """
        objection_type = objection.get("objection_type")
        
        if objection_type == ObjectionType.NO_OBJECTION.value:
            return ""
        
        prompt = self._build_response_generation_prompt(objection, lead, campaign_context)
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert sales professional skilled at handling objections with empathy and persuasion."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Parse JSON
            import json
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            
            logger.info(f"Generated objection response using strategy: {result.get('strategy')}")
            
            return result.get("response", "")
            
        except Exception as e:
            logger.error(f"Response generation failed: {e}")
            return ""
    
    def _build_response_generation_prompt(
        self,
        objection: Dict[str, Any],
        lead: Dict[str, Any],
        campaign_context: Optional[Dict[str, Any]]
    ) -> str:
        """Build prompt for response generation."""
        
        objection_type = objection.get("objection_type")
        strategy = self.RESPONSE_STRATEGIES.get(ObjectionType(objection_type), "empathy_and_value")
        
        lead_name = lead.get("name", "there")
        company = lead.get("company", "your company")
        
        # Response guidelines by objection type
        guidelines = {
            "price": "Focus on ROI, value delivered, and cost of inaction. Ask about their current costs/inefficiencies.",
            "timing": "Acknowledge timing, suggest light touch points, and position for future readiness.",
            "wrong_person": "Thank them, ask for introduction/referral to right person.",
            "already_have_solution": "Ask about gaps/pain points with current solution, highlight unique differentiators.",
            "no_budget": "Explore budget cycle, discuss ROI to justify allocation, offer flexible options.",
            "no_authority": "Request multi-stakeholder meeting, provide materials for them to share internally.",
            "need_more_info": "Provide requested information, offer demo/case study, address specific concerns.",
            "not_interested": "Acknowledge, ask if timing is issue or other concerns, offer to stay in touch."
        }
        
        guideline = guidelines.get(objection_type, "Address with empathy and value")
        
        campaign_info = ""
        if campaign_context:
            campaign_info = f"\nCampaign Context: {campaign_context.get('value_proposition', '')}"
        
        return f"""Generate a professional response to this sales objection.

OBJECTION DETAILS:
Type: {objection_type}
Severity: {objection.get('severity', 0)}
Explanation: {objection.get('explanation', '')}

LEAD INFO:
Name: {lead_name}
Company: {company}
Title: {lead.get('title', 'N/A')}
{campaign_info}

RESPONSE STRATEGY: {strategy}
GUIDELINES: {guideline}

RESPONSE REQUIREMENTS:
1. Start with empathy/acknowledgment of their concern
2. Address the specific objection directly
3. Provide value/insight relevant to their situation
4. Include a soft call-to-action (no pressure)
5. Keep it professional and conversational
6. Maximum 150 words

Respond with ONLY valid JSON:
{{
    "response": "<the email response text>",
    "strategy": "{strategy}",
    "call_to_action": "<suggested next step>",
    "alternative_approaches": ["<other angles to try>"]
}}"""
    
    def handle_objection(
        self,
        reply: str,
        lead: Dict[str, Any],
        campaign_context: Optional[Dict[str, Any]] = None,
        generate_response: bool = True
    ) -> ObjectionHandlerResult:
        """
        Complete objection handling workflow.
        
        Args:
            reply: The reply text
            lead: Lead information
            campaign_context: Optional campaign context
            generate_response: Whether to generate response (default: True)
            
        Returns:
            ObjectionHandlerResult with detection and optional response
        """
        try:
            # Detect objection
            detection_result = self.detect_objection(reply)
            detection = ObjectionDetectionResult(**detection_result)
            
            response_result = None
            if generate_response and detection.objection_type != ObjectionType.NO_OBJECTION.value:
                # Generate response
                response_text = self.generate_objection_response(
                    detection_result,
                    lead,
                    campaign_context
                )
                
                if response_text:
                    import json
                    try:
                        response_data = json.loads(response_text) if isinstance(response_text, str) and response_text.startswith("{") else {"response": response_text}
                    except Exception:
                        response_data = {"response": response_text, "strategy": "unknown", "call_to_action": ""}
                    
                    response_result = ObjectionResponseResult(**response_data)
            
            return ObjectionHandlerResult(
                success=True,
                objection_detection=detection,
                objection_response=response_result
            )
            
        except Exception as e:
            logger.error(f"Objection handling failed: {e}")
            return ObjectionHandlerResult(
                success=False,
                error=str(e)
            )


if __name__ == "__main__":
    # Test the objection handler
    logging.basicConfig(level=logging.INFO)
    
    agent = ObjectionHandlerAgent()
    
    test_cases = [
        {
            "reply": "This is way too expensive for our small business.",
            "lead": {"name": "John Smith", "company": "Small Biz Inc", "title": "Owner"}
        },
        {
            "reply": "We're currently using HubSpot and it's working well.",
            "lead": {"name": "Jane Doe", "company": "Tech Corp", "title": "Marketing Director"}
        },
        {
            "reply": "Can we talk about this next quarter? Too busy right now.",
            "lead": {"name": "Bob Johnson", "company": "Busy Corp", "title": "VP Sales"}
        }
    ]
    
    print("\n=== Objection Handler Test ===\n")
    
    for i, test in enumerate(test_cases):
        print(f"\nTest {i+1}:")
        print(f"Reply: {test['reply']}")
        
        result = agent.handle_objection(test['reply'], test['lead'])
        
        if result.success and result.objection_detection:
            print(f"Objection: {result.objection_detection.objection_type}")
            print(f"Severity: {result.objection_detection.severity:.2f}")
            
            if result.objection_response:
                print(f"\nGenerated Response:")
                print(result.objection_response.response)
                print(f"\nStrategy: {result.objection_response.strategy}")
