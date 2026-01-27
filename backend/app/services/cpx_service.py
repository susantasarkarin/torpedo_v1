import os
import requests
import hashlib
from urllib.parse import quote, urlencode
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient


class CPXService:
    """Service to interact with CPX Research API"""
    
    BASE_URL = "https://live-api.cpx-research.com/api/get-surveys.php"
    ENTRY_URL = "https://offers.cpx-research.com/index.php"  # Direct entry URL for survey redirects
    
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
        href: Optional[str] = None,  # Not used - kept for backward compatibility
        username: Optional[str] = None,
        email: Optional[str] = None,
        live_link: Optional[str] = None,  # Not used - kept for backward compatibility
    ) -> str:
        """
        Generate CPX survey entry link using the offers.cpx-research.com format.
        
        URL format:
        https://offers.cpx-research.com/index.php?app_id={app_id}&ext_user_id={ext_user_id}&secure_hash={secure_hash}&survey_id={survey_id}&subid_1={subid_1}
        
        Args:
            survey_id: The CPX survey ID
            respondent_id: The respondent ID (ext_user_id) for tracking
            subid_1: Optional tracking parameter (defaults to respondent_id)
            subid_2: Optional tracking parameter
            href: Not used - kept for backward compatibility
            username: Optional username (not used)
            email: Optional email (not used)
            live_link: Not used - kept for backward compatibility
            
        Returns:
            CPX entry URL in offers.cpx-research.com format
        """
        if not survey_id or not respondent_id:
            return ""
        
        # Always generate the offers.cpx-research.com/index.php format
        # This is the correct format per CPX documentation
        secure_hash = self._generate_secure_hash(respondent_id, self.secure_hash_key)
        
        from urllib.parse import urlencode
        
        params = {
            "app_id": self.app_id,
            "ext_user_id": respondent_id,
            "secure_hash": secure_hash,
            "survey_id": survey_id,
            "subid_1": subid_1 or respondent_id,
        }
        if subid_2:
            params["subid_2"] = subid_2
            
        return f"{self.ENTRY_URL}?{urlencode(params)}"
    
    def generate_entry_link_template(self, survey_id: str) -> str:
        """
        Generate a template entry link with placeholders for runtime substitution.
        Used for display purposes - actual values should be substituted at allocation time.
        
        Template format per CPX documentation:
        https://offers.cpx-research.com/index.php?app_id={app_id}&ext_user_id={ext_user_id}&secure_hash={secure_hash}&survey_id={survey_id}
        
        Args:
            survey_id: The CPX survey ID
            
        Returns:
            Entry URL template with placeholders
        """
        if not survey_id:
            return ""
            
        template = (
            f"{self.ENTRY_URL}"
            f"?app_id={self.app_id}"
            f"&ext_user_id={{ext_user_id}}"
            f"&secure_hash={{secure_hash}}"
            f"&survey_id={survey_id}"
            f"&subid_1={{subid_1}}"
        )
        return template
    
    @staticmethod
    def _get_client_ip() -> str:
        """
        Get IP address for CPX API requests.
        
        Uses a hardcoded Indian IP to ensure CPX API works regardless of
        server location (e.g., when deployed on US-based VMs).
        
        Returns:
            Indian IP address for geo-targeting
        """
        # Hardcoded Indian IP address for CPX API geo-targeting
        # This ensures CPX API returns India-relevant surveys regardless of server location
        # Using a Mumbai (Maharashtra) IP address
        INDIAN_IP = "103.21.124.1"  # Indian IP (Mumbai region)
        
        return INDIAN_IP
    
    @staticmethod
    def _get_user_agent() -> str:
        """
        Get default user agent for requests
        Returns:
            User agent string
        """
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

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
        Fetch surveys from CPX Research API
        
        Returns:
            List of normalized survey dictionaries
        """
        try:
            # Generate secure hash
            secure_hash = self._generate_secure_hash(self.ext_user_id, self.secure_hash_key)
            
            # Get client IP and user agent
            client_ip = self._get_client_ip()
            user_agent = self._get_user_agent()
            
            # Build query parameters
            params = {
                "app_id": self.app_id,
                "ext_user_id": self.ext_user_id,
                "subid_1": "",
                "subid_2": "",
                "output_method": "api",
                "ip_user": quote(client_ip),
                "user_agent": quote(user_agent),
                "limit": self.fetch_limit,
                "secure_hash": secure_hash,
            }
            
            # Make request to CPX API
            print(f"🔄 Fetching CPX surveys with limit={self.fetch_limit}...")
            response = requests.get(
                self.BASE_URL,
                params=params,
                timeout=self.api_timeout
            )
            response.raise_for_status()
            
            data = response.json()
            print(f"📥 CPX API Response: {data}")
            
            # Handle API response
            if not isinstance(data, dict):
                print(f"⚠️  Unexpected CPX API response format: {type(data)}")
                return []
            
            # Handle multiple response formats (like the working script)
            surveys = []
            
            # Format 1: Direct surveys list
            if isinstance(data.get("surveys"), list) and len(data["surveys"]) > 0:
                surveys = data["surveys"]
                print(f"📋 Found {len(surveys)} surveys in 'surveys' key")
            
            # Format 2: Using count_available_surveys and info key
            elif data.get("count_available_surveys", 0) > 0:
                info_list = data.get("info", [])
                if isinstance(info_list, list) and len(info_list) > 0:
                    surveys = info_list
                    print(f"📋 Found {len(surveys)} surveys in 'info' key")
            
            # Format 3: No surveys message
            elif data.get("message_not_found"):
                print("ℹ️  No surveys available (message_not_found)")
                return []
            
            if not surveys:
                print("ℹ️  No surveys returned from CPX API")
                return []
            
            # Normalize surveys (store ALL surveys without filtering)
            # Filters are now applied only during display/routing, not during ingestion
            normalized_surveys = []
            for survey in surveys:
                normalized = self._normalize_survey(survey)
                normalized_surveys.append(normalized)
            
            print(f"✅ Fetched {len(normalized_surveys)} CPX surveys (storing all without filtering)")
            return normalized_surveys
            
        except requests.exceptions.Timeout:
            print(f"❌ CPX API timeout (>{self.api_timeout}s)")
            return []
        except requests.exceptions.RequestException as e:
            print(f"❌ CPX API request failed: {e}")
            return []
        except Exception as e:
            print(f"❌ CPX fetch error: {e}")
            return []
    
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
        
        # Get href and href_new from CPX API response (stored for reference only)
        href = survey.get("href") or ""
        href_new = survey.get("href_new") or ""
        
        # Generate live_link using the correct offers.cpx-research.com/index.php format
        # Format: https://offers.cpx-research.com/index.php?app_id={app_id}&ext_user_id={ext_user_id}&secure_hash={secure_hash}&survey_id={survey_id}&subid_1={subid_1}
        # Note: The entry_link template uses placeholders, actual values are filled at allocation time
        live_link = self.generate_entry_link_template(survey_id=str(survey_id))
        
        # Map CPX field names to internal field names
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
            "href": href,          # Original href from CPX (stored for reference)
            "href_new": href_new,  # Mobile-optimized href from CPX (stored for reference)
            "live_link": live_link,  # Entry link template in offers.cpx-research.com format
            "raw_data": survey,  # Store raw data for reference
            # Click tracking fields - used for click-based cleanup
            # click_count and last_clicked_at are set via $setOnInsert to preserve existing values
        }
        
        # Generate entry_link using direct URL format (with survey_id)
        # Note: The actual respondent-specific entry_link is generated at allocation time
        if respondent_id:
            normalized["entry_link"] = self.generate_entry_link(
                survey_id=str(survey_id),
                respondent_id=respondent_id
            )
        else:
            # Generate entry_link template with placeholders for later substitution
            normalized["entry_link"] = self.generate_entry_link_template(
                survey_id=str(survey_id)
            )
        
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
                    if not survey.get("live_link"):
                        raw = survey["raw_data"]
                        survey["live_link"] = raw.get("href") or raw.get("href_new") or raw.get("link") or ""
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
