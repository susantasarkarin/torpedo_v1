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
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
import logging
import base64
from pymongo.collection import Collection

try:
    from ...database import get_client
except ImportError:
    from database import get_client

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


# ============================================
# Cint Validation Error Codes (V01-V19)
# ============================================

CINT_VALIDATION_ERRORS = {
    "V01": "Invalid survey number - survey does not exist or is not accessible",
    "V02": "Invalid supplier code - supplier not recognized",
    "V03": "Invalid API key - authentication failed",
    "V04": "Survey not live - survey is closed or paused",
    "V05": "Quota exceeded - no more respondents needed for this quota",
    "V06": "Survey qualifications not met - respondent does not qualify",
    "V07": "Quota full - survey has reached maximum completions",
    "V08": "Invalid respondent ID - PID format not accepted",
    "V09": "Duplicate respondent - PID has already completed this survey",
    "V10": "Invalid session - session has expired or is invalid",
    "V11": "Survey group conflict - respondent already in survey group",
    "V12": "Invalid country/language - respondent locale not supported",
    "V13": "Quality termination - respondent failed quality checks",
    "V14": "Security termination - fraud or bot detection triggered",
    "V15": "Invalid redirect URL - callback URL format invalid",
    "V16": "Rate limit exceeded - too many requests, retry later",
    "V17": "Invalid subscription configuration - missing required fields",
    "V18": "Webhook delivery failed - callback URL unreachable",
    "V19": "Internal server error - Cint platform issue, retry later",
}


class CintValidationError(Exception):
    """
    Exception for Cint API validation errors (V01-V19).
    Maps Cint error codes to human-readable messages.
    """
    
    def __init__(self, error_code: str, raw_message: str = None, status_code: int = 400):
        self.error_code = error_code
        self.raw_message = raw_message
        self.status_code = status_code
        self.message = CINT_VALIDATION_ERRORS.get(
            error_code, 
            f"Unknown Cint error ({error_code}): {raw_message or 'No details provided'}"
        )
        super().__init__(self.message)
    
    def __str__(self):
        return f"[{self.error_code}] {self.message}"
    
    @classmethod
    def from_response(cls, response_data: dict, status_code: int = 400) -> "CintValidationError":
        """Create CintValidationError from Cint API response."""
        error_code = response_data.get("error_code") or response_data.get("ErrorCode") or "V19"
        raw_message = response_data.get("message") or response_data.get("Message") or str(response_data)
        return cls(error_code, raw_message, status_code)


