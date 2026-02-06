import os
import random
import requests
import hashlib
from urllib.parse import urlencode
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient


class CPXService:
    """Service to interact with CPX Research API"""
    
    BASE_URL = "https://live-api.cpx-research.com/api/get-surveys.php"
    # CPX provides href URLs in the format: click.cpx-research.com/?k=<encrypted>&...
    # We just need to append subid_1 and subid_2 to the href for tracking
    CLICK_URL = "https://click.cpx-research.com/"
    
    def __init__(
        self,
        app_id: str,
        ext_user_id: str,
        secure_hash_key: str,
        api_timeout: int = 30,
        fetch_limit: int = 1000,
        surveys_collection: Optional[Any] = None,
        filters_collection: Optional[Any] = None,
        settings_collection: Optional[Any] = None,
        survey_allocation_service: Optional[Any] = None,
    ):
        """
        Initialize CPX Service
        
        Args:
            app_id: CPX App ID
            ext_user_id: CPX External User ID
            secure_hash_key: CPX Secure Hash Key
            api_timeout: API request timeout in seconds
            fetch_limit: Maximum number of surveys to fetch
            surveys_collection: MongoDB collection for surveys (optional for testing)
            filters_collection: MongoDB collection for filter settings (deprecated, use settings_collection)
            settings_collection: MongoDB collection for app settings (torpedo_settings.app_settings)
            survey_allocation_service: SurveyAllocationService instance for metrics (optional, needed for clicks/completes)
        """
        self.app_id = app_id
        self.ext_user_id = ext_user_id
        self.secure_hash_key = secure_hash_key
        self.api_timeout = api_timeout
        self.fetch_limit = fetch_limit
        self.settings_collection = settings_collection
        self.survey_allocation_service = survey_allocation_service
        
        # If collections are provided, use them; otherwise initialize from env
        if surveys_collection is not None:
            self.cpx_surveys_collection = surveys_collection
            self.cpx_filters_collection = filters_collection
        else:
            # Fallback to environment-based initialization
            mongo_uri = os.getenv("MONGO_URI")
            if mongo_uri:
                client = MongoClient(mongo_uri)
                db = client["cpx_research"]
                self.cpx_surveys_collection = db["cpx_surveys"]
                self.cpx_filters_collection = db["cpx_filters"]
                # Also connect to settings database
                if settings_collection is None:
                    settings_db = client["torpedo_settings"]
                    self.settings_collection = settings_db["app_settings"]
            else:
                self.cpx_surveys_collection = None
                self.cpx_filters_collection = None
        
        # Create indexes for faster queries
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create database indexes for faster query performance"""
        if self.cpx_surveys_collection is None:
            return
        try:
            # Index for sorting by last_updated (most common query)
            self.cpx_surveys_collection.create_index("last_updated", background=True)
            # Index for filtering
            self.cpx_surveys_collection.create_index("loi", background=True)
            self.cpx_surveys_collection.create_index("payout", background=True)
            self.cpx_surveys_collection.create_index("country", background=True)
            self.cpx_surveys_collection.create_index("category", background=True)
            # Compound index for common filter + sort combo
            self.cpx_surveys_collection.create_index(
                [("country", 1), ("last_updated", -1)], 
                background=True
            )
        except Exception as e:
            print(f"Warning: Could not create CPX indexes: {e}")
    
    @staticmethod
    def _generate_secure_hash(ext_user_id: str, secure_hash_key: str) -> str:
        """
        Generate MD5 secure hash for CPX API authentication
        
        Args:
            ext_user_id: External user ID
            secure_hash_key: Secure hash key
            
        Returns:
            MD5 hash string
        """
        hash_string = f"{ext_user_id}-{secure_hash_key}"
        return hashlib.md5(hash_string.encode()).hexdigest()
    
    def generate_entry_link(
        self,
        survey_id: str,
        respondent_id: str,
        subid_1: Optional[str] = None,
        subid_2: Optional[str] = None,
        href: Optional[str] = None,
        username: Optional[str] = None,
        email: Optional[str] = None,
        live_link: Optional[str] = None,
    ) -> str:
        """
        Generate CPX entry link by appending subid_1 and subid_2 to the CPX href URL.
        
        Args:
            survey_id: The CPX survey ID
            respondent_id: The respondent's SFWID for tracking
            href: The CPX href URL (click.cpx-research.com/?k=...) - REQUIRED
            Other params are deprecated/ignored
            
        Returns:
            Entry link with subid_1 and subid_2 populated
        """
        # Use href or live_link as the base URL
        base_href = href or live_link
        
        if survey_id and respondent_id and base_href:
            return self.generate_respondent_entry_link(survey_id, respondent_id, base_href)
        elif survey_id and respondent_id:
            # No href provided - log warning
            print(f"⚠️ generate_entry_link called without href for survey {survey_id}")
            return ""
        return ""
    
    def generate_respondent_entry_link(
        self,
        survey_id: str,
        respondent_id: str,  # SFWID - Survey Field Work ID
        href: Optional[str] = None,  # The CPX href URL with k= parameter
    ) -> str:
        """
        Generate a unique CPX entry link for a specific respondent.
        
        CORRECT FLOW:
        1. CPX API returns surveys with href URLs: click.cpx-research.com/?k=<encrypted>&...
        2. The href already contains the unique k= token from CPX
        3. We just append subid_1 and subid_2 to the href for callback tracking
        
        Args:
            survey_id: The CPX survey ID (for logging/validation)
            respondent_id: The respondent's SFWID (Survey Field Work ID)
            href: The CPX href URL from the survey (contains k= parameter)
            
        Returns:
            Fully qualified CPX entry URL with subid_1 and subid_2 appended
            
        Raises:
            ValueError: If survey_id, respondent_id, or href is empty
        """
        # Validate inputs - fail loudly if missing
        if not survey_id:
            raise ValueError("survey_id is required for CPX entry link generation")
        if not respondent_id:
            raise ValueError("respondent_id (SFWID) is required for CPX entry link generation")
        if not href:
            raise ValueError("href (CPX click URL with k= parameter) is required for CPX entry link generation")
        
        # The href from CPX already has the format:
        # https://click.cpx-research.com/?k=<encrypted>&api=true&time_stamp=...&ext_user_id=...
        # We keep the href as-is and only set subid_1 for respondent tracking
        
        # Parse the URL to properly handle query parameters
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        
        parsed = urlparse(href)
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Ensure subid_1 appears exactly once in the final URL.
        # CPX hrefs may already include subid_1/subid_2 placeholders; remove all first.
        query_params.pop('subid_1', None)
        query_params.pop('subid_2', None)
        # Set respondent tracking only (subid_1). Ignore subid_2 placeholder.
        query_params['subid_1'] = [respondent_id]
        
        # Build query string preserving original parameters (k, api, time_stamp, ext_user_id)
        new_query = urlencode(query_params, doseq=True)
        
        # Reconstruct the full URL
        entry_link = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        
        print(f"🔗 Generated CPX entry link for respondent {respondent_id}, survey {survey_id}")
        print(f"   Full URL: {entry_link[:150]}...")
        return entry_link
    
    def allocate_survey_for_respondent(
        self,
        respondent_id: str,  # SFWID
        survey_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Allocate a CPX survey to a respondent and generate their unique entry link.
        
        This method:
        1. Validates the respondent_id (SFWID) is non-empty
        2. Selects a survey (by survey_id or from active pool)
        3. Validates the survey exists and is_active_in_pool=true
        4. Generates entry link using generate_respondent_entry_link()
        5. Increments click counters on the survey
        6. Returns a clean allocation response
        
        IMPORTANT: This method does NOT call the CPX API. It only uses cached
        survey metadata and generates entry links dynamically.
        
        Args:
            respondent_id: The respondent's SFWID (Survey Field Work ID) - REQUIRED
            survey_id: Optional specific survey ID to allocate. If not provided,
                      a random active survey is selected.
        
        Returns:
            Dictionary with allocation details:
            {
                "success": bool,
                "entry_link": str,
                "survey_id": str,
                "respondent_id": str,
                "survey": dict,  # Survey metadata (loi, payout, etc.)
                "error": str  # Only present if success=False
            }
            
        Raises:
            ValueError: If respondent_id is empty
        """
        # Validate respondent_id is non-empty
        if not respondent_id:
            raise ValueError("respondent_id (SFWID) is required for CPX allocation")
        
        if self.cpx_surveys_collection is None:
            return {
                "success": False,
                "error": "CPX surveys collection not initialized",
                "entry_link": "",
                "survey_id": "",
                "respondent_id": respondent_id,
            }
        
        try:
            # Build query for active surveys
            query = {"is_active_in_pool": True}
            
            if survey_id:
                # Specific survey requested - validate it exists and is active
                query["_id"] = survey_id
                survey = self.cpx_surveys_collection.find_one(query)
                
                if not survey:
                    # Check if survey exists but is inactive
                    inactive_survey = self.cpx_surveys_collection.find_one({"_id": survey_id})
                    if inactive_survey:
                        return {
                            "success": False,
                            "error": f"Survey {survey_id} exists but is not active in pool",
                            "entry_link": "",
                            "survey_id": survey_id,
                            "respondent_id": respondent_id,
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Survey {survey_id} not found",
                            "entry_link": "",
                            "survey_id": survey_id,
                            "respondent_id": respondent_id,
                        }
            else:
                # No specific survey - pick one from active pool
                # Use aggregation with $sample for random selection
                pipeline = [
                    {"$match": query},
                    {"$sample": {"size": 1}}
                ]
                result = list(self.cpx_surveys_collection.aggregate(pipeline))
                
                if not result:
                    return {
                        "success": False,
                        "error": "No active surveys available in pool",
                        "entry_link": "",
                        "survey_id": "",
                        "respondent_id": respondent_id,
                    }
                
                survey = result[0]
            
            # Extract survey_id from the selected survey
            allocated_survey_id = str(survey.get("_id") or survey.get("survey_id"))
            
            # Use cached href from survey (fetched during refresh with PANEL_88921)
            # This avoids calling CPX API per respondent (important for 500+ simultaneous starts)
            # Prefer href_new (mobile-optimized per CPX docs)
            survey_href = survey.get("href_new") or survey.get("href") or ""
            
            if not survey_href:
                return {
                    "success": False,
                    "error": f"Survey {allocated_survey_id} missing href (run refresh to update surveys)",
                    "entry_link": "",
                    "survey_id": allocated_survey_id,
                    "respondent_id": respondent_id,
                }
            
            # Generate entry link by appending subid_1 to the cached CPX href
            # Note: href is encrypted with PANEL_88921, but respondent tracking is via subid_1
            entry_link = self.generate_respondent_entry_link(
                survey_id=allocated_survey_id,
                respondent_id=respondent_id,
                href=survey_href
            )
            
            # Increment click counter and update last_clicked_at
            self.cpx_surveys_collection.update_one(
                {"_id": allocated_survey_id},
                {
                    "$inc": {"click_count": 1},
                    "$set": {"last_clicked_at": datetime.utcnow()}
                }
            )
            
            # Prepare clean survey metadata for response (no raw_data, no href)
            clean_survey = {
                "survey_id": allocated_survey_id,
                "title": survey.get("title", ""),
                "loi": survey.get("loi", 0),
                "payout": survey.get("payout", 0),
                "conversion_rate": survey.get("conversion_rate", 0),
                "country": survey.get("country", "ALL"),
                "category": survey.get("category", ""),
                "provider": "CPX",
            }
            
            print(f"✅ Allocated CPX survey {allocated_survey_id} to respondent {respondent_id}")
            
            return {
                "success": True,
                "entry_link": entry_link,
                "survey_id": allocated_survey_id,
                "respondent_id": respondent_id,
                "survey": clean_survey,
            }
            
        except ValueError as ve:
            # Re-raise validation errors
            raise ve
        except Exception as e:
            print(f"❌ CPX allocation error: {e}")
            return {
                "success": False,
                "error": f"Allocation failed: {str(e)}",
                "entry_link": "",
                "survey_id": survey_id or "",
                "respondent_id": respondent_id,
            }
    
    @staticmethod
    def _get_client_ip() -> str:
        """
        DEPRECATED - DO NOT USE
        
        This method previously returned a hardcoded IP which violated CPX identity rules.
        IP MUST come from the actual client request, not a fallback.
        
        Raises:
            RuntimeError: Always - fallback IP is not allowed
        """
        raise RuntimeError(
            "CPX FATAL: _get_client_ip() fallback called. "
            "IP MUST be captured from actual client request headers. "
            "Using fallback IP will cause CPX to reject all traffic."
        )
    
    @staticmethod
    def _get_user_agent() -> str:
        """
        DEPRECATED - DO NOT USE
        
        This method previously returned a generic UA which violated CPX fingerprint rules.
        UA MUST come from the actual client request, not a fallback.
        
        Raises:
            RuntimeError: Always - fallback UA is not allowed
        """
        raise RuntimeError(
            "CPX FATAL: _get_user_agent() fallback called. "
            "User-Agent MUST be captured from actual client request headers. "
            "Using fallback UA will cause CPX fingerprint mismatch."
        )

    @staticmethod
    def _utc_to_ist(utc_dt: datetime) -> datetime:
        """
        Convert UTC datetime to IST (Indian Standard Time)

        Args:
            utc_dt: UTC datetime object

        Returns:
            IST datetime object
        """
        ist_offset = timedelta(hours=5, minutes=30)
        return utc_dt + ist_offset
    
    def fetch_cpx_surveys(self) -> List[Dict[str, Any]]:
        """
        DEPRECATED - DO NOT USE FOR PRODUCTION
        
        This method attempts to fetch CPX surveys without a real client context.
        This fundamentally violates CPX protocol:
        - href URLs are bound to ext_user_id + IP + UA from the API call
        - Surveys fetched with fake/generic IP/UA cannot be used by real respondents
        - The encrypted 'k' parameter in href will mismatch on click
        
        For production use:
        - Use fetch_and_allocate_for_respondent() with REAL client IP and UA
        - Fetch surveys on-demand when a real respondent is present
        
        Raises:
            RuntimeError: Always - bulk fetching CPX surveys is not allowed
        """
        raise RuntimeError(
            "CPX FATAL: fetch_cpx_surveys() is deprecated. "
            "CPX surveys MUST be fetched per-respondent with real IP/UA. "
            "Use fetch_and_allocate_for_respondent() instead."
        )

    def fetch_survey_href_for_respondent(
        self,
        respondent_id: str,
        survey_id: str
    ) -> Optional[str]:
        """
        DEPRECATED - DO NOT USE
        
        This method attempts to fetch a specific survey href without real IP/UA.
        This fundamentally violates CPX protocol:
        - href URLs are bound to ext_user_id + IP + UA from the API call
        - Using fallback IP/UA causes fingerprint mismatch on click
        
        For production use:
        - Use fetch_and_allocate_for_respondent() with REAL client IP and UA
        - Let CPX select the best survey (don't target specific survey_id)
        
        Raises:
            RuntimeError: Always - this method cannot work correctly
        """
        raise RuntimeError(
            "CPX FATAL: fetch_survey_href_for_respondent() is deprecated. "
            "CPX surveys MUST be fetched with real IP/UA. "
            "Use fetch_and_allocate_for_respondent() instead."
        )
    
    @classmethod
    def normalize_country_code(cls, country_code: str) -> str:
        """
        Normalize country code to 2-letter ISO format for CPX API.
        
        CPX requires ISO2 format (e.g., "IN", "US", "GB").
        This method ensures we always send 2-letter codes.
        """
        if not country_code:
            return ""
        code = country_code.upper().strip()
        # Handle common aliases
        if code == "UK":
            return "GB"
        # If already ISO2 (2 chars), return as-is
        if len(code) == 2:
            return code
        # If ISO3 was accidentally passed, we can't safely convert back
        # Just return empty and log warning
        if len(code) == 3:
            print(f"⚠️ CPX WARNING: Received ISO3 country code '{code}', expected ISO2. Skipping country param.")
            return ""
        return code
    
    def fetch_and_allocate_for_respondent(
        self,
        vendor_user_id: str,          # STABLE vendor-provided rid (ext_user_id for CPX)
        internal_tracking_id: str,     # Our SFWID for internal tracking (subid_1)
        user_ip: str,                  # REQUIRED - real client IP, no fallback
        user_agent: str,               # REQUIRED - real client UA, no fallback
        country_code: str = "",        # ISO2 country code (e.g., "US", "IN") - sent as-is to CPX
    ) -> Dict[str, Any]:
        """
        ╔══════════════════════════════════════════════════════════════════════════════╗
        ║  ⚠️  CPX IS NOT A POOL-BASED PROVIDER - READ THIS BEFORE MODIFYING  ⚠️       ║
        ╠══════════════════════════════════════════════════════════════════════════════╣
        ║                                                                              ║
        ║  DO NOT:                                                                     ║
        ║    ❌ Reuse survey hrefs (they are single-use, identity-bound)               ║
        ║    ❌ Retry failed calls (each call binds new identity)                      ║
        ║    ❌ Call from background jobs (requires real HTTP context)                 ║
        ║    ❌ Mutate href URLs (k= parameter is cryptographically signed)            ║
        ║    ❌ Fabricate IP or User-Agent (must match click fingerprint)              ║
        ║    ❌ Store href in database (expires immediately)                           ║
        ║    ❌ Abstract into shared vendor allocator (CPX rules are unique)           ║
        ║                                                                              ║
        ║  THIS METHOD MUST BE CALLED ONLY FROM A REAL HTTP REQUEST.                   ║
        ║  VIOLATING THIS WILL CAUSE SILENT TRAFFIC TERMINATION BY CPX.                ║
        ║                                                                              ║
        ╚══════════════════════════════════════════════════════════════════════════════╝
        
        Fetch CPX surveys for a specific respondent, apply filters, randomly select one,
        and generate entry link for IMMEDIATE redirect.
        
        ⚠️ THIS IS THE ONLY VALID CPX ENTRY POINT ⚠️
        
        This method MUST be called from an HTTP request context with:
        - Real vendor-provided respondent ID (not generated UUIDs)
        - Real client IP from request headers
        - Real User-Agent from browser
        
        CRITICAL CPX IDENTITY RULES:
        - ext_user_id MUST be a STABLE identifier (vendor's rid), NOT our internal traffic_id
        - secure_hash = md5(ext_user_id + "-" + secret) - MUST use same ext_user_id
        - subid_1 = our internal tracking ID (SFWID) for postback correlation
        - href is single-use, tied to ext_user_id, NEVER cache or reuse
        - IP and UA MUST match between API call and user click (no fallbacks!)
        
        Flow:
        1. Call CPX API with vendor_user_id as ext_user_id
        2. CPX returns surveys with hrefs bound to that ext_user_id
        3. Apply filter settings (max_loi, min_cpi, min_ir)
        4. Randomly select one survey from filtered results  
        5. Append subid_1=internal_tracking_id to href for our tracking
        6. Return entry_link for IMMEDIATE redirect (href expires quickly)
        
        REGRESSION GUARDS:
        - vendor_user_id must not look like UUID/ObjectId (indicates wrong ID used)
        - user_ip must not be localhost/private (indicates missing real IP)
        - user_agent must not be generic/empty (indicates missing real UA)
        
        Args:
            vendor_user_id: STABLE vendor-provided respondent ID (rid parameter)
                           This becomes ext_user_id for CPX identity tracking
            internal_tracking_id: Our SFWID for internal tracking (becomes subid_1)
            user_ip: Real Device IP - REQUIRED, must match user's click IP
            user_agent: Real User-Agent - REQUIRED, must match user's browser
            
        Returns:
            Dictionary with allocation result:
            {
                "success": bool,
                "entry_link": str,
                "survey_id": str,
                "vendor_user_id": str,
                "internal_tracking_id": str,
                "survey": dict,
                "error": str  # Only present if success=False
            }
        """
        # =========================================================================
        # REGRESSION GUARDS - Detect incorrect usage patterns
        # =========================================================================
        import re
        
        # Guard 1: Detect if vendor_user_id looks like a UUID/ObjectId (wrong ID type)
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        objectid_pattern = r'^[0-9a-f]{24}$'
        if vendor_user_id and (re.match(uuid_pattern, vendor_user_id, re.I) or re.match(objectid_pattern, vendor_user_id, re.I)):
            print(f"⚠️ CPX REGRESSION WARNING: vendor_user_id '{vendor_user_id}' looks like UUID/ObjectId!")
            print("   This should be the vendor's stable rid, not an internally generated ID.")
            # Don't fail, but log loudly for debugging
        
        # Guard 2: Detect localhost/private IPs (indicates missing real client IP)
        private_ip_patterns = ['127.0.0.1', 'localhost', '0.0.0.0', '::1', '10.', '192.168.', '172.16.', '172.17.', '172.18.', '172.19.', '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.']
        if user_ip and any(user_ip.startswith(p) for p in private_ip_patterns):
            print(f"⚠️ CPX REGRESSION WARNING: user_ip '{user_ip}' is private/localhost!")
            print("   CPX requires real public client IP. This will cause identity mismatch on click.")
        
        # Guard 3: Detect generic/empty User-Agent
        generic_ua_patterns = ['python', 'requests', 'curl', 'wget', 'httpie', 'test', 'bot', 'crawler']
        if user_agent and any(p in user_agent.lower() for p in generic_ua_patterns):
            print(f"⚠️ CPX REGRESSION WARNING: user_agent looks generic/automated!")
            print("   CPX requires real browser User-Agent. This will cause fingerprint mismatch.")
        
        # =========================================================================
        # Validate ALL required inputs - no fallbacks, fail fast
        if not vendor_user_id:
            return {
                "success": False,
                "error": "vendor_user_id (rid) is REQUIRED for CPX ext_user_id",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id or "",
                "internal_tracking_id": internal_tracking_id or "",
            }
        
        if not internal_tracking_id:
            return {
                "success": False,
                "error": "internal_tracking_id (SFWID) is REQUIRED for tracking",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": "",
            }
        
        if not user_ip:
            return {
                "success": False,
                "error": "user_ip is REQUIRED - CPX validates IP consistency",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": internal_tracking_id,
            }
        
        if not user_agent:
            return {
                "success": False,
                "error": "user_agent is REQUIRED - CPX validates UA fingerprint",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": internal_tracking_id,
            }
        
        try:
            # Generate secure hash using the tracking ID (ext_user_id = subid_1 = internal_tracking_id)
            # CPX formula: md5(ext_user_id + "-" + secure_hash_key)
            # Using internal_tracking_id for BOTH ext_user_id and subid_1 for consistent tracking
            secure_hash = self._generate_secure_hash(internal_tracking_id, self.secure_hash_key)
            
            # Normalize country code to ISO2 format for CPX (e.g., "IN", "US")
            country_iso2 = self.normalize_country_code(country_code) if country_code else ""
            
            # Build params - ext_user_id and subid_1 are the SAME for consistent tracking
            params = {
                "app_id": self.app_id,
                "ext_user_id": internal_tracking_id,   # Use SFWID as ext_user_id
                "subid_1": internal_tracking_id,       # Use SFWID as subid_1 (same value)
                "subid_2": "",
                "output_method": "api",
                "ip_user": user_ip,                    # Real client IP (required)
                "user_agent": user_agent,              # Real client UA (required)
                "limit": self.fetch_limit,
                "secure_hash": secure_hash,
            }
            
            # Add country code if available (ISO2 format for CPX - e.g., "IN", "US")
            # CPX docs: parameter name is "user_country_code", NOT "country_code"
            if country_iso2:
                params["user_country_code"] = country_iso2
            
            print(f"🔄 Fetching CPX surveys for tracking_id={internal_tracking_id} (ext_user_id=subid_1)")
            print(f"   Device IP: {user_ip}")
            print(f"   Country: {country_iso2}" if country_iso2 else "   Country: not provided")
            print(f"   User-Agent: {user_agent[:80]}..." if user_agent and len(user_agent) > 80 else f"   User-Agent: {user_agent}")
            print(f"   CPX params: app_id={params['app_id']}, ext_user_id={params['ext_user_id']}, subid_1={params['subid_1']}, ip_user={params['ip_user']}, user_country_code={country_iso2}")
            
            response = requests.get(
                self.BASE_URL,
                params=params,
                timeout=self.api_timeout
            )
            response.raise_for_status()
            data = response.json()
            
            # Debug: Log raw CPX API response summary
            print(f"🔍 CPX API response for {vendor_user_id}: status={data.get('status')}, count={data.get('count_available_surveys')}, surveys_len={len(data.get('surveys', []))}, message_not_found={data.get('message_not_found')}")
            
            # Parse API response
            if not isinstance(data, dict):
                print(f"⚠️ Unexpected CPX API response format: {type(data)}")
                return {
                    "success": False,
                    "error": "Invalid API response format",
                    "entry_link": "",
                    "survey_id": "",
                    "vendor_user_id": vendor_user_id,
                    "internal_tracking_id": internal_tracking_id,
                }
            
            # Handle multiple response formats
            surveys: List[Dict[str, Any]] = []
            if isinstance(data.get("surveys"), list) and len(data["surveys"]) > 0:
                surveys = data["surveys"]
            elif data.get("count_available_surveys", 0) > 0:
                info_list = data.get("info", [])
                if isinstance(info_list, list) and len(info_list) > 0:
                    surveys = info_list
            elif data.get("message_not_found"):
                print(f"ℹ️ No surveys available from CPX for {vendor_user_id}")
                return {
                    "success": False,
                    "error": "No surveys available from CPX",
                    "entry_link": "",
                    "survey_id": "",
                    "vendor_user_id": vendor_user_id,
                    "internal_tracking_id": internal_tracking_id,
                }
            
            if not surveys:
                return {
                    "success": False,
                    "error": "No surveys returned from CPX API",
                    "entry_link": "",
                    "survey_id": "",
                    "vendor_user_id": vendor_user_id,
                    "internal_tracking_id": internal_tracking_id,
                }
            
            print(f"📥 Fetched {len(surveys)} surveys from CPX for {vendor_user_id}")
            
            # Store ALL surveys in cpx_research.cpx_surveys (for reference/analytics ONLY)
            # NOTE: Do NOT store href - it's bound to ext_user_id and single-use
            if self.cpx_surveys_collection is not None:
                for survey in surveys:
                    normalized = self._normalize_survey(survey)
                    # Remove href before storing - it's single-use and bound to ext_user_id
                    normalized.pop('href', None)
                    normalized.pop('href_new', None)
                    normalized.pop('live_link', None)
                    try:
                        self.cpx_surveys_collection.update_one(
                            {"_id": normalized.get("_id")},
                            {
                                "$set": normalized,
                                "$setOnInsert": {
                                    "created_at": datetime.utcnow(),
                                    "click_count": 0,
                                    "last_clicked_at": None,
                                }
                            },
                            upsert=True
                        )
                    except Exception as e:
                        print(f"⚠️ Failed to upsert survey {normalized.get('_id')}: {e}")
            
            # Get filter settings
            filter_settings = self.get_filter_settings()
            max_loi = filter_settings.get("max_loi", 20)
            min_cpi = filter_settings.get("min_cpi", 1.0)
            min_ir = filter_settings.get("min_ir", 0)
            
            print(f"🔍 Applying filters: max_loi={max_loi}, min_cpi={min_cpi}, min_ir={min_ir}")
            
            # Apply filters to find matching surveys
            filtered_surveys = []
            for survey in surveys:
                # Get survey values
                loi = float(survey.get("loi") or survey.get("survey_loi") or 0)
                payout = float(
                    survey.get("payout_publisher_usd") or
                    survey.get("survey_reward_usd") or
                    survey.get("payout") or 0
                )
                ir = float(survey.get("conversion_rate") or survey.get("ir") or 0)
                
                # Apply filters
                if loi > max_loi:
                    continue  # LOI too high
                if payout < min_cpi:
                    continue  # Payout too low
                if ir < min_ir:
                    continue  # Incidence rate too low
                
                # Check href exists - prefer href_new (mobile-optimized per CPX docs)
                href = survey.get("href_new") or survey.get("href") or ""
                if not href:
                    continue  # No href means we can't generate entry link
                
                filtered_surveys.append(survey)
            
            if not filtered_surveys:
                print(f"⚠️ No surveys match filters for {vendor_user_id}")
                return {
                    "success": False,
                    "error": f"No surveys match filter criteria (max_loi={max_loi}, min_cpi={min_cpi}, min_ir={min_ir})",
                    "entry_link": "",
                    "survey_id": "",
                    "vendor_user_id": vendor_user_id,
                    "internal_tracking_id": internal_tracking_id,
                }
            
            print(f"✅ {len(filtered_surveys)} surveys match filters")
            
            # Randomly select one survey
            selected_survey = random.choice(filtered_surveys)
            survey_id = str(selected_survey.get("id") or selected_survey.get("survey_id"))
            # Prefer href_new (mobile-optimized per CPX docs)
            href = selected_survey.get("href_new") or selected_survey.get("href") or ""
            
            print(f"🎲 Randomly selected survey {survey_id} for {vendor_user_id}")
            
            # CRITICAL: href already contains ext_user_id=vendor_user_id from API call
            # The subid_1 was also set in API call params, so href should have it
            # We use the href as-is - DO NOT modify it (it's already correctly formed)
            # Just verify subid_1 is present, if not, append our internal_tracking_id
            entry_link = href
            if f"subid_1={internal_tracking_id}" not in href and "subid_1=" not in href:
                # href might not have subid_1, append it
                separator = "&" if "?" in href else "?"
                entry_link = f"{href}{separator}subid_1={internal_tracking_id}"
            elif "subid_1=" in href and f"subid_1={internal_tracking_id}" not in href:
                # CPX might have included a different subid_1, replace it
                from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                parsed = urlparse(href)
                query_params = parse_qs(parsed.query, keep_blank_values=True)
                query_params['subid_1'] = [internal_tracking_id]
                new_query = urlencode(query_params, doseq=True)
                entry_link = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
            
            print(f"🔗 Entry link for {vendor_user_id}: {entry_link[:120]}...")
            
            # Prepare clean survey metadata
            clean_survey = {
                "survey_id": survey_id,
                "title": selected_survey.get("survey_title") or selected_survey.get("title", ""),
                "loi": float(selected_survey.get("loi") or selected_survey.get("survey_loi") or 0),
                "payout": float(
                    selected_survey.get("payout_publisher_usd") or
                    selected_survey.get("survey_reward_usd") or 0
                ),
                "conversion_rate": float(selected_survey.get("conversion_rate") or 0),
                "provider": "CPX",
            }
            
            print(f"✅ Allocated CPX survey {survey_id} to vendor_user_id={vendor_user_id}, tracking_id={internal_tracking_id}")
            
            return {
                "success": True,
                "entry_link": entry_link,
                "survey_id": survey_id,
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": internal_tracking_id,
                "survey": clean_survey,
            }
            
        except requests.exceptions.Timeout:
            print(f"❌ CPX API timeout for {vendor_user_id}")
            return {
                "success": False,
                "error": f"CPX API timeout (>{self.api_timeout}s)",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": internal_tracking_id,
            }
        except requests.exceptions.RequestException as e:
            print(f"❌ CPX API request failed for {vendor_user_id}: {e}")
            return {
                "success": False,
                "error": f"CPX API request failed: {str(e)}",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": internal_tracking_id,
            }
        except Exception as e:
            print(f"❌ CPX allocation error for {vendor_user_id}: {e}")
            return {
                "success": False,
                "error": f"Allocation failed: {str(e)}",
                "entry_link": "",
                "survey_id": "",
                "vendor_user_id": vendor_user_id,
                "internal_tracking_id": internal_tracking_id,
            }
    
    def _normalize_survey(self, survey: Dict[str, Any], respondent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Normalize CPX survey data to internal format
        
        Args:
            survey: Raw survey data from CPX API
            respondent_id: Optional respondent ID to generate entry_link
            
        Returns:
            Normalized survey dictionary
        """
        # Handle both naming conventions (id vs survey_id, loi vs survey_loi, etc.)
        survey_id = survey.get("id") or survey.get("survey_id")
        loi_value = survey.get("loi") or survey.get("survey_loi", 0)
        payout_value = (
            survey.get("payout_publisher_usd") or 
            survey.get("survey_reward_usd") or 
            0
        )
        
        # Get country with default to ALL if missing
        # CPX doesn't provide country code in payload, so we use ALL to indicate no country filter
        # The allocation logic should skip country filtering for CPX surveys when country=ALL
        country = survey.get("survey_country") or survey.get("country", "") or "ALL"
        
        # Get href and href_new from CPX API response
        # href is the click-tracking URL (click.cpx-research.com) required for entry links
        # href_new is the mobile-optimized version
        href = survey.get("href") or ""
        href_new = survey.get("href_new") or ""
        
        # Log warning if href is missing - this survey won't be usable for allocation
        if not href:
            print(f"⚠️  Survey {survey_id} missing href - will be skipped during allocation")
        
        # Use href as live_link (the click-tracking URL from CPX API)
        # Prefer href_new (mobile-optimized) if available, otherwise use href
        live_link = href_new or href
        
        # Map CPX field names to internal field names
        # NOTE: Entry links are NOT stored - they are generated dynamically per respondent
        # at allocation time using generate_respondent_entry_link()
        normalized = {
            "_id": str(survey_id),  # Map to _id for MongoDB
            "survey_id": str(survey_id),
            "title": survey.get("survey_title") or survey.get("title", ""),
            "loi": float(loi_value),
            "payout": float(payout_value),
            "payout_publisher_usd": float(payout_value),
            "conversion_rate": float(survey.get("conversion_rate", 0)),
            "country": country,
            "category": survey.get("survey_category") or survey.get("category", ""),
            "provider": "CPX",
            "source": "CPX",
            "last_updated": datetime.utcnow(),
            # IMPORTANT: href contains the click.cpx-research.com/?k=<encrypted> URL from CPX API
            # At allocation time, we append subid_1 and subid_2 to this URL for tracking
            "href": href,              # Primary CPX click URL with k= parameter
            "href_new": href_new,      # Mobile-optimized version (if available)
            "raw_data": survey,        # Store raw data for reference
            # Click tracking fields - used for click-based cleanup
            # click_count and last_clicked_at are set via $setOnInsert to preserve existing values
        }
        
        # CORRECT FLOW for entry link generation at allocation time:
        # 1. Get the href from stored survey (click.cpx-research.com/?k=<encrypted>&...)
        # 2. Append subid_1=SFWID and subid_2=SFWID to the URL for callback tracking
        # 3. Redirect user to this URL
        # 
        # The href already contains the unique k= token from CPX API.
        # DO NOT generate a new secure_hash - just use the href as-is with subids appended.
        
        return normalized
    
    def _apply_filters(self, survey: Dict[str, Any]) -> bool:
        """
        Apply user-configured filters to survey
        
        Args:
            survey: Normalized survey data
            
        Returns:
            True if survey passes filters, False otherwise
        """
        # Get user filter settings, with sensible defaults
        filter_settings = self.get_filter_settings()
        max_loi = filter_settings.get("max_loi", 20)  # Default: 20 minutes
        min_cpi = filter_settings.get("min_cpi", 1.0)  # Default: $1
        
        # Filter: LOI must be <= max_loi
        if survey.get("loi", 0) > max_loi:
            return False
        
        # Filter: payout must be >= min_cpi
        if survey.get("payout", 0) < min_cpi:
            return False
        
        return True
    
    def upsert_surveys(self, surveys: List[Dict[str, Any]]) -> int:
        """
        Upsert surveys into MongoDB collection
        
        Args:
            surveys: List of survey dictionaries
            
        Returns:
            Number of surveys upserted
        """
        if not surveys:
            return 0
        
        try:
            upserted_count = 0
            new_count = 0
            for survey in surveys:
                # Use $set for all fields except those that should persist
                # Use $setOnInsert for fields that should only be set on first insert:
                #   - created_at: when survey was first stored (used for click-based cleanup)
                #   - click_count: initialize to 0 (incremented by allocation service)
                #   - last_clicked_at: null until first click
                result = self.cpx_surveys_collection.update_one(
                    {"_id": survey.get("_id")},
                    {
                        "$set": survey,
                        "$setOnInsert": {
                            "created_at": datetime.utcnow(),
                            "click_count": 0,
                            "last_clicked_at": None,
                            "is_active_in_pool": False  # Default to inactive, must be activated by sync job
                        }
                    },
                    upsert=True
                )
                upserted_count += 1
                if result.upserted_id:
                    new_count += 1
            
            print(f"✅ Upserted {upserted_count} surveys into MongoDB ({new_count} new, {upserted_count - new_count} updated)")
            return upserted_count
            
        except Exception as e:
            print(f"❌ MongoDB upsert error: {e}")
            return 0
    
    def get_surveys(
        self,
        min_loi: Optional[int] = None,
        max_loi: Optional[int] = None,
        min_payout: Optional[float] = None,
        country: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        apply_default_filters: bool = True,
        active_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Get surveys from MongoDB with optional filters and pagination.
        
        Filters are applied at display time (not during ingestion) to allow
        for dynamic filtering without re-fetching from CPX API.
        
        Args:
            min_loi: Minimum LOI filter
            max_loi: Maximum LOI filter (defaults to saved max_loi setting if apply_default_filters=True)
            min_payout: Minimum payout filter (defaults to saved min_cpi setting if apply_default_filters=True)
            country: Country filter
            category: Category filter
            page: Page number (1-indexed)
            page_size: Number of surveys per page
            apply_default_filters: If True, apply saved filter settings as defaults
            active_only: If True, only return surveys that are active in the pool
            
        Returns:
            Dictionary with surveys and pagination info
        """
        # Apply default filters from saved settings if not explicitly provided
        if apply_default_filters:
            filter_settings = self.get_filter_settings()
            if max_loi is None:
                max_loi = filter_settings.get("max_loi", 20)
            if min_payout is None:
                min_payout = filter_settings.get("min_cpi", 1.0)
        
        # Build filter query
        query = {}
        
        # Filter by active status if requested
        if active_only:
            query["is_active_in_pool"] = True
        
        if min_loi is not None:
            query["loi"] = {"$gte": min_loi}
        
        if max_loi is not None:
            if "loi" in query:
                query["loi"]["$lte"] = max_loi
            else:
                query["loi"] = {"$lte": max_loi}
        
        if min_payout is not None:
            query["payout"] = {"$gte": min_payout}
        
        if country:
            query["country"] = country
        
        if category:
            query["category"] = category
        
        try:
            # Get total count
            total_count = self.cpx_surveys_collection.count_documents(query)
            
            # Calculate pagination
            skip = (page - 1) * page_size
            total_pages = (total_count + page_size - 1) // page_size
            
            # Fetch surveys
            surveys = list(
                self.cpx_surveys_collection.find(query)
                .sort("last_updated", -1)
                .skip(skip)
                .limit(page_size)
            )
            
            # Clean up and serialize surveys for JSON response
            cleaned_surveys = []
            for survey in surveys:
                # Remove raw_data to reduce response size, but keep live_link and entry_link
                if "raw_data" in survey:
                    # Preserve href/link from raw_data if live_link is not set
                    # Prefer href_new (mobile-optimized per CPX docs)
                    if not survey.get("live_link"):
                        raw = survey["raw_data"]
                        survey["live_link"] = raw.get("href_new") or raw.get("href") or raw.get("link") or ""
                    del survey["raw_data"]
                
                # Convert ObjectId to string if present
                if "_id" in survey:
                    survey["_id"] = str(survey["_id"])
                
                # Convert datetime to ISO string
                if "last_updated" in survey:
                    survey["last_updated"] = survey["last_updated"].isoformat()
                
                # Convert inserted_at to ISO string if present
                if "inserted_at" in survey:
                    survey["inserted_at"] = survey["inserted_at"].isoformat()
                
                # FIXED: Attach metrics from survey_allocation_service
                # This fixes the issue where CLICKS and COMPLETES were showing 0
                # Use defensive programming to prevent crashes
                try:
                    if self.survey_allocation_service and hasattr(self.survey_allocation_service, 'get_survey_metrics'):
                        try:
                            # Look up metrics by survey external_id
                            survey_id = survey.get("_id")
                            metrics = self.survey_allocation_service.get_survey_metrics(survey_id)
                            
                            if metrics:
                                # Attach metrics fields to survey
                                survey["clicks"] = metrics.get("sent_n", 0)  # sent_n is equivalent to "clicks"
                                survey["completes"] = metrics.get("completes_n", 0)
                                survey["incompletes"] = metrics.get("incompletes_n", 0)
                                survey["entrants"] = metrics.get("entrants_n", 0)
                                # Preserve original conversion_rate if exists
                                if not survey.get("conversion_rate"):
                                    survey["conversion_rate"] = metrics.get("conversion_rate", 0.0)
                                if not survey.get("incidence_rate"):
                                    survey["incidence_rate"] = metrics.get("incidence_rate", 0.0)
                                print(f"✅ Attached metrics for survey {survey_id}: sent={metrics.get('sent_n')}, completes={metrics.get('completes_n')}")
                            else:
                                # Initialize with default metrics if none exist, but preserve conversion_rate
                                survey["clicks"] = 0
                                survey["completes"] = 0
                                survey["incompletes"] = 0
                                survey["entrants"] = 0
                                # Only set to 0.0 if not already set
                                if not survey.get("conversion_rate"):
                                    survey["conversion_rate"] = 0.0
                                if not survey.get("incidence_rate"):
                                    survey["incidence_rate"] = 0.0
                        except AttributeError as ae:
                            print(f"⚠️ Survey allocation service missing get_survey_metrics method: {ae}")
                            survey["clicks"] = 0
                            survey["completes"] = 0
                            survey["incompletes"] = 0
                            survey["entrants"] = 0
                            # Preserve conversion_rate
                        except Exception as me:
                            print(f"⚠️ Failed to attach metrics for survey {survey.get('_id')}: {me}")
                            # Provide default values on error, preserve conversion_rate
                            survey["clicks"] = 0
                            survey["completes"] = 0
                            survey["incompletes"] = 0
                            survey["entrants"] = 0
                    else:
                        # No allocation service provided, use defaults but preserve conversion_rate
                        survey["clicks"] = 0
                        survey["completes"] = 0
                        survey["incompletes"] = 0
                        survey["entrants"] = 0
                        if not survey.get("incidence_rate"):
                            survey["incidence_rate"] = 0.0
                except Exception as outer_e:
                    print(f"❌ Unexpected error in metrics attachment: {outer_e}")
                    # Fallback defaults on any error, but preserve conversion_rate
                    survey["clicks"] = 0
                    survey["completes"] = 0
                    survey["incompletes"] = 0
                    survey["entrants"] = 0
                    # Don't overwrite conversion_rate if it exists
                
                cleaned_surveys.append(survey)
            
            # Get the most recent last_updated timestamp
            last_updated = None
            if cleaned_surveys:
                last_updated = cleaned_surveys[0].get("last_updated")  # Already sorted by last_updated desc
            
            return {
                "surveys": cleaned_surveys,
                "total": total_count,
                "last_updated": last_updated,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total_count,
                    "total_pages": total_pages,
                },
            }
            
        except Exception as e:
            print(f"❌ Error fetching surveys: {e}")
            return {"surveys": [], "pagination": {"page": page, "page_size": page_size, "total": 0, "total_pages": 0}}
    
    def save_filter_settings(self, filters: Dict[str, Any]) -> bool:
        """
        Save filter settings to MongoDB
        
        Args:
            filters: Dictionary of filter settings
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.cpx_filters_collection.update_one(
                {"_id": "default"},
                {"$set": {**filters, "last_updated": datetime.utcnow()}},
                upsert=True
            )
            print("✅ Filter settings saved")
            return True
        except Exception as e:
            print(f"❌ Error saving filter settings: {e}")
            return False
    
    def get_filter_settings(self) -> Dict[str, Any]:
        """
        Get saved filter settings from MongoDB settings database (torpedo_settings.app_settings)
        
        Returns:
            Dictionary of filter settings with sensible defaults
        """
        # Default filter settings that are permissive
        defaults = {
            "max_loi": 20,  # 20 minutes max LOI
            "min_cpi": 1.0,  # $1 min payout
            "min_ir": 0,    # 0% min incidence rate (no filter by default)
            "deletion_period_days": 7,
            "auto_refresh_enabled": True,
            "refresh_interval_seconds": 60,
        }
        
        # First try settings_collection (torpedo_settings.app_settings with key "survey_filters")
        if self.settings_collection is not None:
            try:
                settings = self.settings_collection.find_one({"_id": "survey_filters"})
                if settings:
                    return {
                        "max_loi": settings.get("max_loi", defaults["max_loi"]),
                        "min_cpi": settings.get("min_cpi", defaults["min_cpi"]),
                        "min_ir": settings.get("min_ir", defaults["min_ir"]),
                        "deletion_period_days": settings.get("deletion_period_days", defaults["deletion_period_days"]),
                        "auto_refresh_enabled": settings.get("auto_refresh_enabled", defaults["auto_refresh_enabled"]),
                        "refresh_interval_seconds": settings.get("refresh_interval_seconds", defaults["refresh_interval_seconds"]),
                    }
            except Exception as e:
                print(f"❌ Error fetching filter settings from settings_collection: {e}")
        
        # Fallback to cpx_filters_collection for backward compatibility
        try:
            if self.cpx_filters_collection is not None:
                settings = self.cpx_filters_collection.find_one({"_id": "default"})
                if settings:
                    settings.pop("_id", None)
                    settings.pop("last_updated", None)
                    return {**defaults, **settings}
        except Exception as e:
            print(f"❌ Error fetching filter settings from cpx_filters: {e}")
        
        return defaults
    
    def sync_active_status_by_filters(self) -> Dict[str, Any]:
        """
        Apply filter settings to ALL surveys and mark them as active/inactive.
        Surveys that pass the filter criteria get is_active_in_pool=true,
        others get is_active_in_pool=false.
        
        Returns:
            Dictionary with counts of active/inactive surveys
        """
        try:
            # Get current filter settings
            filter_settings = self.get_filter_settings()
            max_loi = filter_settings.get("max_loi", 20)
            min_cpi = filter_settings.get("min_cpi", 1.0)
            
            print(f"📊 Syncing active status with filters: max_loi={max_loi}, min_cpi={min_cpi}")
            
            # Count ALL surveys first
            total_surveys = self.cpx_surveys_collection.count_documents({})
            
            # Build query for surveys that PASS the filters (active surveys)
            active_query = {
                "$and": [
                    {"$or": [
                        {"loi": {"$lte": max_loi}},
                        {"loi": {"$exists": False}},
                        {"loi": None}
                    ]},
                    {"$or": [
                        {"payout": {"$gte": min_cpi}},
                        {"payout": {"$exists": False}},
                        {"payout": None}
                    ]}
                ]
            }
            
            # Mark all surveys matching active_query as is_active_in_pool=true
            active_result = self.cpx_surveys_collection.update_many(
                active_query,
                {"$set": {"is_active_in_pool": True}}
            )
            active_count = active_result.modified_count
            
            # Mark all OTHER surveys as is_active_in_pool=false
            inactive_result = self.cpx_surveys_collection.update_many(
                {"$nor": [active_query]},
                {"$set": {"is_active_in_pool": False}}
            )
            inactive_count = inactive_result.modified_count
            
            # Get actual counts after update
            actual_active = self.cpx_surveys_collection.count_documents({"is_active_in_pool": True})
            actual_inactive = self.cpx_surveys_collection.count_documents({"is_active_in_pool": False})
            
            print(f"✅ Active status synced: {actual_active} active, {actual_inactive} inactive (total: {total_surveys})")
            
            return {
                "success": True,
                "message": f"Synced active status for {total_surveys} surveys",
                "total": total_surveys,
                "active": actual_active,
                "inactive": actual_inactive,
                "filters_applied": {
                    "max_loi": max_loi,
                    "min_cpi": min_cpi
                }
            }
            
        except Exception as e:
            print(f"❌ Error syncing active status: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "total": 0,
                "active": 0,
                "inactive": 0
            }
    
    def cleanup_old_surveys(self, days: int = 3) -> int:
        """
        Delete surveys that have received 0 clicks and are older than specified days.
        
        Click-based cleanup logic:
        - Surveys with click_count > 0 are kept indefinitely (or until separate expiry)
        - Surveys with click_count == 0 AND created_at > X days ago are deleted
        
        Args:
            days: Number of days after which unclicked surveys should be deleted (default: 3)
            
        Returns:
            Number of surveys deleted
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Delete surveys where:
            # 1. click_count is 0, null, or doesn't exist AND
            # 2. created_at is older than cutoff_date
            result = self.cpx_surveys_collection.delete_many({
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
                                    {"last_updated": {"$lt": cutoff_date}}
                                ]
                            }
                        ]
                    }
                ]
            })
            
            deleted_count = result.deleted_count
            if deleted_count > 0:
                print(f"🗑️  Cleaned up {deleted_count} unclicked surveys older than {days} days")
            
            return deleted_count
            
        except Exception as e:
            print(f"❌ Error cleaning up old surveys: {e}")
            return 0
