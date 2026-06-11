"""
Base Agent - Abstract base class for all lead generation agents
"""

import os
import json
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, List, TypeVar, Generic
from pydantic import BaseModel

try:
    from ai_governance.claude_gateway import ClaudeChatClient
except ImportError:  # package context (tests import as backend.*)
    from backend.ai_governance.claude_gateway import ClaudeChatClient

logger = logging.getLogger(__name__)

# Type variable for agent results
T = TypeVar('T', bound=BaseModel)

# Constants
LEADS_PER_BATCH = 10
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2.0  # seconds

# MODEL CONFIGURATION: Anthropic Claude for everything (via ai_governance)
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_PROVIDER = "anthropic"
WEB_SEARCH_MODEL = "claude-opus-4-8"
WEB_SEARCH_PROVIDER = "anthropic"
# NOTE: Email classification/summarization uses Claude via ai_governance module


class AgentResult(BaseModel):
    """Standard result wrapper for all agents"""
    success: bool = False
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    retries: int = 0
    timestamp: datetime = datetime.utcnow()


class BaseAgent(ABC, Generic[T]):
    """
    Abstract base class for all lead generation agents.
    
    Features:
    - Retry logic with exponential backoff
    - Cost tracking via existing openai_wrapper
    - JSON array response parsing
    - Pydantic output validation
    - Configurable via AgentConfig
    """
    
    # Class attributes to be set by subclasses
    agent_name: str = "base_agent"
    agent_description: str = "Base agent"
    output_model: type = BaseModel
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize agent with optional configuration.
        
        Args:
            config: Agent-specific configuration dict
        """
        self.config = config or {}
        self._openai_client: Optional[ClaudeChatClient] = None
        self._mongo_client = None
        self._db = None

    @property
    def client(self) -> ClaudeChatClient:
        """Default LLM client (Claude via the governed compat layer)."""
        return self._get_openai_client()

    def _get_openai_client(self) -> ClaudeChatClient:
        """Get the Claude-backed chat client (name kept for compat)."""
        if self._openai_client is None:
            # Key resolution happens inside ai_governance (DB settings, then env)
            self._openai_client = ClaudeChatClient()
        return self._openai_client
    
    def _get_db(self):
        """Get MongoDB database connection."""
        if self._db is None:
            from pymongo import MongoClient
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            self._mongo_client = MongoClient(mongo_uri)
            self._db = self._mongo_client['email_automation']
        return self._db
    
    @abstractmethod
    def build_prompt(self, input_data: Any) -> str:
        """
        Build the prompt for the agent.
        Must be implemented by subclasses.
        
        Args:
            input_data: Input data for the agent
            
        Returns:
            Formatted prompt string
        """
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for the agent.
        Must be implemented by subclasses.
        
        Returns:
            System prompt string
        """
        pass
    
    @abstractmethod
    def parse_response(self, response_text: str) -> T:
        """
        Parse the AI response into the output model.
        Must be implemented by subclasses.
        
        Args:
            response_text: Raw response from AI
            
        Returns:
            Parsed output model instance
        """
        pass
    
    def execute(self, input_data: Any, use_web_search: bool = False) -> AgentResult:
        """
        Execute the agent with retry logic and cost tracking.
        
        Args:
            input_data: Input data for the agent
            use_web_search: Whether to use web search tool
            
        Returns:
            AgentResult with success status and data
        """
        start_time = time.time()
        retries = 0
        last_error = None
        
        while retries <= MAX_RETRIES:
            try:
                # Build messages
                system_prompt = self.get_system_prompt()
                user_prompt = self.build_prompt(input_data)
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                
                # Make API call
                if use_web_search:
                    response = self._call_with_web_search(messages)
                else:
                    response = self._call_chat_completion(messages)
                
                # Parse response
                content = response.get("content", "")
                parsed_data = self.parse_response(content)
                
                latency_ms = int((time.time() - start_time) * 1000)
                
                # Log usage
                self._log_usage(
                    input_tokens=response.get("input_tokens", 0),
                    output_tokens=response.get("output_tokens", 0),
                    model=response.get("model", DEFAULT_MODEL),
                    latency_ms=latency_ms,
                    success=True
                )
                
                return AgentResult(
                    success=True,
                    data=parsed_data.model_dump() if hasattr(parsed_data, 'model_dump') else parsed_data,
                    tokens_used=response.get("total_tokens", 0),
                    cost_usd=self._calculate_cost(
                        response.get("input_tokens", 0),
                        response.get("output_tokens", 0),
                        response.get("model", DEFAULT_MODEL)
                    ),
                    latency_ms=latency_ms,
                    retries=retries
                )
                
            except Exception as e:
                last_error = str(e)
                retries += 1
                logger.warning(f"{self.agent_name} attempt {retries} failed: {e}")
                
                if retries <= MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (retries - 1))
                    time.sleep(delay)
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Log failed attempt
        self._log_usage(
            input_tokens=0,
            output_tokens=0,
            model=DEFAULT_MODEL,
            latency_ms=latency_ms,
            success=False,
            error_message=last_error
        )
        
        return AgentResult(
            success=False,
            error=last_error,
            latency_ms=latency_ms,
            retries=retries
        )
    
    def _call_chat_completion(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Make a chat completion call via the governed Claude compat client."""
        response = self.client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        message = response.choices[0].message
        usage = response.usage
        
        return {
            "content": message.content,
            "model": response.model,
            "provider": "anthropic",
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0
        }
    
    def _call_with_web_search(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Make a chat completion call with web search capability.
        NOTE: web_search_preview is not available in standard OpenAI SDK.
        Falls back to regular chat completion.
        """
        try:
            openai_client = self._get_openai_client()
            
            # Log that we're using fallback
            logger.warning("Web search not available in standard SDK. Using chat completion fallback.")
            
            # Add a system note about limitations
            enhanced_messages = messages.copy()
            if enhanced_messages and enhanced_messages[0]["role"] == "system":
                enhanced_messages[0]["content"] += "\n\nNote: Real-time web search is not available. Provide information based on your training data."
            
            # Use standard chat completion
            response = openai_client.chat.completions.create(
                model=WEB_SEARCH_MODEL,  # gpt-4o-mini
                messages=enhanced_messages,
                temperature=0.7
            )
            
            # Extract content from response
            content = ""
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content or ""
            
            usage = response.usage
            
            return {
                "content": content,
                "model": WEB_SEARCH_MODEL,
                "provider": "anthropic",
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0
            }
            
        except Exception as e:
            logger.warning(f"Chat completion failed: {e}")
            # Fallback to regular OpenAI completion
            return self._call_chat_completion(messages)
    
    # USD per 1K tokens
    _MODEL_COSTS = {
        "claude-opus-4-8": {"input": 0.005, "output": 0.025},
        "claude-haiku-4-5": {"input": 0.001, "output": 0.005},
    }

    def _calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Calculate cost in USD based on token usage."""
        model_costs = self._MODEL_COSTS.get(model, self._MODEL_COSTS["claude-opus-4-8"])
        return (input_tokens / 1000 * model_costs["input"]) + (output_tokens / 1000 * model_costs["output"])
    
    def _log_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
        latency_ms: int,
        success: bool,
        error_message: str = ""
    ):
        """Log usage to MongoDB."""
        try:
            db = self._get_db()
            collection = db['ai_usage_logs']
            
            cost_usd = self._calculate_cost(input_tokens, output_tokens, model)
            provider = "anthropic"
            
            doc = {
                "timestamp": datetime.utcnow(),
                "provider": provider,
                "model": model,
                "source": "lead_agent",
                "endpoint": self.agent_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": round(cost_usd, 6),
                "latency_ms": latency_ms,
                "success": success,
                "error_message": error_message
            }
            
            collection.insert_one(doc)
        except Exception as e:
            logger.warning(f"Failed to log agent usage: {e}")
    
    def _extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        """
        Extract JSON from AI response, handling markdown code blocks.
        
        Args:
            response_text: Raw response text
            
        Returns:
            Parsed JSON dict
        """
        text = response_text.strip()
        
        # Remove markdown code blocks if present
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        
        if text.endswith("```"):
            text = text[:-3]
        
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Could not parse JSON from response: {e}")
