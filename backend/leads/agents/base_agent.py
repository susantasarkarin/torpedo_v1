"""
Base Agent Class
================

Abstract base class for all phase agents in the lead generation pipeline.
Provides common functionality for logging, status tracking, and result handling.
"""

import os
import logging
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pymongo import MongoClient

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # Completed with some errors
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentResult:
    """Result from agent execution"""
    agent_name: str
    phase: int
    status: AgentStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    records_processed: int = 0
    records_success: int = 0
    records_failed: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "agent_name": self.agent_name,
            "phase": self.phase,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "records_processed": self.records_processed,
            "records_success": self.records_success,
            "records_failed": self.records_failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "output_data": self.output_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentResult':
        """Create from dictionary"""
        return cls(
            agent_name=data.get("agent_name", "unknown"),
            phase=data.get("phase", 0),
            status=AgentStatus(data.get("status", "pending")),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.utcnow(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            duration_seconds=data.get("duration_seconds", 0.0),
            records_processed=data.get("records_processed", 0),
            records_success=data.get("records_success", 0),
            records_failed=data.get("records_failed", 0),
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
            metrics=data.get("metrics", {}),
            output_data=data.get("output_data", {})
        )


class BaseAgent(ABC):
    """
    Abstract base class for phase agents.
    
    Each agent:
    - Has a name and phase number
    - Connects to MongoDB for data access
    - Tracks execution status and metrics
    - Can be run independently or orchestrated
    - Logs progress and errors
    """
    
    def __init__(self, name: str, phase: int):
        self.name = name
        self.phase = phase
        self.logger = logging.getLogger(f"agent.{name}")
        
        # MongoDB connection
        self.mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        self._client: Optional[MongoClient] = None
        
        # Execution state
        self._status = AgentStatus.PENDING
        self._started_at: Optional[datetime] = None
        self._errors: List[str] = []
        self._warnings: List[str] = []
        self._metrics: Dict[str, Any] = {}
        
        # Configuration
        self.config: Dict[str, Any] = {}
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds
        
    @property
    def client(self) -> MongoClient:
        """Lazy MongoDB client initialization"""
        if self._client is None:
            self._client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
        return self._client
    
    @property
    def db(self):
        """Get email_automation database"""
        return self.client['email_automation']
    
    @property
    def gmail_db(self):
        """Get torpedo_gmail database"""
        return self.client['torpedo_gmail']
    
    @property
    def status(self) -> AgentStatus:
        """Get current status"""
        return self._status
    
    def configure(self, config: Dict[str, Any]) -> 'BaseAgent':
        """
        Configure agent with custom settings.
        Returns self for chaining.
        """
        self.config.update(config)
        return self
    
    def log_info(self, message: str):
        """Log info message"""
        self.logger.info(f"[{self.name}] {message}")
    
    def log_warning(self, message: str):
        """Log warning and track it"""
        self.logger.warning(f"[{self.name}] {message}")
        self._warnings.append(message)
    
    def log_error(self, message: str):
        """Log error and track it"""
        self.logger.error(f"[{self.name}] {message}")
        self._errors.append(message)
    
    def add_metric(self, key: str, value: Any):
        """Add a metric to track"""
        self._metrics[key] = value
    
    def increment_metric(self, key: str, amount: int = 1):
        """Increment a numeric metric"""
        current = self._metrics.get(key, 0)
        self._metrics[key] = current + amount
    
    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Execute the agent.
        
        Args:
            input_data: Optional input data for the agent
            
        Returns:
            AgentResult with execution details
        """
        self._started_at = datetime.utcnow()
        self._status = AgentStatus.RUNNING
        self._errors = []
        self._warnings = []
        self._metrics = {}
        
        self.log_info(f"Starting Phase {self.phase} agent execution")
        
        try:
            # Run the actual agent logic
            output_data = await self.execute(input_data or {})
            
            # Determine final status
            if self._errors:
                self._status = AgentStatus.PARTIAL if output_data else AgentStatus.FAILED
            else:
                self._status = AgentStatus.SUCCESS
                
        except asyncio.CancelledError:
            self._status = AgentStatus.CANCELLED
            self.log_warning("Agent execution cancelled")
            output_data = {}
        except Exception as e:
            self._status = AgentStatus.FAILED
            self.log_error(f"Agent execution failed: {str(e)}")
            output_data = {}
        
        completed_at = datetime.utcnow()
        duration = (completed_at - self._started_at).total_seconds()
        
        result = AgentResult(
            agent_name=self.name,
            phase=self.phase,
            status=self._status,
            started_at=self._started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            records_processed=self._metrics.get("records_processed", 0),
            records_success=self._metrics.get("records_success", 0),
            records_failed=self._metrics.get("records_failed", 0),
            errors=self._errors,
            warnings=self._warnings,
            metrics=self._metrics,
            output_data=output_data
        )
        
        self.log_info(f"Completed in {duration:.2f}s - Status: {self._status.value}")
        
        # Store result in MongoDB
        await self._store_result(result)
        
        return result
    
    async def _store_result(self, result: AgentResult):
        """Store agent result in MongoDB"""
        try:
            collection = self.db['agent_execution_logs']
            collection.insert_one({
                **result.to_dict(),
                "stored_at": datetime.utcnow()
            })
        except Exception as e:
            self.log_warning(f"Failed to store result: {e}")
    
    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent's main logic.
        
        Args:
            input_data: Input data for processing
            
        Returns:
            Output data dictionary
            
        Must be implemented by subclasses.
        """
        pass
    
    @abstractmethod
    def get_description(self) -> str:
        """Return a description of what this agent does"""
        pass
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get current status summary"""
        return {
            "name": self.name,
            "phase": self.phase,
            "status": self._status.value,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "errors_count": len(self._errors),
            "warnings_count": len(self._warnings),
            "metrics": self._metrics
        }
    
    def cleanup(self):
        """Cleanup resources"""
        if self._client:
            self._client.close()
            self._client = None


class AgentRegistry:
    """Registry for managing available agents"""
    
    _agents: Dict[str, type] = {}
    
    @classmethod
    def register(cls, agent_class: type):
        """Register an agent class"""
        cls._agents[agent_class.__name__] = agent_class
        return agent_class
    
    @classmethod
    def get(cls, name: str) -> Optional[type]:
        """Get agent class by name"""
        return cls._agents.get(name)
    
    @classmethod
    def list_agents(cls) -> List[str]:
        """List all registered agents"""
        return list(cls._agents.keys())
    
    @classmethod
    def create(cls, name: str, **kwargs) -> Optional[BaseAgent]:
        """Create agent instance by name"""
        agent_class = cls.get(name)
        if agent_class:
            return agent_class(**kwargs)
        return None
