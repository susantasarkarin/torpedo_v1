"""
Cint Integration - Main Integration Module

Orchestrates:
- Service initialization with MongoDB collections
- Dependency injection setup
- FastAPI app integration
- Webhook management
- Configuration loading
"""

import os
import logging
from typing import Optional, Dict, Any
from pymongo import MongoClient
from pymongo.collection import Collection

from app.services.cint_service import CintService
from app.services.cint_allocation_extension import CintAllocationExtension
from database_setup_cint import setup_cint_database, setup_survey_allocation_extensions

logger = logging.getLogger(__name__)


class CintIntegration:
    """
    Main integration class for Cint API
    
    Manages service initialization, MongoDB collections, and configuration
    """
    
    def __init__(
        self,
        mongo_uri: str,
        api_key: str,
        supplier_code: str,
        environment: str = "sandbox",
        webhook_secret: Optional[str] = None,
    ):
        """
        Initialize Cint Integration
        
        Args:
            mongo_uri: MongoDB connection URI
            api_key: Cint API key
            supplier_code: Unique supplier code
            environment: "sandbox" or "production"
            webhook_secret: Secret for webhook signature validation
        """
        self.mongo_uri = mongo_uri
        self.api_key = api_key
        self.supplier_code = supplier_code
        self.environment = environment
        self.webhook_secret = webhook_secret
        
        # Services
        self.cint_service: Optional[CintService] = None
        self.allocation_extension: Optional[CintAllocationExtension] = None
        
        # Collections
        self.cint_collections: Dict[str, Collection] = {}
        self.survey_collections: Dict[str, Collection] = {}

    def initialize(self) -> bool:
        """
        Initialize all services and MongoDB collections
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Initializing Cint integration...")
            
            # Setup MongoDB collections
            self.cint_collections = setup_cint_database(self.mongo_uri)
            self.survey_collections = setup_survey_allocation_extensions(self.mongo_uri)
            
            # Initialize CintService
            self.cint_service = CintService(
                api_key=self.api_key,
                supplier_code=self.supplier_code,
                environment=self.environment,
                cint_surveys_collection=self.cint_collections.get("cint_surveys"),
                cint_entry_links_collection=self.cint_collections.get("cint_entry_links"),
                cint_settings_collection=self.cint_collections.get("cint_settings"),
            )
            
            # Initialize allocation extension
            self.allocation_extension = CintAllocationExtension(
                cint_surveys_collection=self.cint_collections.get("cint_surveys"),
                cint_entry_links_collection=self.cint_collections.get("cint_entry_links"),
                cint_metrics_collection=self.cint_collections.get("cint_metrics"),
                surveys_collection=self.survey_collections.get("surveys"),
                respondents_collection=self.survey_collections.get("respondents"),
                survey_metrics_collection=self.survey_collections.get("survey_metrics"),
            )
            
            logger.info("✓ Cint integration initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"Failed to initialize Cint integration: {str(e)}")
            return False

    async def close(self) -> None:
        """Close async connections"""
        if self.cint_service:
            await self.cint_service.close()
            logger.info("Cint service closed")

    def get_cint_service(self) -> Optional[CintService]:
        """Get CintService instance"""
        return self.cint_service

    def get_allocation_extension(self) -> Optional[CintAllocationExtension]:
        """Get CintAllocationExtension instance"""
        return self.allocation_extension

    # ============================================
    # Configuration & Settings
    # ============================================

    @staticmethod
    def load_from_env() -> "CintIntegration":
        """
        Load configuration from environment variables
        
        Expected environment variables:
        - MONGO_URI: MongoDB connection URI
        - CINT_API_KEY: Cint API key
        - CINT_SUPPLIER_CODE: Supplier code
        - CINT_ENVIRONMENT: "sandbox" or "production" (default: sandbox)
        - CINT_WEBHOOK_SECRET: Webhook signature secret (optional)
        
        Returns:
            Initialized CintIntegration instance
        """
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        api_key = os.getenv("CINT_API_KEY")
        supplier_code = os.getenv("CINT_SUPPLIER_CODE")
        environment = os.getenv("CINT_ENVIRONMENT", "sandbox")
        webhook_secret = os.getenv("CINT_WEBHOOK_SECRET")
        
        if not api_key or not supplier_code:
            raise ValueError(
                "Missing required environment variables: "
                "CINT_API_KEY, CINT_SUPPLIER_CODE"
            )
        
        integration = CintIntegration(
            mongo_uri=mongo_uri,
            api_key=api_key,
            supplier_code=supplier_code,
            environment=environment,
            webhook_secret=webhook_secret,
        )
        
        if integration.initialize():
            return integration
        else:
            raise RuntimeError("Failed to initialize Cint integration")

    # ============================================
    # Webhook Setup Helpers
    # ============================================

    async def setup_opportunities_subscription(
        self,
        callback_url: str,
        include_quotas: bool = True,
        countries: Optional[list] = None,
        industries: Optional[list] = None,
        min_cpi: float = 0.0,
        max_loi: int = 60,
    ) -> Dict[str, Any]:
        """
        Setup opportunities webhook subscription
        
        Args:
            callback_url: URL where Cint will send opportunities
            include_quotas: Whether to include quota/qualification data
            countries: List of country codes to filter (e.g., ["eng_us", "eng_gb"])
            industries: List of industry codes to filter
            min_cpi: Minimum CPI filter
            max_loi: Maximum LOI filter
        
        Returns:
            Result of subscription creation
        """
        if not self.cint_service:
            return {"success": False, "error": "CintService not initialized"}
        
        try:
            # Build filter criteria
            filters = []
            
            filter_dict = {}
            
            if countries:
                filter_dict["country_language"] = {"in": countries}
            
            if industries:
                filter_dict["industry"] = {"in": industries}
            
            if min_cpi > 0:
                filter_dict["revenue_per_interview"] = {"gte": min_cpi}
            
            if max_loi < 1000:
                filter_dict["bid_length_of_interview"] = {"lte": max_loi}
            
            if filter_dict:
                filters.append(filter_dict)
            
            # Create subscription config
            from app.models.cint import OpportunitiesSubscriptionConfig, OpportunitiesSubscriptionFilter
            
            config = OpportunitiesSubscriptionConfig(
                callback_url=callback_url,
                include_quotas=include_quotas,
                opportunities_filters=filters or [OpportunitiesSubscriptionFilter(country_language={"in": ["eng_us"]})],
            )
            
            result = await self.cint_service.create_opportunities_subscription(config)
            
            logger.info(f"Opportunities subscription setup: {result}")
            
            return result
        
        except Exception as e:
            logger.error(f"Error setting up subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    # ============================================
    # Quick Test Methods
    # ============================================

    async def test_api_connection(self) -> Dict[str, Any]:
        """
        Test Cint API connection
        
        Returns:
            Status of API connection test
        """
        if not self.cint_service:
            return {"success": False, "error": "CintService not initialized"}
        
        try:
            result = await self.cint_service.get_opportunities_subscription()
            
            if result.get("success"):
                logger.info("✓ Cint API connection successful")
            else:
                logger.warning("✗ Cint API connection failed")
            
            return result
        
        except Exception as e:
            logger.error(f"API connection test failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_active_surveys_count(self) -> int:
        """Get count of active Cint surveys in cache"""
        try:
            if self.cint_collections.get("cint_surveys"):
                return self.cint_collections["cint_surveys"].count_documents(
                    {"is_active": True}
                )
        except Exception as e:
            logger.error(f"Error counting surveys: {str(e)}")
        
        return 0

    def get_database_stats(self) -> Dict[str, Any]:
        """Get statistics about Cint databases"""
        stats = {
            "cint_surveys": 0,
            "cint_entry_links": 0,
            "cint_metrics": 0,
            "respondents": 0,
        }
        
        try:
            if self.cint_collections.get("cint_surveys"):
                stats["cint_surveys"] = self.cint_collections["cint_surveys"].estimated_document_count()
            
            if self.cint_collections.get("cint_entry_links"):
                stats["cint_entry_links"] = self.cint_collections["cint_entry_links"].estimated_document_count()
            
            if self.cint_collections.get("cint_metrics"):
                stats["cint_metrics"] = self.cint_collections["cint_metrics"].estimated_document_count()
            
            if self.survey_collections.get("respondents"):
                stats["respondents"] = self.survey_collections["respondents"].estimated_document_count()
        
        except Exception as e:
            logger.error(f"Error getting database stats: {str(e)}")
        
        return stats


# ============================================
# FastAPI Integration
# ============================================

def setup_cint_with_fastapp(app, integration: CintIntegration) -> None:
    """
    Setup Cint integration with FastAPI app
    
    Adds:
    - Startup event to initialize services
    - Shutdown event to close connections
    - Dependency injection for services
    
    Args:
        app: FastAPI application instance
        integration: CintIntegration instance
    """
    
    @app.on_event("startup")
    async def startup_cint():
        """Initialize Cint services on app startup"""
        logger.info("Starting up Cint integration...")
        
        # Collections are already initialized during CintIntegration creation
        # Store in app state for dependency injection
        app.state.cint_service = integration.get_cint_service()
        app.state.cint_allocation = integration.get_allocation_extension()
        
        # Test API connection
        result = await integration.test_api_connection()
        if result.get("success"):
            logger.info("✓ Cint API connection verified")
        else:
            logger.warning("✗ Cint API connection failed - check credentials")
        
        # Log database stats
        stats = integration.get_database_stats()
        logger.info(f"Database stats: {stats}")
    
    @app.on_event("shutdown")
    async def shutdown_cint():
        """Close Cint services on app shutdown"""
        logger.info("Shutting down Cint integration...")
        await integration.close()


# ============================================
# Dependency Injection Functions
# ============================================

def get_cint_service(app) -> Optional[CintService]:
    """
    Dependency injection function for CintService
    
    Usage in route:
        @router.get("/example")
        async def example(cint_service = Depends(get_cint_service)):
            ...
    """
    return getattr(app.state, "cint_service", None)


def get_cint_allocation(app) -> Optional[CintAllocationExtension]:
    """
    Dependency injection function for CintAllocationExtension
    
    Usage in route:
        @router.get("/example")
        async def example(cint_allocation = Depends(get_cint_allocation)):
            ...
    """
    return getattr(app.state, "cint_allocation", None)
