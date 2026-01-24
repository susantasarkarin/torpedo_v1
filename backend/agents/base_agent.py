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

from openai import OpenAI

logger = logging.getLogger(__name__)

# Type variable for agent results
T = TypeVar('T', bound=BaseModel)

# Constants
LEADS_PER_BATCH = 10
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2.0  # seconds

# MODEL CONFIGURATION: OpenAI for all tasks (DeepSeek balance exhausted)
DEFAULT_MODEL = "gpt-4o-mini"           # OpenAI gpt-4o-mini for all tasks
DEFAULT_PROVIDER = "openai"
WEB_SEARCH_MODEL = "gpt-4o-mini"        # OpenAI for web search (required)
WEB_SEARCH_PROVIDER = "openai"
DEEPSEEK_API_BASE = "https://api.deepseek.com"


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
        self._deepseek_client: Optional[OpenAI] = None
        self._openai_client: Optional[OpenAI] = None
        self._mongo_client = None
        self._db = None
    
    @property
    def client(self) -> OpenAI:
        """Default client (DeepSeek for cost savings)."""
        return self._get_deepseek_client()
    
    def _get_deepseek_client(self) -> OpenAI:
        """Get DeepSeek client for most tasks."""
        if self._deepseek_client is None:
            api_key = self._get_deepseek_api_key()
            if not api_key:
                # Fallback to OpenAI if no DeepSeek key
                logger.warning("DeepSeek API key not found, falling back to OpenAI")
                return self._get_openai_client()
            self._deepseek_client = OpenAI(
                api_key=api_key,
                base_url=DEEPSEEK_API_BASE
            )
        return self._deepseek_client
    
    def _get_openai_client(self) -> OpenAI:
        """Get OpenAI client for web search tasks."""
        if self._openai_client is None:
            api_key = self._get_openai_api_key()
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client
    
    def _get_deepseek_api_key(self) -> Optional[str]:
        """Get DeepSeek API key from DB or environment."""
        try:
            from pymongo import MongoClient
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
            settings_db = client["torpedo_settings"]
            app_settings = settings_db["app_settings"]
            stored = app_settings.find_one({"_id": "app_config"})
            if stored and stored.get("deepseek_api_key"):
                return stored["deepseek_api_key"]
        except Exception as e:
            logger.debug(f"Could not fetch DeepSeek key from DB: {e}")
        return os.getenv("DEEPSEEK_API_KEY")
    
    def _get_openai_api_key(self) -> Optional[str]:
        """Get OpenAI API key from DB or environment."""
        try:
            from pymongo import MongoClient
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
            settings_db = client["torpedo_settings"]
            app_settings = settings_db["app_settings"]
            stored = app_settings.find_one({"_id": "app_config"})
            if stored and stored.get("openai_api_key"):
                return stored["openai_api_key"]
        except Exception as e:
            logger.debug(f"Could not fetch OpenAI key from DB: {e}")
        return os.getenv("OPENAI_API_KEY")
    
    # Legacy compatibility
    def _get_api_key(self) -> Optional[str]:
        """Legacy method - returns DeepSeek key (or OpenAI fallback)."""
        return self._get_deepseek_api_key() or self._get_openai_api_key()
    
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
        """Make a chat completion call using DeepSeek (default)."""
        response = self.client.chat.completions.create(
            model=DEFAULT_MODEL,  # deepseek-chat
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
            "provider": "deepseek",
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0
        }
    
    def _call_with_web_search(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Make a chat completion call with web search tool.
        Uses OpenAI's Responses API with web_search_preview tool.
        NOTE: This MUST use OpenAI - DeepSeek doesn't have web search.
        """
        try:
            openai_client = self._get_openai_client()
            
            # Convert messages to single input for Responses API
            system_content = ""
            user_content = ""
            for msg in messages:
                if msg["role"] == "system":
                    system_content = msg["content"]
                elif msg["role"] == "user":
                    user_content = msg["content"]
            
            full_prompt = f"{system_content}\n\n{user_content}"
            
            # Use Responses API with web search (OpenAI only)
            response = openai_client.responses.create(
                model=WEB_SEARCH_MODEL,  # gpt-4o-mini
                tools=[{"type": "web_search_preview"}],
                input=full_prompt
            )
            
            # Extract content from response
            content = ""
            if hasattr(response, 'output'):
                for item in response.output:
                    if hasattr(item, 'content'):
                        for block in item.content:
                            if hasattr(block, 'text'):
                                content += block.text
            
            # Estimate tokens (Responses API doesn't always return usage)
            input_tokens = len(full_prompt) // 4
            output_tokens = len(content) // 4
            
            return {
                "content": content,
                "model": WEB_SEARCH_MODEL,
                "provider": "openai",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
            
        except Exception as e:
            logger.warning(f"Web search failed, falling back to DeepSeek: {e}")
            # Fallback to regular DeepSeek completion
            return self._call_chat_completion(messages)
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Calculate cost in USD based on token usage."""
        costs = {
            "deepseek-chat": {"input": 0.00014, "output": 0.00028},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "gpt-4o": {"input": 0.005, "output": 0.015},
        }
        model_costs = costs.get(model, costs["deepseek-chat"])
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
            
            costs = {
                "deepseek-chat": {"input": 0.00014, "output": 0.00028},
                "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
                "gpt-4o": {"input": 0.005, "output": 0.015},
            }
            model_costs = costs.get(model, costs["deepseek-chat"])
            cost_usd = (input_tokens / 1000 * model_costs["input"]) + (output_tokens / 1000 * model_costs["output"])
            
            # Determine provider from model
            provider = "deepseek" if "deepseek" in model else "openai"
            
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
