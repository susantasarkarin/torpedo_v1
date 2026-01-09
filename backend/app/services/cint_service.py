"""
Cint API Integration Service

Handles:
- API authentication and requests to Cint API
- Webhook signature validation
- Opportunity parsing and storage
- Entry link CRUD operations
- Subscription management
"""
import os
import hmac
import hashlib
import json
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from urllib.parse import urlencode
import logging
from pymongo import MongoClient
from pymongo.collection import Collection

from app.models.cint import (
    CintOpportunity,
    SupplierLink,
    SupplierLinkCreate,
    CintSettings,
    OpportunitiesSubscriptionConfig,
    OutcomeSubscriptionConfig,
    RespondentOutcome,
)

logger = logging.getLogger(__name__)


class CintService:
    """Service to interact with Cint API (Opportunities & Entry Links)"""
    
    # API Endpoints
    SANDBOX_BASE_URL = "https://sandbox.techops.engineering/"
    PRODUCTION_BASE_URL = "https://api.samplicio.us/"
    
    # Supply Integration Endpoints
    OPPORTUNITIES_ENDPOINT = "supply/opportunities/v1/subscriptions/{supplier_code}"
    ENTRY_LINKS_ENDPOINT = "Supply/v1/SupplierLinks"
    
    def __init__(
        self,
        api_key: str,
        supplier_code: str,
        environment: str = "sandbox",
        cint_surveys_collection: Optional[Collection] = None,
        cint_entry_links_collection: Optional[Collection] = None,
        cint_settings_collection: Optional[Collection] = None,
        api_timeout: int = 30,
    ):
        """
        Initialize Cint Service

        Args:
            api_key: Cint API Key
            supplier_code: Unique supplier code
            environment: "sandbox" or "production"
            cint_surveys_collection: MongoDB collection for cint_research.cint_surveys
            cint_entry_links_collection: MongoDB collection for cint_research.cint_entry_links
            cint_settings_collection: MongoDB collection for cint_research.cint_settings
            api_timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.supplier_code = supplier_code
        self.environment = environment
        self.api_timeout = api_timeout
        
        # Set base URL based on environment
        self.base_url = (
            self.PRODUCTION_BASE_URL
            if environment == "production"
            else self.SANDBOX_BASE_URL
        )
        
        # Collections
        self.cint_surveys_collection = cint_surveys_collection
        self.cint_entry_links_collection = cint_entry_links_collection
        self.cint_settings_collection = cint_settings_collection
        
        # HTTP client
        self.client = httpx.AsyncClient(timeout=api_timeout)

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    # ============================================
    # Authentication & Headers
    # ============================================

    def _get_headers(self) -> Dict[str, str]:
        """Get standard API headers"""
        return {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

    # ============================================
    # Webhook Validation
    # ============================================

    def validate_webhook_signature(
        self, payload: bytes, signature: str, webhook_secret: str
    ) -> bool:
        """
        Validate incoming webhook signature

        Args:
            payload: Raw webhook payload
            signature: Signature from X-Cint-Signature header
            webhook_secret: Secret provided by Cint during subscription setup

        Returns:
            True if signature is valid
        """
        expected_signature = hmac.new(
            webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)

    # ============================================
    # Opportunities Subscription Management
    # ============================================

    async def create_opportunities_subscription(
        self, config: OpportunitiesSubscriptionConfig
    ) -> Dict[str, Any]:
        """
        Create or update opportunities subscription

        Args:
            config: Subscription configuration with callback URL and filters

        Returns:
            Response from Cint API
        """
        url = f"{self.base_url}{self.OPPORTUNITIES_ENDPOINT.format(supplier_code=self.supplier_code)}"
        
        # Build opportunities filters - must have at least one filter per Cint API spec
        opportunities = [
            filter.dict(exclude_none=True)
            for filter in config.opportunities_filters
        ] if config.opportunities_filters else [
            # Default: accept major English-speaking locales
            {"country_language": {"in": ["eng_us", "eng_gb", "eng_ca", "eng_au"]}}
        ]
        
        payload = {
            "callback": config.callback_url,
            "include_quotas": config.include_quotas,
            "payload_max_size_mb": config.payload_max_size_mb,
            "payload_max_survey_count": config.payload_max_survey_count,
            "send_interval_seconds": config.send_interval_seconds,
            "opportunities": opportunities,
        }
        
        try:
            # POST per Cint API documentation: https://developer.lucidhq.com/#post-create-opportunities-subscription
            response = await self.client.post(
                url,
                json=payload,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            
            logger.info(f"Opportunities subscription created for {self.supplier_code}")
            return {"success": True, "data": response.json()}
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Cint subscription error: {e.response.status_code} - {e.response.text}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Cint subscription failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_opportunities_subscription(self) -> Dict[str, Any]:
        """
        Get current opportunities subscription status

        Returns:
            Current subscription configuration
        """
        url = f"{self.base_url}{self.OPPORTUNITIES_ENDPOINT.format(supplier_code=self.supplier_code)}"
        
        try:
            response = await self.client.get(
                url,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            
            logger.info(f"Retrieved opportunities subscription for {self.supplier_code}")
            return {"success": True, "data": response.json()}
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get subscription: {e.response.status_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Failed to get subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    async def delete_opportunities_subscription(self) -> Dict[str, Any]:
        """
        Delete opportunities subscription

        Returns:
            Status of deletion
        """
        url = f"{self.base_url}{self.OPPORTUNITIES_ENDPOINT.format(supplier_code=self.supplier_code)}"
        
        try:
            response = await self.client.delete(
                url,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            
            logger.info(f"Opportunities subscription deleted for {self.supplier_code}")
            return {"success": True}
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to delete subscription: {e.response.status_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Failed to delete subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    # ============================================
    # Opportunity Processing
    # ============================================

    async def process_opportunity_webhook(
        self, payload: Dict[str, Any], check_active: bool = True
    ) -> List[CintOpportunity]:
        """
        Process incoming opportunities from webhook

        Args:
            payload: Webhook payload (single opportunity dict or array)
            check_active: If True, deactivate surveys with message_reason="deactivated"

        Returns:
            List of processed CintOpportunity objects
        """
        # Handle both single opportunity and array
        opportunities = payload if isinstance(payload, list) else [payload]
        
        processed = []
        
        for opp_data in opportunities:
            try:
                # Add webhook timestamp if not present
                if "webhook_timestamp" not in opp_data:
                    opp_data["webhook_timestamp"] = datetime.now(timezone.utc)
                
                # Parse to Pydantic model
                opportunity = CintOpportunity(**opp_data)
                
                # Determine if survey is active
                opportunity.is_active = opportunity.is_live and opportunity.message_reason != "deactivated"
                
                # Store in MongoDB if collection provided
                if self.cint_surveys_collection is not None:
                    self._upsert_opportunity(opportunity)
                
                processed.append(opportunity)
                
            except Exception as e:
                logger.error(f"Error processing opportunity {opp_data.get('survey_id')}: {str(e)}")
                continue
        
        logger.info(f"Processed {len(processed)} opportunities from webhook")
        return processed

    def _upsert_opportunity(self, opportunity: CintOpportunity) -> None:
        """
        Insert or update opportunity in MongoDB

        Args:
            opportunity: CintOpportunity instance
        """
        if not self.cint_surveys_collection:
            return
        
        query = {"survey_id": opportunity.survey_id}
        update = {
            "$set": opportunity.dict(exclude={"id"}, exclude_none=False),
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
        }
        
        self.cint_surveys_collection.update_one(
            query,
            update,
            upsert=True,
        )

    # ============================================
    # Entry Links Management
    # ============================================

    async def create_entry_link(
        self, survey_id: int, link_config: SupplierLinkCreate
    ) -> Dict[str, Any]:
        """
        Create entry link for a survey

        Args:
            survey_id: Cint survey ID
            link_config: Entry link configuration

        Returns:
            Created entry link with live_link and test_link
        """
        url = f"{self.base_url}{self.ENTRY_LINKS_ENDPOINT}/Create/{survey_id}/{self.supplier_code}"
        
        payload = link_config.dict(exclude_none=True)
        
        try:
            response = await self.client.post(
                url,
                json=payload,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            
            # Parse response
            api_response = response.json()
            
            # Extract supplier link from response
            if "SupplierLink" in api_response:
                link_data = api_response["SupplierLink"]
                
                # Create SupplierLink object
                supplier_link = SupplierLink(
                    survey_id=survey_id,
                    survey_number=survey_id,
                    **link_data
                )
                
                # Store in MongoDB if collection provided
                if self.cint_entry_links_collection is not None:
                    self._store_entry_link(supplier_link)
                
                logger.info(f"Entry link created for survey {survey_id}")
                return {"success": True, "link": supplier_link}
            
            return {"success": False, "error": "Invalid API response"}
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create entry link: {e.response.status_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Failed to create entry link: {str(e)}")
            return {"success": False, "error": str(e)}

    async def update_entry_link(
        self, survey_id: int, link_config: SupplierLinkCreate
    ) -> Dict[str, Any]:
        """
        Update existing entry link

        Args:
            survey_id: Cint survey ID
            link_config: Updated entry link configuration

        Returns:
            Updated entry link
        """
        url = f"{self.base_url}{self.ENTRY_LINKS_ENDPOINT}/Update/{survey_id}/{self.supplier_code}"
        
        payload = link_config.dict(exclude_none=False)
        
        try:
            response = await self.client.put(
                url,
                json=payload,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            
            api_response = response.json()
            
            if "SupplierLink" in api_response:
                link_data = api_response["SupplierLink"]
                supplier_link = SupplierLink(
                    survey_id=survey_id,
                    survey_number=survey_id,
                    **link_data
                )
                
                if self.cint_entry_links_collection is not None:
                    self._store_entry_link(supplier_link)
                
                logger.info(f"Entry link updated for survey {survey_id}")
                return {"success": True, "link": supplier_link}
            
            return {"success": False, "error": "Invalid API response"}
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to update entry link: {e.response.status_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Failed to update entry link: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_entry_link(self, survey_id: int) -> Dict[str, Any]:
        """
        Retrieve entry link for a survey

        Args:
            survey_id: Cint survey ID

        Returns:
            Entry link details
        """
        url = f"{self.base_url}{self.ENTRY_LINKS_ENDPOINT}/BySurveyNumber/{survey_id}/{self.supplier_code}"
        
        try:
            response = await self.client.get(
                url,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            
            api_response = response.json()
            
            if "SupplierLink" in api_response:
                link_data = api_response["SupplierLink"]
                supplier_link = SupplierLink(
                    survey_id=survey_id,
                    survey_number=survey_id,
                    **link_data
                )
                
                logger.info(f"Retrieved entry link for survey {survey_id}")
                return {"success": True, "link": supplier_link}
            
            return {"success": False, "error": "Entry link not found"}
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Entry link not found for survey {survey_id}")
                return {"success": False, "error": "Entry link not found", "status_code": 404}
            
            logger.error(f"Failed to get entry link: {e.response.status_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Failed to get entry link: {str(e)}")
            return {"success": False, "error": str(e)}

    def _store_entry_link(self, supplier_link: SupplierLink) -> None:
        """
        Store entry link in MongoDB

        Args:
            supplier_link: SupplierLink instance
        """
        if not self.cint_entry_links_collection:
            return
        
        query = {"survey_id": supplier_link.survey_id}
        update = {
            "$set": supplier_link.dict(exclude={"id"}, exclude_none=False),
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
        }
        
        self.cint_entry_links_collection.update_one(
            query,
            update,
            upsert=True,
        )

    # ============================================
    # Entry Link URL Generation
    # ============================================

    def build_entry_link(
        self,
        live_link: str,
        respondent_id: str,
        country_code: str,
        pid: Optional[str] = None,
        mid: Optional[str] = None,
        **additional_params
    ) -> str:
        """
        Build complete entry link with respondent parameters

        Args:
            live_link: Base live link from Cint
            respondent_id: Unique respondent ID
            country_code: ISO country code
            pid: Panelist ID (optional)
            mid: Session/Market ID (optional)
            **additional_params: Additional query parameters

        Returns:
            Complete entry link with all parameters
        """
        params = {
            "rid": respondent_id,
            "cc": country_code,
        }
        
        if pid:
            params["pid"] = pid
        if mid:
            params["mid"] = mid
        
        # Add any additional parameters
        params.update(additional_params)
        
        # Build query string
        query_string = urlencode(params)
        
        # Append to live link
        separator = "&" if "?" in live_link else "?"
        entry_url = f"{live_link}{separator}{query_string}"
        
        # Validate length (Cint requires < 1999 characters)
        if len(entry_url) >= 1999:
            logger.warning(f"Entry link exceeds 1999 characters: {len(entry_url)}")
        
        return entry_url

    # ============================================
    # Local Data Queries
    # ============================================

    async def get_active_opportunities(self, limit: int = 100) -> List[CintOpportunity]:
        """
        Get active opportunities from local MongoDB cache

        Args:
            limit: Maximum number to return

        Returns:
            List of active CintOpportunity objects
        """
        if not self.cint_surveys_collection:
            return []
        
        opportunities = []
        
        try:
            cursor = self.cint_surveys_collection.find(
                {
                    "is_active": True,
                    "is_live": True,
                    "message_reason": {"$ne": "deactivated"}
                }
            ).limit(limit)
            
            for doc in cursor:
                opportunities.append(CintOpportunity(**doc))
            
        except Exception as e:
            logger.error(f"Error querying active opportunities: {str(e)}")
        
        return opportunities

    async def get_opportunity_by_survey_id(self, survey_id: int) -> Optional[CintOpportunity]:
        """
        Get opportunity by survey ID

        Args:
            survey_id: Cint survey ID

        Returns:
            CintOpportunity or None if not found
        """
        if not self.cint_surveys_collection:
            return None
        
        try:
            doc = self.cint_surveys_collection.find_one({"survey_id": survey_id})
            if doc:
                return CintOpportunity(**doc)
        except Exception as e:
            logger.error(f"Error querying opportunity {survey_id}: {str(e)}")
        
        return None

    async def get_entry_link_by_survey_id(self, survey_id: int) -> Optional[SupplierLink]:
        """
        Get entry link by survey ID from local cache

        Args:
            survey_id: Cint survey ID

        Returns:
            SupplierLink or None if not found
        """
        if not self.cint_entry_links_collection:
            return None
        
        try:
            doc = self.cint_entry_links_collection.find_one({"survey_id": survey_id})
            if doc:
                return SupplierLink(**doc)
        except Exception as e:
            logger.error(f"Error querying entry link for survey {survey_id}: {str(e)}")
        
        return None

    def get_surveys(
        self,
        min_loi: Optional[int] = None,
        max_loi: Optional[int] = None,
        min_cpi: Optional[float] = None,
        country: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        Get filtered Cint surveys from MongoDB cache

        Args:
            min_loi: Minimum Length of Interview (minutes)
            max_loi: Maximum Length of Interview (minutes)
            min_cpi: Minimum Cost Per Completion ($)
            country: Filter by country code
            page: Page number (1-indexed)
            page_size: Results per page

        Returns:
            Dict with surveys list, total count, and metadata
        """
        if self.cint_surveys_collection is None:
            return {
                "success": False,
                "surveys": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "message": "Surveys collection not available"
            }
        
        try:
            # Build query filter
            filter_query = {"is_active": True}
            
            # Apply LOI filters
            if max_loi is not None:
                filter_query["length_of_interview"] = {"$lte": max_loi}
            if min_loi is not None:
                if "length_of_interview" in filter_query:
                    filter_query["length_of_interview"]["$gte"] = min_loi
                else:
                    filter_query["length_of_interview"] = {"$gte": min_loi}
            
            # Apply CPI filter
            if min_cpi is not None:
                filter_query["payout"] = {"$gte": min_cpi}
            
            # Apply country filter
            if country:
                filter_query["country_language"] = {"$regex": f"^{country}", "$options": "i"}
            
            # Get total count
            total = self.cint_surveys_collection.count_documents(filter_query)
            
            # Calculate pagination
            skip = (page - 1) * page_size
            
            # Fetch surveys with sorting
            surveys_cursor = self.cint_surveys_collection.find(filter_query).sort(
                "_id", -1
            ).skip(skip).limit(page_size)
            
            surveys = []
            for doc in surveys_cursor:
                # Remove MongoDB _id if present to avoid serialization issues
                if "_id" in doc:
                    del doc["_id"]
                surveys.append(doc)
            
            return {
                "success": True,
                "surveys": surveys,
                "total": total,
                "page": page,
                "page_size": page_size,
                "filtered": min_loi is not None or max_loi is not None or min_cpi is not None or country is not None,
            }
        
        except Exception as e:
            logger.error(f"Error fetching surveys: {str(e)}")
            return {
                "success": False,
                "surveys": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "error": str(e)
            }
