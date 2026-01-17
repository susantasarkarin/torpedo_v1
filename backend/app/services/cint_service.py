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
    # Survey Filter Settings (same as CPX)
    # ============================================

    def get_filter_settings(self) -> Dict[str, Any]:
        """
        Get survey filter settings from Settings database.
        Uses the same settings as CPX from torpedo_settings.app_settings.
        
        Returns:
            Dict with filter settings (max_loi, min_cpi, deletion_period_days)
        """
        try:
            # Connect to torpedo_settings database
            MONGO_URI = os.getenv("MONGO_URI")
            if MONGO_URI:
                mongo_client = MongoClient(MONGO_URI)
                settings_db = mongo_client["torpedo_settings"]
                app_settings = settings_db["app_settings"]
                
                stored = app_settings.find_one({"_id": "survey_filters"})
                if stored and "data" in stored:
                    return stored["data"]
        except Exception as e:
            logger.warning(f"Could not read survey filter settings: {e}")
        
        # Default settings
        return {
            "max_loi": 20,  # Maximum 20 minutes
            "min_cpi": 1.0,  # Minimum $1.00 payout
            "min_incidence": 60,  # Minimum 60% conversion rate (bid_incidence)
            "deletion_period_days": 7,
        }

    def _apply_filters(self, survey_data: Dict[str, Any]) -> bool:
        """
        Apply user-configured filters to survey.
        Same logic as CPX: only store surveys that pass the filter.
        
        Args:
            survey_data: Survey data dict with loi, payout, and bid_incidence fields
            
        Returns:
            True if survey passes filters (should be stored), False otherwise
        """
        filter_settings = self.get_filter_settings()
        max_loi = filter_settings.get("max_loi", 20)
        min_cpi = filter_settings.get("min_cpi", 1.0)
        min_incidence = filter_settings.get("min_incidence", 60)
        
        # Get LOI - use length_of_interview primarily
        loi = survey_data.get("length_of_interview") or survey_data.get("bid_length_of_interview") or 0
        # Ensure LOI is numeric
        if isinstance(loi, str):
            try:
                loi = float(loi)
            except:
                loi = 0
        
        # Get payout - check multiple field names
        payout = survey_data.get("payout", 0)
        if not payout and "revenue_per_interview" in survey_data:
            rpi = survey_data["revenue_per_interview"]
            if isinstance(rpi, dict):
                payout = rpi.get("value", 0)
            elif isinstance(rpi, (int, float)):
                payout = rpi
        # Ensure payout is numeric
        if isinstance(payout, str):
            try:
                payout = float(payout)
            except:
                payout = 0
        
        # Get conversion rate - try bid_incidence first, then incidence_rate
        incidence = survey_data.get("bid_incidence") or survey_data.get("incidence_rate", 0)
        if isinstance(incidence, str):
            try:
                incidence = float(incidence)
            except:
                incidence = 0
        
        # Filter: LOI must be <= max_loi (skip if LOI is 0, meaning not provided)
        if loi > 0 and loi > max_loi:
            logger.debug(f"Survey {survey_data.get('survey_id')} filtered out: LOI {loi} > {max_loi}")
            return False
        
        # Filter: payout must be >= min_cpi
        if payout < min_cpi:
            logger.debug(f"Survey {survey_data.get('survey_id')} filtered out: payout ${payout} < ${min_cpi}")
            return False
        
        # Filter: incidence must be >= min_incidence (skip if incidence is 0, meaning not provided)
        if incidence > 0 and incidence < min_incidence:
            logger.debug(f"Survey {survey_data.get('survey_id')} filtered out: incidence {incidence}% < {min_incidence}%")
            return False
        
        return True

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
            # 404 often means the endpoint URL is wrong or subscription needs different method
            if e.response.status_code == 404:
                logger.warning(f"Cint subscription endpoint not found (404) - verify API endpoint and supplier code: {self.supplier_code}")
            else:
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
            # 404 is expected if subscription doesn't exist yet
            if e.response.status_code == 404:
                logger.debug(f"Subscription not found for {self.supplier_code} (will be created on first webhook)")
            else:
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
                
                # Normalize fields for consistent filtering
                # LOI: use bid_length_of_interview as primary, fallback to length_of_interview
                if "bid_length_of_interview" in opp_data and opp_data["bid_length_of_interview"]:
                    opp_data["length_of_interview"] = opp_data["bid_length_of_interview"]
                
                # Payout: extract value from revenue_per_interview object if present
                if "revenue_per_interview" in opp_data and isinstance(opp_data["revenue_per_interview"], dict):
                    opp_data["payout"] = opp_data["revenue_per_interview"].get("value", 0)
                elif "revenue_per_interview" in opp_data and isinstance(opp_data["revenue_per_interview"], (int, float)):
                    opp_data["payout"] = opp_data["revenue_per_interview"]
                
                # Parse to Pydantic model
                opportunity = CintOpportunity(**opp_data)
                
                # Determine if survey is active
                opportunity.is_active = opportunity.is_live and opportunity.message_reason != "deactivated"
                
                # Store ALL surveys without filtering during ingestion
                # Filters are now applied only during display/routing, not during ingestion
                # This allows us to keep a complete inventory and apply dynamic filters
                
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
        if self.cint_surveys_collection is None:
            return
        
        query = {"survey_id": opportunity.survey_id}
        update = {
            "$set": opportunity.dict(exclude={"id"}, exclude_none=False),
            # Set created_at and click tracking fields only on first insert
            # click_count is incremented by allocation service when user is routed to survey
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "click_count": 0,
                "last_clicked_at": None
            },
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
        if self.cint_entry_links_collection is None:
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
        if self.cint_surveys_collection is None:
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
        if self.cint_surveys_collection is None:
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
        if self.cint_entry_links_collection is None:
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
        apply_default_filters: bool = True,
    ) -> Dict[str, Any]:
        """
        Get filtered Cint surveys from MongoDB cache.
        
        Filters are applied at display time (not during ingestion) to allow
        for dynamic filtering without missing webhook updates.

        Args:
            min_loi: Minimum Length of Interview (minutes)
            max_loi: Maximum Length of Interview (minutes) - defaults to saved max_loi setting
            min_cpi: Minimum Cost Per Completion ($) - defaults to saved min_cpi setting
            country: Filter by country code
            page: Page number (1-indexed)
            page_size: Results per page
            apply_default_filters: If True, apply saved filter settings as defaults

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
        
        # Apply default filters from saved settings if not explicitly provided
        filter_settings = self.get_filter_settings()
        if apply_default_filters:
            if max_loi is None:
                max_loi = filter_settings.get("max_loi", 20)
            if min_cpi is None:
                min_cpi = filter_settings.get("min_cpi", 1.0)
        
        try:
            # Build query filter - only show active/live surveys
            filter_query = {
                "$or": [
                    {"is_active": True},
                    {"is_live": True, "message_reason": {"$ne": "deactivated"}}
                ]
            }
            
            # Apply LOI filters - check both normalized and original fields
            if max_loi is not None or min_loi is not None:
                loi_conditions = []
                loi_filter = {}
                if max_loi is not None:
                    loi_filter["$lte"] = max_loi
                if min_loi is not None:
                    loi_filter["$gte"] = min_loi
                
                # Check both length_of_interview and bid_length_of_interview fields
                loi_conditions.append({"length_of_interview": loi_filter})
                loi_conditions.append({"bid_length_of_interview": loi_filter})
                
                if "$and" not in filter_query:
                    filter_query["$and"] = []
                filter_query["$and"].append({"$or": loi_conditions})
            
            # Apply CPI filter
            effective_min_cpi = min_cpi if min_cpi is not None else filter_settings.get("min_cpi", 1.0)
            cpi_conditions = [
                {"payout": {"$gte": effective_min_cpi}},
                {"revenue_per_interview.value": {"$gte": effective_min_cpi}}
            ]
            if "$and" not in filter_query:
                filter_query["$and"] = []
            filter_query["$and"].append({"$or": cpi_conditions})
            
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

    def filter_and_delete_surveys(
        self,
        max_loi: int = None,
        min_cpi: float = None,
    ) -> Dict[str, Any]:
        """
        Re-apply filter settings to existing CINT surveys.
        
        This is used when filter settings are changed to clean up
        surveys that no longer meet the new criteria.
        
        Uses the same filter logic as during webhook ingestion:
        - Surveys are deleted if: LOI > max_loi OR CPI < min_cpi
        - If max_loi/min_cpi not provided, reads from settings DB
        
        Args:
            max_loi: Maximum Length of Interview (minutes). If None, reads from settings.
            min_cpi: Minimum Cost Per Interview ($). If None, reads from settings.
        
        Returns:
            Dict with deletion statistics
        """
        if self.cint_surveys_collection is None:
            return {
                "success": False,
                "message": "Surveys collection not available",
                "deleted_count": 0
            }
        
        try:
            # Get filter settings if not provided
            if max_loi is None or min_cpi is None:
                filter_settings = self.get_filter_settings()
                if max_loi is None:
                    max_loi = filter_settings.get("max_loi", 20)
                if min_cpi is None:
                    min_cpi = filter_settings.get("min_cpi", 1.0)
            
            # Count surveys before deletion
            total_before = self.cint_surveys_collection.count_documents({})
            
            # Build delete query for surveys that don't meet criteria
            # Delete if: LOI > max_loi OR CPI < min_cpi
            delete_query = {
                "$or": [
                    # LOI exceeds max (check both field names)
                    {"length_of_interview": {"$gt": max_loi}},
                    {"bid_length_of_interview": {"$gt": max_loi}},
                    # CPI below min (check both field names)
                    {"$and": [
                        {"payout": {"$lt": min_cpi}},
                        {"payout": {"$exists": True, "$ne": None}}
                    ]},
                    {"$and": [
                        {"revenue_per_interview.value": {"$lt": min_cpi}},
                        {"revenue_per_interview.value": {"$exists": True, "$ne": None}}
                    ]},
                ]
            }
            
            # Count surveys to be deleted
            to_delete = self.cint_surveys_collection.count_documents(delete_query)
            
            # Perform deletion
            result = self.cint_surveys_collection.delete_many(delete_query)
            
            # Count surveys after deletion
            total_after = self.cint_surveys_collection.count_documents({})
            
            logger.info(f"Survey filter applied: max_loi={max_loi}, min_cpi={min_cpi}")
            logger.info(f"Deleted {result.deleted_count} surveys. Before: {total_before}, After: {total_after}")
            
            return {
                "success": True,
                "message": f"Deleted {result.deleted_count} surveys that did not meet criteria (LOI > {max_loi} min or CPI < ${min_cpi})",
                "deleted_count": result.deleted_count,
                "total_before": total_before,
                "total_after": total_after,
                "criteria": {
                    "max_loi": max_loi,
                    "min_cpi": min_cpi
                }
            }
        
        except Exception as e:
            logger.error(f"Error filtering surveys: {str(e)}")
            return {
                "success": False,
                "message": str(e),
                "deleted_count": 0
            }

    def cleanup_unclicked_surveys(self, days: int = 3) -> int:
        """
        Delete CINT surveys that have received 0 clicks and are older than specified days.
        
        Click-based cleanup logic:
        - Surveys with click_count > 0 are kept indefinitely (or until separate expiry)
        - Surveys with click_count == 0 AND created_at > X days ago are deleted
        
        Args:
            days: Number of days after which unclicked surveys should be deleted (default: 3)
            
        Returns:
            Number of surveys deleted
        """
        if self.cint_surveys_collection is None:
            return 0
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Delete surveys where:
            # 1. click_count is 0, null, or doesn't exist AND
            # 2. created_at is older than cutoff_date
            result = self.cint_surveys_collection.delete_many({
                "$and": [
                    {
                        "$or": [
                            {"click_count": {"$exists": False}},
                            {"click_count": None},
                            {"click_count": 0}
                        ]
                    },
                    {
                        "$or": [
                            {"created_at": {"$lt": cutoff_date}},
                            # Fallback for legacy surveys without created_at
                            {
                                "$and": [
                                    {"created_at": {"$exists": False}},
                                    {"received_at": {"$lt": cutoff_date}}
                                ]
                            }
                        ]
                    }
                ]
            })
            
            deleted_count = result.deleted_count
            if deleted_count > 0:
                logger.info(f"🗑️  Cleaned up {deleted_count} unclicked CINT surveys older than {days} days")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up unclicked surveys: {e}")
            return 0
