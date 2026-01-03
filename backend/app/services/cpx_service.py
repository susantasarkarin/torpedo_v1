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
        """
        self.app_id = app_id
        self.ext_user_id = ext_user_id
        self.secure_hash_key = secure_hash_key
        self.api_timeout = api_timeout
        self.fetch_limit = fetch_limit
        self.settings_collection = settings_collection
        
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
        live_link: str,
        respondent_id: str,
    ) -> str:
        """
        Generate CPX survey entry link by appending required parameters to live_link.
        
        Args:
            live_link: The base live link from CPX API (href or href_new)
            respondent_id: The respondent ID to use as ext_user_id (unique per user)
            
        Returns:
            Fully constructed entry URL with required parameters appended
        """
        if not live_link:
            return ""
            
        # Generate secure hash using respondent_id as ext_user_id
        # Formula: md5({unique_user_id}-{app_secure_hash})
        secure_hash = self._generate_secure_hash(respondent_id, self.secure_hash_key)
        
        # Build additional query parameters to append
        additional_params = (
            f"&ext_user_id={respondent_id}"
            f"&app_id={self.app_id}"
            f"&secure_hash={secure_hash}"
        )
        
        return f"{live_link}{additional_params}"
    
    def generate_entry_link_template(self, live_link: str) -> str:
        """
        Generate a template entry link by appending placeholders to live_link.
        Used for display purposes - actual values should be substituted at runtime.
        
        Args:
            live_link: The base live link from CPX API (href or href_new)
            
        Returns:
            Entry URL template with placeholders appended to live_link
        """
        if not live_link:
            return ""
            
        template = (
            f"{live_link}"
            f"&ext_user_id={{ext_user_id}}"
            f"&app_id={self.app_id}"
            f"&secure_hash={{secure_hash}}"
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
            
            # Normalize and filter surveys
            normalized_surveys = []
            for survey in surveys:
                normalized = self._normalize_survey(survey)
                
                # Apply filters
                if self._apply_filters(normalized):
                    normalized_surveys.append(normalized)
            
            print(f"✅ Fetched {len(normalized_surveys)} CPX surveys (before filters: {len(surveys)})")
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
        
        # Get country with default to IN if missing
        country = survey.get("survey_country") or survey.get("country", "") or "IN"
        
        # Get live link from raw survey data if available
        live_link = survey.get("href") or survey.get("href_new") or survey.get("link") or ""
        
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
            "live_link": live_link,  # Store live link from CPX API
            "raw_data": survey,  # Store raw data for reference
        }
        
        # Generate entry_link by appending parameters to live_link
        if respondent_id and live_link:
            normalized["entry_link"] = self.generate_entry_link(
                live_link=live_link,
                respondent_id=respondent_id
            )
        elif live_link:
            # Generate entry_link template with placeholders appended to live_link
            normalized["entry_link"] = self.generate_entry_link_template(
                live_link=live_link
            )
        else:
            normalized["entry_link"] = ""
        
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
            for survey in surveys:
                # Use $set for all fields except inserted_at
                # Use $setOnInsert for inserted_at to preserve original insert time
                result = self.cpx_surveys_collection.update_one(
                    {"_id": survey.get("_id")},
                    {
                        "$set": survey,
                        "$setOnInsert": {"inserted_at": datetime.utcnow()}
                    },
                    upsert=True
                )
                upserted_count += 1
            
            print(f"✅ Upserted {upserted_count} surveys into MongoDB")
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
    ) -> Dict[str, Any]:
        """
        Get surveys from MongoDB with optional filters and pagination
        
        Args:
            min_loi: Minimum LOI filter
            max_loi: Maximum LOI filter
            min_payout: Minimum payout filter
            country: Country filter
            category: Category filter
            page: Page number (1-indexed)
            page_size: Number of surveys per page
            
        Returns:
            Dictionary with surveys and pagination info
        """
        # Build filter query
        query = {}
        
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
    
    def cleanup_old_surveys(self, days: int = 3) -> int:
        """
        Delete surveys that are older than specified number of days
        
        Args:
            days: Number of days after which surveys should be deleted (default: 3)
            
        Returns:
            Number of surveys deleted
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Delete surveys where last_updated is older than cutoff_date
            result = self.cpx_surveys_collection.delete_many({
                "last_updated": {"$lt": cutoff_date}
            })
            
            deleted_count = result.deleted_count
            if deleted_count > 0:
                print(f"🗑️  Cleaned up {deleted_count} surveys older than {days} days")
            
            return deleted_count
            
        except Exception as e:
            print(f"❌ Error cleaning up old surveys: {e}")
            return 0
