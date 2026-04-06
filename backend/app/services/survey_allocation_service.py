"""
Survey Allocation & Quality Control Engine - Core Service

Implements:
- Survey eligibility filtering
- Atomic allocation logic (no double-allocation)
- Event handlers for survey callbacks
- Auto-pause evaluation logic
- Batch management
"""
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pymongo import MongoClient, ReturnDocument, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from dotenv import load_dotenv
import hashlib
import secrets
import time
from app.services.cpx_service import CPXService

# Load environment
load_dotenv()

# Import models
try:
    from ..models.survey_allocation import (
        Respondent, RespondentCreate, RespondentStatus, RespondentUpdate,
        Survey, SurveyCreate, SurveyStatus, SurveyUpdate,
        SurveyMetrics, AllocationSettings,
        AllocationRequest, AllocationResponse,
        CallbackEvent, CallbackResponse
    )
except ImportError:
    from app.models.survey_allocation import (
        Respondent, RespondentCreate, RespondentStatus, RespondentUpdate,
        Survey, SurveyCreate, SurveyStatus, SurveyUpdate,
        SurveyMetrics, AllocationSettings,
        AllocationRequest, AllocationResponse,
        CallbackEvent, CallbackResponse
    )


class SurveyAllocationService:
    """
    Core service for survey allocation and quality control.
    
    Handles:
    - Respondent management
    - Survey inventory management
    - Atomic allocation with locking
    - Performance metrics tracking
    - Auto-pause evaluation
    """
    
    def __init__(self, mongo_uri: str = None):
        """Initialize service with MongoDB connection"""
        self.mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(self.mongo_uri)
        self.db = self.client["survey_allocation"]
        
        # Collections
        self.respondents = self.db["respondents"]
        self.surveys = self.db["surveys"]
        self.metrics = self.db["survey_metrics"]
        self.allocation_log = self.db["allocation_log"]
        
        # CPX and CINT survey collections for click tracking
        # These are the source survey pools that need click_count updates
        self.cpx_surveys = self.client["cpx_research"]["cpx_surveys"]
        self.cint_surveys = self.client["cint_research"]["cint_surveys"]
        
        # Settings collection (shared with main settings)
        self.settings_db = self.client["torpedo_settings"]
        self.settings_collection = self.settings_db["app_settings"]
        
        # Create indexes for performance and uniqueness
        self._create_indexes()
        
        print("✅ Survey Allocation Service initialized")
    
    def _create_indexes(self):
        """Create MongoDB indexes for optimal performance"""
        try:
            # Respondent indexes
            self.respondents.create_index(
                [("vid", ASCENDING), ("rid", ASCENDING)],
                unique=True,
                name="unique_vendor_respondent"
            )
            self.respondents.create_index([("status", ASCENDING)])
            self.respondents.create_index([("survey_id", ASCENDING)])
            self.respondents.create_index([("created_at", DESCENDING)])
            
            # Survey indexes
            self.surveys.create_index(
                [("external_id", ASCENDING), ("provider", ASCENDING)],
                unique=True,
                name="unique_provider_survey"
            )
            self.surveys.create_index([("status", ASCENDING)])
            self.surveys.create_index([("country_codes", ASCENDING)])
            self.surveys.create_index([("remaining_quota", DESCENDING)])
            
            # Metrics indexes
            self.metrics.create_index([("survey_id", ASCENDING)], unique=True)
            
            # Allocation log indexes
            self.allocation_log.create_index([("respondent_id", ASCENDING)])
            self.allocation_log.create_index([("survey_id", ASCENDING)])
            self.allocation_log.create_index([("timestamp", DESCENDING)])
            
            print("✅ Survey Allocation indexes created")
        except Exception as e:
            print(f"⚠️ Index creation issue: {e}")
    
    # ============================================
    # Settings Management
    # ============================================
    
    def get_allocation_settings(self) -> AllocationSettings:
        """Get allocation settings from database with defaults (cached 60s)"""
        now = time.time()
        cached = getattr(self, "_alloc_settings_cache", None)
        cached_ts = getattr(self, "_alloc_settings_ts", 0)
        if cached is not None and now - cached_ts < 60:
            return cached
        try:
            stored = self.settings_collection.find_one({"_id": "allocation_settings"}, max_time_ms=5000)
            if stored:
                result = AllocationSettings(
                    batch_size=stored.get("batch_size", 100),
                    buffer_multiplier=stored.get("buffer_multiplier", 1.2),
                    max_incomplete_rate=stored.get("max_incomplete_rate", 40.0),
                    min_incidence_rate=stored.get("min_incidence_rate", 10.0),
                    minimum_entrants_for_evaluation=stored.get("minimum_entrants_for_evaluation", 50),
                    auto_pause_enabled=stored.get("auto_pause_enabled", True),
                    pause_cooldown_minutes=stored.get("pause_cooldown_minutes", 30),
                    prefer_high_ir_surveys=stored.get("prefer_high_ir_surveys", True),
                    prefer_high_cpi_surveys=stored.get("prefer_high_cpi_surveys", False)
                )
                self._alloc_settings_cache = result
                self._alloc_settings_ts = now
                return result
        except Exception as e:
            print(f"⚠️ Error loading allocation settings: {e}")
        
        return AllocationSettings()  # Return defaults
    
    def save_allocation_settings(self, settings: AllocationSettings) -> bool:
        """Save allocation settings to database"""
        try:
            self.settings_collection.update_one(
                {"_id": "allocation_settings"},
                {
                    "$set": {
                        **settings.model_dump(),
                        "last_updated": datetime.utcnow()
                    }
                },
                upsert=True
            )
            # Invalidate cache on save
            self._alloc_settings_cache = None
            self._alloc_settings_ts = 0
            return True
        except Exception as e:
            print(f"❌ Error saving allocation settings: {e}")
            return False
    
    # ============================================
    # Respondent Management
    # ============================================
    
    def get_or_create_respondent(self, request: AllocationRequest) -> Tuple[dict, bool]:
        """
        Get existing respondent or create new one.
        Returns (respondent_doc, is_new)
        """
        # Try to find existing respondent
        existing = self.respondents.find_one({
            "vid": request.vid,
            "rid": request.rid
        })
        
        if existing:
            return existing, False
        
        # Create new respondent
        new_respondent = {
            "vid": request.vid,
            "cc": request.cc,
            "rid": request.rid,
            "status": RespondentStatus.NEW.value,
            "created_at": datetime.utcnow(),
            "ip_address": request.ip_address,
            "user_agent": request.user_agent,
            "session_id": secrets.token_hex(16)
        }
        
        try:
            result = self.respondents.insert_one(new_respondent)
            new_respondent["_id"] = result.inserted_id
            return new_respondent, True
        except DuplicateKeyError:
            # Race condition - respondent was just created
            return self.respondents.find_one({
                "vid": request.vid,
                "rid": request.rid
            }), False
    
    def get_respondent(self, respondent_id: str) -> Optional[dict]:
        """Get respondent by ID"""
        try:
            return self.respondents.find_one({"_id": ObjectId(respondent_id)})
        except Exception:
            return None
    
    def get_respondent_by_vendor(self, vid: str, rid: str) -> Optional[dict]:
        """Get respondent by vendor ID and respondent ID"""
        return self.respondents.find_one({"vid": vid, "rid": rid})
    
    def update_respondent_status(
        self, 
        respondent_id: str, 
        status: RespondentStatus,
        additional_data: dict = None
    ) -> Optional[dict]:
        """Update respondent status with optional additional data"""
        update_data = {
            "status": status.value,
            "updated_at": datetime.utcnow()
        }
        
        # Add timestamp based on status
        if status == RespondentStatus.STARTED:
            update_data["started_at"] = datetime.utcnow()
        elif status == RespondentStatus.COMPLETED:
            update_data["completed_at"] = datetime.utcnow()
        elif status in [RespondentStatus.TERMINATED, RespondentStatus.QUOTA_FULL]:
            update_data["terminated_at"] = datetime.utcnow()
        
        if additional_data:
            update_data.update(additional_data)
        
        try:
            return self.respondents.find_one_and_update(
                {"_id": ObjectId(respondent_id)},
                {"$set": update_data},
                return_document=ReturnDocument.AFTER
            )
        except Exception as e:
            print(f"❌ Error updating respondent: {e}")
            return None
    
    # ============================================
    # Survey Management
    # ============================================
    
    def upsert_survey(self, survey_data: SurveyCreate) -> dict:
        """Insert or update a survey from provider"""
        survey_dict = survey_data.model_dump()
        survey_dict["updated_at"] = datetime.utcnow()
        
        result = self.surveys.find_one_and_update(
            {
                "external_id": survey_data.external_id,
                "provider": survey_data.provider
            },
            {
                "$set": survey_dict,
                "$setOnInsert": {
                    "created_at": datetime.utcnow(),
                    "status": SurveyStatus.ACTIVE.value,
                    "current_batch_sent": 0,
                    "total_allocations": 0
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        
        # Ensure metrics exist for this survey
        self._ensure_metrics(str(result["_id"]))
        
        return result
    
    def get_survey(self, survey_id: str) -> Optional[dict]:
        """Get survey by ID"""
        try:
            return self.surveys.find_one({"_id": ObjectId(survey_id)})
        except Exception:
            return None
    
    def get_active_surveys(self, country_code: str = None) -> List[dict]:
        """Get all active surveys, optionally filtered by country
        
        Surveys with country_codes containing "ALL" are included for any country
        (used by CPX which handles country routing internally)
        """
        query = {"status": SurveyStatus.ACTIVE.value}
        
        if country_code:
            # Match either the specific country code OR "ALL" (global surveys)
            query["$or"] = [
                {"country_codes": country_code.upper()},
                {"country_codes": "ALL"}
            ]
        
        return list(self.surveys.find(query))
    
    def update_survey_status(
        self, 
        survey_id: str, 
        status: SurveyStatus,
        reason: str = None
    ) -> Optional[dict]:
        """Update survey status"""
        update_data = {
            "status": status.value,
            "updated_at": datetime.utcnow()
        }
        
        if status == SurveyStatus.PAUSED:
            update_data["paused_at"] = datetime.utcnow()
            update_data["paused_reason"] = reason
        
        try:
            return self.surveys.find_one_and_update(
                {"_id": ObjectId(survey_id)},
                {"$set": update_data},
                return_document=ReturnDocument.AFTER
            )
        except Exception as e:
            print(f"❌ Error updating survey status: {e}")
            return None
    
    # ============================================
    # Survey Eligibility Filtering
    # ============================================
    
    def get_eligible_surveys(self, country_code: str) -> List[dict]:
        """
        Get surveys eligible for allocation based on:
        - Active status
        - Country match (or country_codes contains "ALL" for global surveys like CPX)
        - Remaining quota > 0
        - Batch not full
        """
        settings = self.get_allocation_settings()
        
        # Calculate max allocations per batch with buffer
        max_batch_allocations = int(settings.batch_size * settings.buffer_multiplier)
        
        # Query for surveys matching the specific country OR surveys with "ALL" (global surveys)
        # CPX surveys use "ALL" to indicate they handle country routing internally
        query = {
            "status": SurveyStatus.ACTIVE.value,
            "$or": [
                {"country_codes": country_code.upper()},
                {"country_codes": "ALL"}  # Include global surveys (e.g., CPX)
            ],
            "remaining_quota": {"$gt": 0},
            "current_batch_sent": {"$lt": max_batch_allocations}
        }
        
        # Build sort order based on preferences
        sort_order = []
        if settings.prefer_high_ir_surveys:
            sort_order.append(("ir", DESCENDING))
        if settings.prefer_high_cpi_surveys:
            sort_order.append(("cpi", DESCENDING))
        sort_order.append(("remaining_quota", DESCENDING))
        
        return list(self.surveys.find(query).sort(sort_order))
    
    def select_best_survey(self, eligible_surveys: List[dict]) -> Optional[dict]:
        """
        Select the best survey from eligible list.
        Currently returns first (already sorted by preference).
        Can be extended for more complex selection logic.
        """
        if not eligible_surveys:
            return None
        
        return eligible_surveys[0]
    
    # ============================================
    # Allocation Logic (Atomic)
    # ============================================
    
    def allocate_respondent(self, request: AllocationRequest) -> AllocationResponse:
        """
        Main allocation entry point.
        
        Implements atomic allocation to prevent double-allocation:
        1. Get or create respondent
        2. Check if already allocated (if so, allow re-allocation by resetting status)
        3. Find eligible surveys
        4. Atomically assign survey to respondent
        5. Update survey allocation count
        6. Return entry link
        
        NOTE: CPX integration fix - allows re-allocation of respondents who have completed/terminated
        previous surveys. This fixes the "already_clicked / no" issue where all traffic was being
        rejected due to respondents being in ALLOCATED/COMPLETED/TERMINATED status.
        """
        # Step 1: Get or create respondent
        respondent, is_new = self.get_or_create_respondent(request)
        respondent_id = str(respondent["_id"])
        
        # Step 2: Check if already allocated
        if respondent.get("status") != RespondentStatus.NEW.value:
            # FIXED: Instead of rejecting, reset status to NEW to allow re-allocation
            # This fixes the CPX issue where "already_clicked / no" was blocking all traffic
            print(f"⚠️ Respondent {respondent_id} in status {respondent.get('status')}, resetting to NEW for re-allocation")
            
            try:
                reset_result = self.respondents.find_one_and_update(
                    {"_id": ObjectId(respondent_id)},
                    {
                        "$set": {
                            "status": RespondentStatus.NEW.value,
                            "reset_at": datetime.utcnow(),
                            "reset_count": (respondent.get("reset_count", 0) or 0) + 1,
                            # Clear previous allocation data
                            "survey_id": None,
                            "survey_name": None,
                            "entry_link": None,
                            "allocation_id": None,
                            "vendor_redirect_url": None
                        }
                    },
                    return_document=ReturnDocument.AFTER
                )
                
                if reset_result:
                    respondent = reset_result
                    print(f"✅ Reset respondent {respondent_id} to NEW status for re-allocation")
                else:
                    print(f"❌ Failed to reset respondent {respondent_id}")
                    return AllocationResponse(
                        success=False,
                        message="Failed to reset respondent for re-allocation",
                        respondent_id=respondent_id
                    )
            except Exception as e:
                print(f"❌ Error resetting respondent {respondent_id}: {e}")
                return AllocationResponse(
                    success=False,
                    message=f"Error resetting respondent: {str(e)}",
                    respondent_id=respondent_id
                )
        
        # Step 3: Find eligible surveys
        eligible_surveys = self.get_eligible_surveys(request.cc)
        
        if not eligible_surveys:
            return AllocationResponse(
                success=False,
                message="No eligible surveys available",
                respondent_id=respondent_id
            )
        
        # Step 4: Try to allocate atomically
        for survey in eligible_surveys:
            allocation_result = self._try_atomic_allocation(
                respondent_id=respondent_id,
                survey=survey,
                request=request
            )
            
            if allocation_result:
                return allocation_result
        
        # All surveys failed allocation (race conditions or full batches)
        return AllocationResponse(
            success=False,
            message="Failed to allocate survey (all batches full)",
            respondent_id=respondent_id
        )
    
    def _try_atomic_allocation(
        self, 
        respondent_id: str, 
        survey: dict,
        request: AllocationRequest
    ) -> Optional[AllocationResponse]:
        """
        Attempt atomic allocation to a specific survey.
        Uses findOneAndUpdate with conditions to prevent race conditions.
        """
        settings = self.get_allocation_settings()
        survey_id = str(survey["_id"])
        max_batch = int(settings.batch_size * settings.buffer_multiplier)
        
        # Generate unique allocation ID
        allocation_id = f"alloc_{secrets.token_hex(8)}"
        
        # Build entry link with tracking parameters
        entry_link = self._build_entry_link(
            survey=survey,
            respondent_id=respondent_id,
            allocation_id=allocation_id,
            user_ip=request.ip_address
        )

        if not entry_link:
            try:
                self.respondents.update_one(
                    {"_id": ObjectId(respondent_id)},
                    {
                        "$set": {
                            "status": RespondentStatus.TERMINATED.value,
                            "terminated_at": datetime.utcnow(),
                            "termination_reason": "CPX survey unavailable"
                        }
                    }
                )
            except Exception as e:
                print(f"⚠️ Failed to mark respondent {respondent_id} as terminated: {e}")

            return AllocationResponse(
                success=False,
                message="Respondent terminated: CPX survey unavailable",
                respondent_id=respondent_id,
                survey_id=survey_id
            )
        
        # Vendor redirect URL (for complete/terminate callbacks)
        vendor_redirect_base = os.getenv("API_BASE", "http://localhost:8000")
        vendor_redirect_url = f"{vendor_redirect_base}/api/survey-allocation/callback"
        
        # Step 4a: Atomically update survey (increment allocation count)
        survey_update = self.surveys.find_one_and_update(
            {
                "_id": ObjectId(survey_id),
                "status": SurveyStatus.ACTIVE.value,
                "current_batch_sent": {"$lt": max_batch},
                "remaining_quota": {"$gt": 0}
            },
            {
                "$inc": {
                    "current_batch_sent": 1,
                    "total_allocations": 1
                },
                "$set": {"updated_at": datetime.utcnow()}
            },
            return_document=ReturnDocument.AFTER
        )
        
        if not survey_update:
            # Survey no longer eligible (race condition or full)
            return None
        
        # Step 4b: Atomically update respondent (only if still NEW)
        respondent_update = self.respondents.find_one_and_update(
            {
                "_id": ObjectId(respondent_id),
                "status": RespondentStatus.NEW.value
            },
            {
                "$set": {
                    "status": RespondentStatus.ALLOCATED.value,
                    "survey_id": survey_id,
                    "survey_name": survey.get("name"),
                    "vendor_redirect_url": vendor_redirect_url,
                    "entry_link": entry_link,
                    "allocation_id": allocation_id,
                    "allocation_timestamp": datetime.utcnow()
                }
            },
            return_document=ReturnDocument.AFTER
        )
        
        if not respondent_update:
            # Respondent was allocated by another request - rollback survey count
            self.surveys.update_one(
                {"_id": ObjectId(survey_id)},
                {"$inc": {"current_batch_sent": -1, "total_allocations": -1}}
            )
            return None
        
        # Step 4c: Update metrics
        self._increment_metric(survey_id, "sent_n")
        
        # Step 4d: Increment click count on source survey (CPX/CINT collection)
        # This tracks clicks for the click-based cleanup logic
        self._increment_survey_click_count(survey)
        
        # Step 4e: Log allocation
        self._log_allocation(
            respondent_id=respondent_id,
            survey_id=survey_id,
            allocation_id=allocation_id,
            request=request
        )
        
        return AllocationResponse(
            success=True,
            message="Survey allocated successfully",
            respondent_id=respondent_id,
            survey_id=survey_id,
            survey_name=survey.get("name"),
            entry_link=entry_link,
            allocation_id=allocation_id
        )
    
    def _build_entry_link(
        self, 
        survey: dict, 
        respondent_id: str,
        allocation_id: str,
        user_ip: Optional[str] = None
    ) -> str:
        """
        Build survey entry link with tracking parameters.
        
        For CPX surveys: Generates unique entry link per respondent using
        click.cpx-research.com with fresh secure_hash per CPX API contract.
        
        For other providers: Appends tracking parameters to stored entry_url.
        """
        provider = survey.get("provider", "").upper()
        
        # CPX requires using the href from the API with k= parameter
        # Just append subid_1 and subid_2 to the existing href
        if provider == "CPX":
            return self._build_cpx_entry_link(
                survey=survey,  # Pass full survey to access href
                respondent_id=respondent_id,
                user_ip=user_ip
            )
        
        # Default: append tracking parameters to stored entry_url
        base_url = survey.get("entry_url", "")
        separator = "&" if "?" in base_url else "?"
        tracking_params = f"resp_id={respondent_id}&alloc_id={allocation_id}"
        
        return f"{base_url}{separator}{tracking_params}"
    
    def _build_cpx_entry_link(
        self,
        survey: dict,
        respondent_id: str,
        user_ip: Optional[str] = None
    ) -> str:
        """
        Build CPX entry link using per-respondent CPX API call.
        
        PER-RESPONDENT FLOW (scales to 500+ simultaneous starts):
        1. Call CPX API with respondent's SFWID as ext_user_id
        2. Apply filter settings (max_loi, min_cpi, min_ir) from torpedo_settings
        3. Randomly select one survey from filtered results
        4. Generate entry link with subid_1=respondent_id
        
        This ensures href is encrypted for the specific respondent.
        
        Args:
            survey: Survey document from allocation pool (used for fallback metadata)
            respondent_id: Respondent's SFWID for tracking
            user_ip: Optional IP address of the respondent (passed from incoming request)
            
        Returns:
            Entry link with respondent tracking, or empty string on failure
        """
        # Get CPX settings
        settings = self.settings_collection.find_one({"_id": "app_config"}) or {}
        app_id = settings.get("cpx_app_id") or os.getenv("CPX_APP_ID", "")
        secure_hash_key = settings.get("cpx_secure_hash_key") or os.getenv("CPX_SECURE_HASH_KEY", "")

        if not app_id or not secure_hash_key:
            print("⚠️ CPX app settings missing (app_id or secure_hash_key)")
            return ""

        # Initialize CPXService with respondent as ext_user_id
        cpx_service = CPXService(
            app_id=app_id,
            ext_user_id=respondent_id,
            secure_hash_key=secure_hash_key,
            api_timeout=30,
            surveys_collection=self.cpx_surveys,
            filters_collection=None,
            settings_collection=self.settings_collection,
            survey_allocation_service=None
        )

        # Call per-respondent allocation (API call + filter + random select)
        # CRITICAL CPX IDENTITY RULES:
        # - vendor_user_id = stable vendor rid (becomes ext_user_id for CPX)
        # - internal_tracking_id = our sfwid for subid_1 tracking
        # - IP and UA are REQUIRED, no fallbacks
        result = cpx_service.fetch_and_allocate_for_respondent(
            vendor_user_id=respondent_id,        # This should be the vendor's rid
            internal_tracking_id=respondent_id,  # Our tracking ID (may differ in real flow)
            user_ip=user_ip or "",               # Will fail if empty - that's correct
            user_agent=""                        # Will fail - caller must provide UA
        )

        if result.get("success"):
            print(f"🔗 Built CPX entry link for respondent {respondent_id}, survey {result.get('survey_id')}")
            return result.get("entry_link", "")
        else:
            print(f"⚠️ CPX allocation failed for respondent {respondent_id}: {result.get('error')}")
            return ""
    
    def _log_allocation(
        self,
        respondent_id: str,
        survey_id: str,
        allocation_id: str,
        request: AllocationRequest
    ):
        """Log allocation for audit trail"""
        try:
            self.allocation_log.insert_one({
                "respondent_id": respondent_id,
                "survey_id": survey_id,
                "allocation_id": allocation_id,
                "vid": request.vid,
                "cc": request.cc,
                "rid": request.rid,
                "timestamp": datetime.utcnow(),
                "ip_address": request.ip_address,
                "user_agent": request.user_agent
            })
        except Exception as e:
            print(f"⚠️ Failed to log allocation: {e}")
    
    # ============================================
    # Callback Event Handlers
    # ============================================
    
    def handle_callback(self, event: CallbackEvent) -> CallbackResponse:
        """
        Handle survey callback events.
        Routes to appropriate handler based on event type.
        """
        handlers = {
            "start": self._handle_start,
            "complete": self._handle_complete,
            "incomplete": self._handle_incomplete,
            "terminate": self._handle_terminate,
            "quota_full": self._handle_quota_full
        }
        
        handler = handlers.get(event.event_type)
        if not handler:
            return CallbackResponse(
                success=False,
                message=f"Unknown event type: {event.event_type}"
            )
        
    
    def _handle_start(self, event: CallbackEvent) -> CallbackResponse:
        """Handle survey start event (respondent began survey)"""
        # Update respondent status
        respondent = self.update_respondent_status(
            event.respondent_id,
            RespondentStatus.STARTED
        )
        
        if not respondent:
            return CallbackResponse(
                success=False,
                message="Respondent not found"
            )
        
        # Increment entrants count (NOT sent_n - allocations are counted separately)
        self._increment_metric(event.survey_id, "entrants_n")
        
        # Evaluate auto-pause rules
        self._evaluate_auto_pause(event.survey_id)
        
        return CallbackResponse(
            success=True,
            message="Start event recorded"
        )
    
    def _handle_complete(self, event: CallbackEvent) -> CallbackResponse:
        """Handle survey completion event"""
        respondent = self.update_respondent_status(
            event.respondent_id,
            RespondentStatus.COMPLETED
        )
        
        if not respondent:
            return CallbackResponse(
                success=False,
                message="Respondent not found"
            )
        
        # Update metrics
        self._increment_metric(event.survey_id, "completes_n")
        
        # Decrement remaining quota
        self.surveys.update_one(
            {"_id": ObjectId(event.survey_id)},
            {"$inc": {"remaining_quota": -1}}
        )
        
        # Get redirect URL
        survey = self.get_survey(event.survey_id)
        redirect_url = survey.get("complete_redirect_url") if survey else None
        
        # Evaluate auto-pause rules
        self._evaluate_auto_pause(event.survey_id)
        
        return CallbackResponse(
            success=True,
            message="Complete event recorded",
            redirect_url=redirect_url
        )
    
    def _handle_incomplete(self, event: CallbackEvent) -> CallbackResponse:
        """Handle incomplete/dropout event"""
        respondent = self.update_respondent_status(
            event.respondent_id,
            RespondentStatus.TERMINATED,
            {"termination_reason": "incomplete"}
        )
        
        if not respondent:
            return CallbackResponse(
                success=False,
                message="Respondent not found"
            )
        
        # Update metrics
        self._increment_metric(event.survey_id, "incompletes_n")
        
        # Get redirect URL
        survey = self.get_survey(event.survey_id)
        redirect_url = survey.get("terminate_redirect_url") if survey else None
        
        # Evaluate auto-pause rules
        self._evaluate_auto_pause(event.survey_id)
        
        return CallbackResponse(
            success=True,
            message="Incomplete event recorded",
            redirect_url=redirect_url
        )
    
    def _handle_terminate(self, event: CallbackEvent) -> CallbackResponse:
        """Handle termination/screen-out event"""
        respondent = self.update_respondent_status(
            event.respondent_id,
            RespondentStatus.TERMINATED,
            {"termination_reason": "screened_out"}
        )
        
        if not respondent:
            return CallbackResponse(
                success=False,
                message="Respondent not found"
            )
        
        # Update metrics
        self._increment_metric(event.survey_id, "terminates_n")
        
        # Get redirect URL
        survey = self.get_survey(event.survey_id)
        redirect_url = survey.get("terminate_redirect_url") if survey else None
        
        return CallbackResponse(
            success=True,
            message="Terminate event recorded",
            redirect_url=redirect_url
        )
    
    def _handle_quota_full(self, event: CallbackEvent) -> CallbackResponse:
        """Handle quota full event"""
        respondent = self.update_respondent_status(
            event.respondent_id,
            RespondentStatus.QUOTA_FULL
        )
        
        if not respondent:
            return CallbackResponse(
                success=False,
                message="Respondent not found"
            )
        
        # Update metrics
        self._increment_metric(event.survey_id, "quota_full_n")
        
        # Get redirect URL
        survey = self.get_survey(event.survey_id)
        redirect_url = survey.get("quota_full_redirect_url") if survey else None
        
        return CallbackResponse(
            success=True,
            message="Quota full event recorded",
            redirect_url=redirect_url
        )
    
    # ============================================
    # Metrics Management
    # ============================================
    
    def _ensure_metrics(self, survey_id: str):
        """Ensure metrics document exists for survey"""
        try:
            self.metrics.update_one(
                {"survey_id": survey_id},
                {
                    "$setOnInsert": {
                        "survey_id": survey_id,
                        "sent_n": 0,
                        "entrants_n": 0,
                        "completes_n": 0,
                        "incompletes_n": 0,
                        "terminates_n": 0,
                        "quota_full_n": 0,
                        "incidence_rate": 0.0,
                        "incomplete_rate": 0.0,
                        "conversion_rate": 0.0,
                        "last_updated": datetime.utcnow()
                    }
                },
                upsert=True
            )
        except Exception as e:
            print(f"⚠️ Failed to ensure metrics: {e}")
    
    def _increment_metric(self, survey_id: str, field: str, amount: int = 1):
        """Increment a metric field and recalculate rates"""
        try:
            # Increment the field
            result = self.metrics.find_one_and_update(
                {"survey_id": survey_id},
                {
                    "$inc": {field: amount},
                    "$set": {"last_updated": datetime.utcnow()}
                },
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            
            if result:
                # Recalculate rates
                entrants = result.get("entrants_n", 0)
                completes = result.get("completes_n", 0)
                incompletes = result.get("incompletes_n", 0)
                sent = result.get("sent_n", 0)
                
                updates = {}
                
                if entrants > 0:
                    updates["incidence_rate"] = round((completes / entrants) * 100, 2)
                    updates["incomplete_rate"] = round((incompletes / entrants) * 100, 2)
                
                if sent > 0:
                    updates["conversion_rate"] = round((completes / sent) * 100, 2)
                
                if field == "sent_n":
                    updates["last_allocation"] = datetime.utcnow()
                elif field == "completes_n":
                    updates["last_complete"] = datetime.utcnow()
                
                if updates:
                    self.metrics.update_one(
                        {"survey_id": survey_id},
                        {"$set": updates}
                    )
        except Exception as e:
            print(f"⚠️ Failed to increment metric: {e}")
    
    def get_survey_metrics(self, survey_id: str) -> Optional[dict]:
        """Get metrics for a specific survey"""
        return self.metrics.find_one({"survey_id": survey_id})
    
    def _increment_survey_click_count(self, survey: dict):
        """
        Increment click_count and update last_clicked_at on CPX/CINT survey document.
        
        This is called when a respondent is allocated to a survey, ensuring the
        source survey pool (cpx_surveys or cint_surveys) tracks click activity
        for the click-based cleanup logic.
        
        Args:
            survey: Survey dict containing provider and external_id fields
        """
        try:
            provider = survey.get("provider", "").upper()
            external_id = survey.get("external_id") or survey.get("survey_id")
            
            if not external_id:
                print(f"⚠️ Cannot increment click count: no external_id found")
                return
            
            now = datetime.utcnow()
            
            if provider == "CPX":
                # Update CPX survey - uses _id as survey_id
                self.cpx_surveys.update_one(
                    {"_id": str(external_id)},
                    {
                        "$inc": {"click_count": 1},
                        "$set": {"last_clicked_at": now}
                    }
                )
                print(f"✅ Incremented click_count for CPX survey {external_id}")
                
            elif provider == "CINT":
                # Update CINT survey - uses survey_id field
                # Handle both string and int survey_id
                try:
                    survey_id_int = int(external_id)
                    self.cint_surveys.update_one(
                        {"survey_id": survey_id_int},
                        {
                            "$inc": {"click_count": 1},
                            "$set": {"last_clicked_at": now}
                        }
                    )
                except ValueError:
                    self.cint_surveys.update_one(
                        {"survey_id": external_id},
                        {
                            "$inc": {"click_count": 1},
                            "$set": {"last_clicked_at": now}
                        }
                    )
                print(f"✅ Incremented click_count for CINT survey {external_id}")
            else:
                print(f"⚠️ Unknown provider '{provider}' - cannot increment click count")
                
        except Exception as e:
            print(f"⚠️ Failed to increment survey click count: {e}")
    
    def get_all_metrics(self) -> List[dict]:
        """Get metrics for all surveys"""
        return list(self.metrics.find().sort("last_updated", DESCENDING))
    
    # ============================================
    # Auto-Pause Evaluation Logic
    # ============================================
    
    def _evaluate_auto_pause(self, survey_id: str):
        """
        Evaluate whether a survey should be auto-paused.
        
        Rules (only evaluated after minimum entrants threshold):
        1. Incomplete Rate > max_incomplete_rate → PAUSE
        2. Incidence Rate < min_incidence_rate → PAUSE
        """
        settings = self.get_allocation_settings()
        
        if not settings.auto_pause_enabled:
            return
        
        metrics = self.get_survey_metrics(survey_id)
        if not metrics:
            return
        
        entrants = metrics.get("entrants_n", 0)
        
        # Don't evaluate until minimum threshold is reached
        if entrants < settings.minimum_entrants_for_evaluation:
            return
        
        incomplete_rate = metrics.get("incomplete_rate", 0.0)
        incidence_rate = metrics.get("incidence_rate", 0.0)
        
        pause_reason = None
        
        # Check incomplete rate
        if incomplete_rate > settings.max_incomplete_rate:
            pause_reason = f"High incomplete rate: {incomplete_rate:.1f}% (threshold: {settings.max_incomplete_rate}%)"
        
        # Check incidence rate
        elif incidence_rate < settings.min_incidence_rate:
            pause_reason = f"Low incidence rate: {incidence_rate:.1f}% (threshold: {settings.min_incidence_rate}%)"
        
        if pause_reason:
            print(f"⚠️ Auto-pausing survey {survey_id}: {pause_reason}")
            self.update_survey_status(
                survey_id,
                SurveyStatus.PAUSED,
                pause_reason
            )
    
    def manually_resume_survey(self, survey_id: str) -> bool:
        """Manually resume a paused survey"""
        try:
            result = self.surveys.find_one_and_update(
                {
                    "_id": ObjectId(survey_id),
                    "status": SurveyStatus.PAUSED.value
                },
                {
                    "$set": {
                        "status": SurveyStatus.ACTIVE.value,
                        "paused_at": None,
                        "paused_reason": None,
                        "updated_at": datetime.utcnow()
                    }
                },
                return_document=ReturnDocument.AFTER
            )
            return result is not None
        except Exception as e:
            print(f"❌ Error resuming survey: {e}")
            return False
    
    def reset_batch(self, survey_id: str) -> bool:
        """Reset the batch counter for a survey (start new batch)"""
        try:
            result = self.surveys.find_one_and_update(
                {"_id": ObjectId(survey_id)},
                {
                    "$set": {
                        "current_batch_sent": 0,
                        "updated_at": datetime.utcnow()
                    }
                },
                return_document=ReturnDocument.AFTER
            )
            return result is not None
        except Exception as e:
            print(f"❌ Error resetting batch: {e}")
            return False
    
    # ============================================
    # Dashboard / Reporting
    # ============================================
    
    def get_dashboard_stats(self) -> dict:
        """Get summary statistics for dashboard"""
        try:
            active_surveys = self.surveys.count_documents({"status": SurveyStatus.ACTIVE.value})
            paused_surveys = self.surveys.count_documents({"status": SurveyStatus.PAUSED.value})
            
            total_respondents = self.respondents.count_documents({})
            allocated = self.respondents.count_documents({"status": RespondentStatus.ALLOCATED.value})
            started = self.respondents.count_documents({"status": RespondentStatus.STARTED.value})
            completed = self.respondents.count_documents({"status": RespondentStatus.COMPLETED.value})
            
            # Today's stats
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_allocations = self.allocation_log.count_documents({
                "timestamp": {"$gte": today_start}
            })
            today_completes = self.respondents.count_documents({
                "completed_at": {"$gte": today_start}
            })
            
            return {
                "surveys": {
                    "active": active_surveys,
                    "paused": paused_surveys,
                    "total": active_surveys + paused_surveys
                },
                "respondents": {
                    "total": total_respondents,
                    "allocated": allocated,
                    "started": started,
                    "completed": completed
                },
                "today": {
                    "allocations": today_allocations,
                    "completes": today_completes
                }
            }
        except Exception as e:
            print(f"❌ Error getting dashboard stats: {e}")
            return {}
    
    def get_surveys_with_metrics(self, status: str = None) -> List[dict]:
        """Get surveys with their metrics joined"""
        query = {}
        if status:
            query["status"] = status
        
        surveys = list(self.surveys.find(query).sort("updated_at", DESCENDING))
        
        for survey in surveys:
            survey["_id"] = str(survey["_id"])
            metrics = self.get_survey_metrics(survey["_id"])
            if metrics:
                metrics.pop("_id", None)
                survey["metrics"] = metrics
            else:
                survey["metrics"] = {}
        
        return surveys


# Singleton instance
_service_instance = None

def get_survey_allocation_service() -> SurveyAllocationService:
    """Get or create singleton service instance"""
    global _service_instance
    if _service_instance is None:
        _service_instance = SurveyAllocationService()
    return _service_instance