class CintService:
    """Service to interact with Cint API (Opportunities & Entry Links)"""
    
    # API Endpoints
    SANDBOX_BASE_URL = "https://sandbox.techops.engineering/"
    PRODUCTION_BASE_URL = "https://api.samplicio.us/"
    
    # Supply Integration Endpoints
    OPPORTUNITIES_ENDPOINT = "supply/opportunities/v1/subscriptions/{supplier_code}"
    ENTRY_LINKS_ENDPOINT = "Supply/v1/SupplierLinks"
    RESPONDENT_OUTCOMES_ENDPOINT = "supply/respondent-outcomes/v2/subscriptions/{supplier_code}"
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_STATUS_CODES = {429, 502, 503, 504}  # Retry on rate limit and server errors
    NO_RETRY_STATUS_CODES = {400, 401, 403}    # Never retry on client errors
    
    # Legacy Fulcrum/Samplicio API Endpoints (for polling)
    LEGACY_OFFERWALL_ENDPOINT = "Supply/v1/Surveys/AllOfferwall/{supplier_code}"
    LEGACY_SURVEY_DETAIL_ENDPOINT = "Supply/v1/Surveys/BySurveyNumber/{survey_number}/{supplier_code}"
    
    def __init__(
        self,
        api_key: str,
        supplier_code: str,
        environment: str = "sandbox",
        cint_surveys_collection: Optional[Collection] = None,
        cint_entry_links_collection: Optional[Collection] = None,
        cint_settings_collection: Optional[Collection] = None,
        cint_outcomes_collection: Optional[Collection] = None,
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
            cint_outcomes_collection: MongoDB collection for cint_research.cint_respondent_outcomes
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
        self.cint_outcomes_collection = cint_outcomes_collection

        # HTTP client
        self.client = httpx.AsyncClient(timeout=api_timeout)

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """
        Make HTTP request with exponential backoff retry logic.
        
        Retries on: 429 (Rate Limited), 502, 503, 504 (Server Errors)
        Never retries on: 400, 401, 403 (Client Errors)
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Request URL
            **kwargs: Additional arguments for httpx request
            
        Returns:
            httpx.Response object
            
        Raises:
            CintValidationError: For validation errors (V01-V19)
            httpx.HTTPStatusError: For non-retryable HTTP errors
        """
        import asyncio
        
        last_exception = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self.client.request(method, url, **kwargs)
                
                # Check if we should retry
                if response.status_code in self.RETRY_STATUS_CODES:
                    wait_time = (2 ** attempt)  # 1s, 2s, 4s
                    logger.warning(
                        f"Cint API returned {response.status_code}, "
                        f"retrying in {wait_time}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                
                # Check for non-retryable errors
                if response.status_code in self.NO_RETRY_STATUS_CODES:
                    try:
                        error_data = response.json()
                        raise CintValidationError.from_response(error_data, response.status_code)
                    except (ValueError, KeyError):
                        response.raise_for_status()
                
                response.raise_for_status()
                return response
                
            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code in self.NO_RETRY_STATUS_CODES:
                    raise
                if e.response.status_code not in self.RETRY_STATUS_CODES:
                    raise
                    
            except Exception as e:
                last_exception = e
                logger.error(f"Request error (attempt {attempt + 1}): {str(e)}")
        
        if last_exception:
            raise last_exception
        raise Exception(f"Request failed after {self.MAX_RETRIES} attempts")

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
                settings_db = get_client()["torpedo_settings"]
                app_settings = settings_db["app_settings"]
                
                # Settings are stored directly at _id='survey_filters' without data wrapper
                stored = app_settings.find_one({"_id": "survey_filters"})
                if stored:
                    return {
                        "max_loi": stored.get("max_loi", 20),
                        "min_cpi": stored.get("min_cpi", 1.0),
                        "min_incidence": stored.get("min_incidence", 60),
                        "deletion_period_days": stored.get("deletion_period_days", 7),
                    }
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

    def sync_active_status_by_filters(self) -> Dict[str, Any]:
        """
        Apply filter settings to ALL surveys and mark them as active/inactive.
        Surveys that pass the filter criteria get is_active_in_pool=true,
        others get is_active_in_pool=false.
        
        This is similar to CPX's sync_active_status_by_filters method.
        
        Returns:
            Dictionary with counts of active/inactive surveys
        """
        if self.cint_surveys_collection is None:
            return {
                "success": False,
                "message": "MongoDB collection not configured",
                "total": 0,
                "active": 0,
                "inactive": 0
            }
        
        try:
            # Get current filter settings
            filter_settings = self.get_filter_settings()
            min_cpi = filter_settings.get("min_cpi", 1.0)
            
            logger.info(f"📊 Syncing CINT active status with filters: min_cpi={min_cpi}")
            
            # Count ALL surveys first
            total_surveys = self.cint_surveys_collection.count_documents({})
            
            # Build query for surveys that PASS the filters (active surveys)
            # Surveys need: is_live=True and payout > min_cpi
            active_query = {
                "$and": [
                    {"$or": [
                        {"is_live": True},
                        {"is_live": {"$exists": False}}
                    ]},
                    {"$or": [
                        {"payout": {"$gt": min_cpi}},
                        {"revenue_per_interview.value": {"$gt": str(min_cpi)}},
                        # Handle numeric revenue_per_interview.value
                        {"$expr": {"$gt": [{"$toDouble": {"$ifNull": ["$revenue_per_interview.value", "0"]}}, min_cpi]}}
                    ]}
                ]
            }
            
            # Yield-deactivated surveys (survey_status="inactive" in cint_metrics,
            # set either manually via PATCH /surveys/{id}/yield-status or by the
            # low-conversion auto-deactivation in the redirect callback) must
            # SURVIVE this re-sync. Previously this blanket $set flipped them
            # back into the pool on every sync cycle, silently undoing every
            # yield decision. Reactivation happens only through the yield layer
            # (which clears survey_status), never through the filter sync.
            yield_deactivated_ids: set = set()
            try:
                metrics_collection = \
                    self.cint_surveys_collection.database["cint_metrics"]
                yield_deactivated_ids = {
                    doc["survey_id"]
                    for doc in metrics_collection.find(
                        {"survey_status": "inactive"}, {"survey_id": 1})
                }
            except Exception as e:
                logger.warning(f"Could not load yield-deactivated ids: {e}")
            if yield_deactivated_ids:
                # survey_id is stored as int in cint_surveys but as str in
                # cint_metrics on some paths — exclude both representations.
                excluded: list = []
                for sid in yield_deactivated_ids:
                    excluded.append(sid)
                    if isinstance(sid, str) and sid.isdigit():
                        excluded.append(int(sid))
                    elif isinstance(sid, int):
                        excluded.append(str(sid))
                active_query = {"$and": [active_query,
                                         {"survey_id": {"$nin": excluded}}]}
                logger.info(f"Yield guard: {len(yield_deactivated_ids)} "
                            f"deactivated surveys excluded from pool re-sync")

            # Mark all surveys matching active_query as is_active_in_pool=true
            active_result = self.cint_surveys_collection.update_many(
                active_query,
                {"$set": {"is_active_in_pool": True, "updated_at": datetime.now(timezone.utc)}}
            )
            
            # Mark all OTHER surveys as is_active_in_pool=false
            inactive_result = self.cint_surveys_collection.update_many(
                {"$nor": [active_query]},
                {"$set": {"is_active_in_pool": False, "updated_at": datetime.now(timezone.utc)}}
            )
            
            # Also deactivate quota-exhausted surveys (total_remaining == 0)
            quota_full_result = self.cint_surveys_collection.update_many(
                {"total_remaining": 0, "is_active_in_pool": True},
                {"$set": {
                    "is_active_in_pool": False,
                    "updated_at": datetime.now(timezone.utc),
                    "deactivation_reason": "quota_full",
                }}
            )
            if quota_full_result.modified_count:
                logger.info(f"Deactivated {quota_full_result.modified_count} quota-exhausted surveys")

            # Get actual counts after update
            actual_active = self.cint_surveys_collection.count_documents({"is_active_in_pool": True})
            actual_inactive = self.cint_surveys_collection.count_documents({"is_active_in_pool": False})

            logger.info(f"✅ CINT active status synced: {actual_active} active, {actual_inactive} inactive (total: {total_surveys})")
            
            return {
                "success": True,
                "message": f"Synced active status for {total_surveys} surveys",
                "total": total_surveys,
                "active": actual_active,
                "inactive": actual_inactive,
                "filters_applied": {
                    "min_cpi": min_cpi,
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error syncing CINT active status: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "total": 0,
                "active": 0,
                "inactive": 0
            }

    # ============================================
    # Legacy Fulcrum API (Polling)
    # ============================================

    async def fetch_surveys_from_offerwall(self) -> Dict[str, Any]:
        """
        Fetch surveys from legacy Fulcrum/Samplicio AllOfferwall API.
        
        This is used when the newer Opportunities webhook API is not available.
        API: GET /Supply/v1/Surveys/AllOfferwall/{SupplierCode}?key={APIKey}
        
        Returns:
            Dict with success status and list of surveys
        """
        url = f"{self.PRODUCTION_BASE_URL}{self.LEGACY_OFFERWALL_ENDPOINT.format(supplier_code=self.supplier_code)}"
        url_with_key = f"{url}?key={self.api_key}"
        
        try:
            logger.info(f"Fetching surveys from legacy Fulcrum API for supplier {self.supplier_code}")
            
            response = await self.client.get(url_with_key)
            response.raise_for_status()
            
            data = response.json()
            surveys = data.get("Surveys", [])
            
            logger.info(f"Fetched {len(surveys)} surveys from Fulcrum AllOfferwall API")
            
            return {
                "success": True,
                "surveys": surveys,
                "total": len(surveys),
                "source": "fulcrum_offerwall"
            }
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Fulcrum API error: {e.response.status_code} - {e.response.text[:200]}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Fulcrum API fetch failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def sync_surveys_from_offerwall(self, apply_filters: bool = True) -> Dict[str, Any]:
        """
        Fetch surveys from legacy API and upsert to MongoDB.
        
        Args:
            apply_filters: If True, only store surveys that pass filter criteria
            
        Returns:
            Dict with sync stats
        """
        result = await self.fetch_surveys_from_offerwall()
        
        if not result.get("success"):
            return result
        
        surveys = result.get("surveys", [])
        stats = {
            "fetched": len(surveys),
            "stored": 0,
            "filtered_out": 0,
            "errors": 0
        }
        
        if self.cint_surveys_collection is None:
            return {"success": False, "error": "MongoDB collection not configured"}
        
        for survey in surveys:
            try:
                # Map Fulcrum fields to our internal format
                survey_data = self._map_fulcrum_survey(survey)
                
                # Apply filters if enabled
                if apply_filters and not self._apply_filters(survey_data):
                    stats["filtered_out"] += 1
                    continue
                
                # Upsert to MongoDB
                self._upsert_fulcrum_survey(survey_data)
                stats["stored"] += 1
                
            except Exception as e:
                logger.error(f"Error processing Fulcrum survey {survey.get('SurveyNumber')}: {e}")
                stats["errors"] += 1
        
        logger.info(f"Fulcrum sync complete: {stats['stored']} stored, {stats['filtered_out']} filtered, {stats['errors']} errors")
        
        return {
            "success": True,
            "stats": stats,
            "source": "fulcrum_offerwall"
        }

    def _map_fulcrum_survey(self, survey: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map Fulcrum API survey fields to our internal format.
        
        Fulcrum fields: SurveyNumber, SurveyName, CountryLanguageID, BidLengthOfInterview,
                        BidIncidence, CPI, Conversion, EPC, etc.
        """
        # Get payout - Fulcrum uses CPI or QuotaCPI
        cpi = survey.get("CPI") or survey.get("QuotaCPI") or 0
        if isinstance(cpi, str):
            try:
                cpi = float(cpi)
            except:
                cpi = 0
        
        # Get LOI
        loi = survey.get("BidLengthOfInterview") or survey.get("LengthOfInterview") or 0
        
        # Get incidence/conversion
        incidence = survey.get("BidIncidence") or survey.get("Conversion") or 0
        
        # Get entry link
        live_link = survey.get("LiveLink") or survey.get("SurveyLink") or ""
        
        return {
            "survey_id": survey.get("SurveyNumber"),
            "survey_name": survey.get("SurveyName") or f"Survey {survey.get('SurveyNumber')}",
            "country_language": survey.get("CountryLanguageID") or survey.get("Country"),
            "length_of_interview": loi,
            "payout": cpi,
            "bid_incidence": incidence,
            "epc": survey.get("EPC") or 0,
            "conversion": survey.get("Conversion") or 0,
            "is_live": True,
            "is_active": True,
            "message_reason": None,
            "live_link": live_link,
            "test_link": survey.get("TestLink") or "",
            "study_type": survey.get("StudyType"),
            "industry": survey.get("Industry"),
            "quota_remaining": survey.get("Quota", {}).get("TotalRemaining") if isinstance(survey.get("Quota"), dict) else survey.get("TotalRemaining") or 1000,
            "source_api": "fulcrum_offerwall",
            "raw_data": survey,  # Store original for debugging
            "updated_at": datetime.now(timezone.utc),
        }

    def _upsert_fulcrum_survey(self, survey_data: Dict[str, Any]) -> None:
        """Insert or update Fulcrum survey in MongoDB"""
        if self.cint_surveys_collection is None:
            return
        
        query = {"survey_id": survey_data["survey_id"]}
        update = {
            "$set": survey_data,
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "click_count": 0,
                "last_clicked_at": None,
                "is_active_in_pool": False
            },
        }
        
        self.cint_surveys_collection.update_one(query, update, upsert=True)

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
            # Default: accept ALL countries (empty filter or no country_language restriction)
            # Full list of Cint country_language codes for global coverage:
            {"country_language": {"in": [
                # English
                "eng_us", "eng_gb", "eng_ca", "eng_au", "eng_nz", "eng_ie", "eng_za", "eng_in", "eng_ph", "eng_sg", "eng_hk", "eng_my",
                # Spanish
                "spa_mx", "spa_es", "spa_ar", "spa_co", "spa_cl", "spa_pe", "spa_ve", "spa_ec", "spa_gt", "spa_cu", "spa_bo", "spa_py", "spa_uy", "spa_pa", "spa_cr", "spa_pr", "spa_ni", "spa_hn", "spa_sv",
                # Portuguese
                "por_br", "por_pt",
                # French
                "fra_fr", "fra_ca", "fra_be", "fra_ch",
                # German
                "deu_de", "deu_at", "deu_ch",
                # Italian
                "ita_it", "ita_ch",
                # Dutch
                "nld_nl", "nld_be",
                # Polish
                "pol_pl",
                # Russian
                "rus_ru",
                # Japanese
                "jpn_jp",
                # Korean
                "kor_kr",
                # Chinese
                "zho_cn", "zho_tw", "zho_hk", "zho_sg",
                # Arabic
                "ara_sa", "ara_ae", "ara_eg", "ara_ma",
                # Turkish
                "tur_tr",
                # Thai
                "tha_th",
                # Indonesian
                "ind_id",
                # Vietnamese
                "vie_vn",
                # Hindi
                "hin_in",
                # Swedish
                "swe_se",
                # Norwegian
                "nor_no",
                # Danish
                "dan_dk",
                # Finnish
                "fin_fi",
                # Czech
                "ces_cz",
                # Hungarian
                "hun_hu",
                # Romanian
                "ron_ro",
                # Greek
                "ell_gr",
                # Hebrew
                "heb_il",
                # Malay
                "msa_my"
            ]}}
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
    # Respondent Outcomes Subscription (v2)
    # ============================================

    async def create_outcomes_subscription(
        self, config: OutcomeSubscriptionConfig
    ) -> Dict[str, Any]:
        """
        Create or update respondent outcomes subscription.
        
        Cint will send outcome webhooks when respondent sessions complete/terminate.
        
        Args:
            config: Subscription configuration with callback URL and filters
            
        Returns:
            Response from Cint API
        """
        url = f"{self.base_url}{self.RESPONDENT_OUTCOMES_ENDPOINT.format(supplier_code=self.supplier_code)}"
        
        payload = {
            "callback": config.callback_url,
            "outcome_filters": config.outcome_filters if config.outcome_filters else [],
        }
        
        try:
            response = await self._request_with_retry(
                "POST",
                url,
                json=payload,
                headers=self._get_headers(),
            )
            
            logger.info(f"Outcomes subscription created for {self.supplier_code}")
            return {"success": True, "data": response.json()}
        
        except CintValidationError as e:
            logger.error(f"Cint validation error: {e}")
            return {"success": False, "error": str(e), "error_code": e.error_code}
        except httpx.HTTPStatusError as e:
            logger.error(f"Cint outcomes subscription error: {e.response.status_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            logger.error(f"Cint outcomes subscription failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_outcomes_subscription(self) -> Dict[str, Any]:
        """Get current respondent outcomes subscription status."""
        url = f"{self.base_url}{self.RESPONDENT_OUTCOMES_ENDPOINT.format(supplier_code=self.supplier_code)}"
        
        try:
            response = await self._request_with_retry(
                "GET",
                url,
                headers=self._get_headers(),
            )
            
            logger.info(f"Retrieved outcomes subscription for {self.supplier_code}")
            return {"success": True, "data": response.json()}
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Outcomes subscription not found for {self.supplier_code}")
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_outcomes_subscription(self) -> Dict[str, Any]:
        """Delete respondent outcomes subscription."""
        url = f"{self.base_url}{self.RESPONDENT_OUTCOMES_ENDPOINT.format(supplier_code=self.supplier_code)}"
        
        try:
            response = await self._request_with_retry(
                "DELETE",
                url,
                headers=self._get_headers(),
            )
            
            logger.info(f"Outcomes subscription deleted for {self.supplier_code}")
            return {"success": True}
        
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================
    # Respondent Outcome Processing
    # ============================================

    # Status code mappings for marketplace_status and client_status
    MARKETPLACE_STATUS_MAP = {
        10: "complete",
        20: "terminate",
        30: "over_quota",
        40: "quality_terminate",
        50: "survey_closed",
    }
    
    CLIENT_STATUS_MAP = {
        10: "complete",
        20: "terminate",
        30: "over_quota",
        40: "quality_terminate",
    }

    async def process_respondent_outcome(
        self, outcome_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process respondent outcome from webhook.
        
        Per Cint API spec:
        - Multiple updates may be received per respondent
        - Always store the LATEST outcome only (by last_date)
        - Map marketplace_status and client_status to final status
        
        Args:
            outcome_data: Webhook payload with respondent outcome
            
        Returns:
            Processing result with stored outcome details
        """
        try:
            # Parse to Pydantic model for validation
            outcome = RespondentOutcome(**outcome_data)
            
            # Determine final status from marketplace_status
            final_status = self.MARKETPLACE_STATUS_MAP.get(
                outcome.marketplace_status, 
                f"unknown_{outcome.marketplace_status}"
            )
            
            # Build document for storage
            outcome_doc = {
                "respondent_id": outcome.respondent_id,
                "session_id": outcome.session_id,
                "panelist_id": outcome.panelist_id,
                "parent_session_id": outcome.parent_session_id,
                "survey_id": outcome.survey_id,
                "marketplace_status": outcome.marketplace_status,
                "client_status": outcome.client_status,
                "final_status": final_status,
                "entry_date": outcome.entry_date,
                "last_date": outcome.last_date,
                "rpi": outcome.rpi,
                "payout": outcome.rpi.get("value") if outcome.rpi else None,
                "currency": outcome.rpi.get("currency_code") if outcome.rpi else "USD",
                "study_type": outcome.study_type,
                "received_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            
            # Upsert to MongoDB - use session_id as unique key
            # Only update if this outcome is newer (by last_date)
            if self.cint_outcomes_collection is not None:
                existing = self.cint_outcomes_collection.find_one(
                    {"session_id": outcome.session_id}
                )
                
                if existing:
                    # Only update if newer
                    existing_last_date = existing.get("last_date")
                    if existing_last_date and outcome.last_date <= existing_last_date:
                        logger.debug(
                            f"Skipping older outcome for session {outcome.session_id}"
                        )
                        return {
                            "success": True,
                            "action": "skipped",
                            "reason": "older_outcome",
                            "session_id": outcome.session_id,
                        }
                
                # Upsert the outcome
                self.cint_outcomes_collection.update_one(
                    {"session_id": outcome.session_id},
                    {"$set": outcome_doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                    upsert=True,
                )
                
                logger.info(
                    f"Stored outcome for session {outcome.session_id}: "
                    f"status={final_status}, payout={outcome_doc.get('payout')}"
                )
            
            return {
                "success": True,
                "action": "stored",
                "session_id": outcome.session_id,
                "respondent_id": outcome.respondent_id,
                "final_status": final_status,
                "payout": outcome_doc.get("payout"),
            }
            
        except Exception as e:
            logger.error(f"Error processing respondent outcome: {str(e)}")
            return {"success": False, "error": str(e)}

    # ============================================
    # Opportunity Processing
    # ============================================

    async def process_opportunity_webhook(
        self, payload: Dict[str, Any], check_active: bool = True, auto_create_entry_links: bool = True
    ) -> List[CintOpportunity]:
        """
        Process incoming opportunities from webhook

        Args:
            payload: Webhook payload (single opportunity dict or array)
            check_active: If True, deactivate surveys with message_reason="deactivated"
            auto_create_entry_links: If True, auto-create entry links for new active surveys

        Returns:
            List of processed CintOpportunity objects
        """
        # Handle both single opportunity and array
        opportunities = payload if isinstance(payload, list) else [payload]
        
        processed = []
        entry_links_created = 0
        
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
                
                # Check if this is a new survey (for auto-creating entry links)
                is_new_survey = False
                if self.cint_surveys_collection is not None:
                    existing = self.cint_surveys_collection.find_one({"survey_id": opportunity.survey_id})
                    is_new_survey = existing is None
                
                # Store ALL surveys without filtering during ingestion
                # Filters are now applied only during display/routing, not during ingestion
                # This allows us to keep a complete inventory and apply dynamic filters
                
                # Store in MongoDB if collection provided
                if self.cint_surveys_collection is not None:
                    self._upsert_opportunity(opportunity)

                # Quota-full auto-deactivation: if total_remaining == 0, deactivate
                if (opportunity.total_remaining is not None
                        and opportunity.total_remaining == 0
                        and opportunity.is_active):
                    logger.info(
                        f"Auto-deactivating survey {opportunity.survey_id}: quota exhausted (total_remaining=0)"
                    )
                    await self._auto_deactivate_quota_full(opportunity.survey_id)

                # Dispatch AI cold-start scoring for brand-new surveys with no in-field data
                # Per Cint guide: rank new opportunities before real conversion data exists
                if is_new_survey and opportunity.is_active:
                    has_real_ir = (
                        (opportunity.conversion or 0) > 0
                        or (opportunity.bid_incidence or 0) > 0
                    )
                    if not has_real_ir:
                        try:
                            from tasks.cint_survey_scoring import score_cold_start_survey
                            score_cold_start_survey.delay(opportunity.survey_id)
                            logger.info(
                                f"Dispatched cold-start scoring for survey {opportunity.survey_id}"
                            )
                        except Exception as _scoring_err:
                            logger.debug(
                                f"Could not dispatch scoring task for {opportunity.survey_id}: "
                                f"{_scoring_err}"
                            )

                # Auto-create entry links for new active surveys
                if auto_create_entry_links and is_new_survey and opportunity.is_active:
                    try:
                        result = await self._auto_create_entry_link(opportunity.survey_id)
                        if result.get("success"):
                            entry_links_created += 1
                            logger.info(f"Auto-created entry link for survey {opportunity.survey_id}")
                    except Exception as link_err:
                        logger.warning(f"Failed to auto-create entry link for {opportunity.survey_id}: {link_err}")
                
                processed.append(opportunity)
                
            except Exception as e:
                logger.error(f"Error processing opportunity {opp_data.get('survey_id')}: {str(e)}")
                continue
        
        logger.info(f"Processed {len(processed)} opportunities (entry links created: {entry_links_created})")
        return processed

    async def _auto_create_entry_link(
        self, survey_id: int, force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Auto-create entry link for a survey.
        
        Redirect URLs are passed at entry link creation to ensure proper
        handling even when Cint rejects respondents at entry (403).
        Portal-level redirects (SR-0721) provide additional demographic params.
        
        Args:
            survey_id: Cint survey ID
            force_refresh: If True, bypass cache and fetch/create from API
        
        Returns:
            Dict with success status and SupplierLink object
        """
        # Step 1: Check local MongoDB cache first (fast)
        if not force_refresh:
            cached = await self.get_entry_link_by_survey_id(survey_id)
            if cached and cached.live_link:
                logger.debug(f"Entry link for survey {survey_id} found in cache")
                return {"success": True, "link": cached, "source": "cache"}
        
        # Step 2: Try to fetch from Cint API (may already exist)
        existing = await self.get_entry_link(survey_id)
        if existing.get("success") and existing.get("link"):
            link = existing.get("link")
            if hasattr(link, 'live_link') and link.live_link:
                logger.debug(f"Entry link for survey {survey_id} fetched from API")
                return {**existing, "source": "api_fetch"}
        
        # Step 3: Create new entry link with redirect URLs
        # These ensure proper redirect even on entry rejection (403)
        # [%PID%] and [%MID%] are Cint macros replaced at runtime
        base_url = "https://torpedo.cogentixresearch.com"
        link_config = SupplierLinkCreate(
            supplier_link_type_code="OWS",
            tracking_type_code="NONE",
            success_link=f"{base_url}/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]",
            failure_link=f"{base_url}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]",
            over_quota_link=f"{base_url}/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]",
            quality_termination_link=f"{base_url}/cint-response?status=quality_terminate&pid=[%PID%]&mid=[%MID%]",
        )
        
        result = await self.create_entry_link(survey_id, link_config)
        if result.get("success"):
            result["source"] = "created"
        return result

    def _upsert_opportunity(self, opportunity: CintOpportunity) -> None:
        """
        Insert or update opportunity in MongoDB

        Args:
            opportunity: CintOpportunity instance
        """
        if self.cint_surveys_collection is None:
            return

        # Compute testing state from completes count
        overall_completes = opportunity.overall_completes or 0
        is_testing = overall_completes < 20
        testing_sessions_remaining = max(0, 20 - overall_completes)

        opp_dict = opportunity.dict(exclude={"id"}, exclude_none=False)
        opp_dict["is_testing"] = is_testing
        opp_dict["testing_sessions_remaining"] = testing_sessions_remaining

        query = {"survey_id": opportunity.survey_id}
        update = {
            "$set": opp_dict,
            # Set created_at and click tracking fields only on first insert
            # click_count is incremented by allocation service when user is routed to survey
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "click_count": 0,
                "last_clicked_at": None,
                "is_active_in_pool": False  # Default to inactive, must be activated by sync job
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
        
        # Use by_alias=True to send PascalCase field names to Cint API
        payload = link_config.dict(exclude_none=True, by_alias=True)
        
        try:
            response = await self.client.post(
                url,
                json=payload,
                headers=self._get_headers(),
            )
            response.raise_for_status()

            # Parse response
            api_response = response.json()

            # Debug logging for response structure (use debug level to avoid log spam)
            logger.debug(f"[ENTRY LINK] Cint API response for survey {survey_id}: {json.dumps(api_response, indent=2)[:500]}")
            logger.debug(f"[ENTRY LINK] Response keys: {list(api_response.keys()) if isinstance(api_response, dict) else type(api_response)}")

            # Extract supplier link from response
            if "SupplierLink" in api_response:
                link_data = api_response["SupplierLink"]

                logger.debug(f"[ENTRY LINK] SupplierLink data keys: {list(link_data.keys())}")
                logger.debug(f"[ENTRY LINK] SupplierLink has LiveLink: {'LiveLink' in link_data}")

                # Create SupplierLink object
                supplier_link = SupplierLink(
                    survey_id=survey_id,
                    survey_number=survey_id,
                    **link_data
                )

                logger.debug(f"[ENTRY LINK] Created SupplierLink object with live_link: {supplier_link.live_link}")

                # Store in MongoDB if collection provided
                if self.cint_entry_links_collection is not None:
                    self._store_entry_link(supplier_link)

                logger.info(f"Entry link created for survey {survey_id}")
                return {"success": True, "link": supplier_link}

            logger.warning(f"[ENTRY LINK] No 'SupplierLink' key in response. Full response: {api_response}")
            return {"success": False, "error": "Invalid API response - missing SupplierLink key"}
        
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            
            # Handle 409 Conflict - entry link already exists
            # This ensures idempotency: calling create multiple times is safe
            if status_code == 409:
                logger.info(f"Entry link already exists for survey {survey_id} (409 Conflict), fetching existing")
                existing = await self.get_entry_link(survey_id)
                if existing.get("success") and existing.get("link"):
                    return {**existing, "source": "existing_409"}
                # If fetch also fails, return the original 409 error
                logger.warning(f"Failed to fetch existing entry link after 409 for survey {survey_id}")
            
            logger.error(f"Failed to create entry link: {status_code}")
            return {"success": False, "error": str(e), "status_code": status_code}
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
        
        # Use by_alias=True to send PascalCase field names to Cint API
        payload = link_config.dict(exclude_none=False, by_alias=True)
        
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
                
                # Cache the fetched entry link to MongoDB
                if self.cint_entry_links_collection is not None:
                    self._store_entry_link(supplier_link)
                    logger.info(f"Retrieved and cached entry link for survey {survey_id}")
                else:
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
            pid: Panelist ID (optional, defaults to respondent_id)
            mid: Session/Market ID (optional, auto-generated if not provided)
            **additional_params: Additional query parameters

        Returns:
            Complete entry link with all parameters
        """
        import uuid
        
        panelist_id = pid or respondent_id
        # Task: PID should be the SHA256 hash of respondent id
        import hashlib
        panelist_id = hashlib.sha256(panelist_id.encode()).hexdigest()
        
        session_mid = mid or uuid.uuid4().hex[:16]  # 16 hex chars, no dashes

        parsed = urlparse(live_link)
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))

        # Remove lowercase params if they already exist
        query_params.pop("pid", None)
        query_params.pop("mid", None)

        # Enforce expected case for Lucid/Cint
        query_params["PID"] = panelist_id
        query_params["MID"] = session_mid
        # Task: rid should also be hashed if it's the respondent id
        query_params["rid"] = panelist_id # Use the already hashed panelist_id
        query_params["cc"] = country_code

        # Add any additional parameters
        query_params.update(additional_params)

        query_string = urlencode(query_params)
        url_no_hash = urlunparse(parsed._replace(query=query_string))
        
        # Add trailing & before hashing as per Cint requirements
        url_to_hash = url_no_hash + "&"

        # --- Hash signature (REQUIRED, must be last) ---
        secret_key = os.getenv("CINT_WEBHOOK_SECRET", "")
        if secret_key:
            sig = hmac.new(
                secret_key.encode("utf-8"),
                url_to_hash.encode("utf-8"),
                hashlib.sha1
            ).digest()
            # Use URL-safe Base64 without padding as per Cint documentation
            hash_value = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
            entry_url = f"{url_to_hash}hash={hash_value}"
        else:
            entry_url = url_no_hash
        
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

    async def mark_survey_inactive(self, survey_id: int, reason: str = "404_from_cint_api") -> bool:
        """
        Mark a survey as inactive (e.g., when Cint API returns 404)
        
        This is called when:
        - Cint API returns 404 for entry link creation
        - Survey is no longer available in Cint system
        - Manual deactivation is needed
        
        Args:
            survey_id: Cint survey ID
            reason: Reason for deactivation
        
        Returns:
            True if updated, False if survey not found or error
        """
        if self.cint_surveys_collection is None:
            return False
        
        try:
            result = self.cint_surveys_collection.update_one(
                {"survey_id": survey_id},
                {
                    "$set": {
                        "is_active": False,
                        "is_live": False,
                        "deactivated_at": datetime.now(timezone.utc),
                        "deactivation_reason": reason,
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Marked survey {survey_id} as inactive: {reason}")
                return True
            else:
                logger.warning(f"Survey {survey_id} not found for deactivation")
                return False
        
        except Exception as e:
            logger.error(f"Error marking survey {survey_id} inactive: {e}")
            return False

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

    def get_all_surveys_for_rate_card(self) -> List[Dict[str, Any]]:
        """
        Get all active surveys for rate card calculation (no pagination).
        
        Returns only the fields needed for rate card: bid_incidence, 
        length_of_interview, revenue_per_interview, country_language.
        
        Returns:
            List of survey dicts with rate card relevant fields
        """
        if self.cint_surveys_collection is None:
            return []
        
        try:
            # Include all surveys (active + inactive) for rate card calculations
            filter_query = {}
            
            # Only fetch fields needed for rate card calculation
            projection = {
                "_id": 0,
                "survey_id": 1,
                "bid_incidence": 1,
                "length_of_interview": 1,
                "bid_length_of_interview": 1,
                "revenue_per_interview": 1,
                "country_language": 1,
            }
            
            cursor = self.cint_surveys_collection.find(filter_query, projection)
            return list(cursor)
        
        except Exception as e:
            logger.error(f"Error fetching surveys for rate card: {str(e)}")
            return []

    def get_surveys(
        self,
        min_loi: Optional[int] = None,
        max_loi: Optional[int] = None,
        min_cpi: Optional[float] = None,
        country: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        apply_default_filters: bool = True,
        active_only: bool = False,
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
            active_only: If True, only return surveys that are active in the pool

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
            
            # Filter by pool activation status if requested
            if active_only:
                filter_query["is_active_in_pool"] = True
            
            # Apply LOI filters - check both length_of_interview and bid_length_of_interview fields
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
            
            # Apply CPI filter only if explicitly provided or apply_default_filters is True
            effective_min_cpi = min_cpi  # Use explicitly passed value first
            if effective_min_cpi is None and apply_default_filters:
                effective_min_cpi = filter_settings.get("min_cpi", 1.0)
            
            if effective_min_cpi is not None:
                # IMPORTANT: revenue_per_interview.value is stored as a STRING in the database
                # We need to compare as string for proper matching
                min_cpi_str = str(effective_min_cpi)
                cpi_conditions = [
                    {"payout": {"$gte": effective_min_cpi}},
                    # Compare as string since revenue_per_interview.value is stored as string like "1.6975"
                    {"revenue_per_interview.value": {"$gte": min_cpi_str}},
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

    async def _auto_deactivate_quota_full(self, survey_id: int) -> None:
        """Deactivate survey in yield layer and pool layer when quota is exhausted."""
        if self.cint_surveys_collection is None:
            return

        try:
            metrics_col = self.db["cint_metrics"] if hasattr(self, 'db') else None
            if metrics_col is None:
                return

            now = datetime.now(timezone.utc)
            sid_str = str(survey_id)

            # Snapshot conversion rate at deactivation
            survey_snap = self.cint_surveys_collection.find_one(
                {"survey_id": survey_id},
                {"conversion": 1}
            )
            global_conv_now = float((survey_snap or {}).get("conversion") or 0)

            # Update yield layer
            metrics_col.update_one(
                {"survey_id": sid_str},
                {"$set": {
                    "survey_status": "inactive",
                    "deactivated_at": now,
                    "global_conv_at_deactivation": global_conv_now,
                    "deactivation_reason": "quota_full",
                    "auto_deactivated": True,
                }},
                upsert=True,
            )

            # Update pool layer
            self.cint_surveys_collection.update_one(
                {"survey_id": survey_id},
                {"$set": {"is_active_in_pool": False}}
            )
            logger.info(f"Survey {survey_id} yield-deactivated: quota_full")
        except Exception as e:
            logger.error(f"Error auto-deactivating quota-full survey {survey_id}: {e}")

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


# ============================================
# Module-level Helpers
# ============================================

def calculate_safe_volume(survey: dict, floor_conv: float = 0.05) -> int:
    """
    Recommended number of respondents to send to avoid over-pacing.

    Formula:  ceil(quota_remaining / max(functional_conv, floor_conv))

    Args:
        survey: Dict that has 'total_remaining' and optional 'conversion' /
                'internal_conversion' fields
        floor_conv: Minimum conversion rate to use as divisor (avoid division by very small value)

    Returns:
        Recommended volume (integer)
    """
    import math
    quota_remaining = int(survey.get("total_remaining") or 0)
    if quota_remaining <= 0:
        return 0

    # functional_conv is the better signal; fall back to global conversion
    internal_conv = survey.get("internal_conversion")
    entrants_n = int(survey.get("entrants_n") or 0)
    global_conv = float(survey.get("conversion") or 0)

    functional_conv = (
        internal_conv if (internal_conv is not None and entrants_n >= 20)
        else global_conv
    )
    effective_conv = max(float(functional_conv or 0), floor_conv)

    return math.ceil(quota_remaining / effective_conv)
