import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pymongo import MongoClient

from .survey_allocation_service import SurveyAllocationService, SurveyCreate, SurveyStatus

logger = logging.getLogger(__name__)


class SurveyActivationService:
    """
    Service to manage the activation of surveys from provider pools (CPX, Cint)
    to the central allocation engine.
    
    Flow:
    1. CPX and CINT download ALL surveys to their respective collections (survey_pool)
    2. This service evaluates filters and marks matching surveys as is_active_in_pool=True
    3. Traffic allocation only routes to surveys that are active in the pool
    """

    def __init__(self, mongo_uri: str = None, survey_allocation_service: SurveyAllocationService = None):
        mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        
        if survey_allocation_service:
            self.allocation_service = survey_allocation_service
            self.client = survey_allocation_service.client
        else:
            self.client = MongoClient(mongo_uri)
            self.allocation_service = SurveyAllocationService(mongo_uri)

        self.db = self.client["survey_allocation"]
        
        # Source collections (the survey pool)
        self.cpx_surveys = self.client["cpx_research"]["cpx_surveys"]
        self.cint_surveys = self.client["cint_research"]["cint_surveys"]
        
        # Settings
        self.settings_db = self.client["torpedo_settings"]
        self.settings_collection = self.settings_db["app_settings"]
        
        logger.info("✅ Survey Activation Service initialized")

    def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the survey pool
        
        Returns:
            Dict with pool counts for CPX and CINT
        """
        try:
            cpx_total = self.cpx_surveys.count_documents({})
            cpx_active = self.cpx_surveys.count_documents({"is_active_in_pool": True})
            
            cint_total = self.cint_surveys.count_documents({})
            cint_active = self.cint_surveys.count_documents({"is_active_in_pool": True})
            
            return {
                "cpx": {
                    "total": cpx_total,
                    "active": cpx_active,
                    "inactive": cpx_total - cpx_active
                },
                "cint": {
                    "total": cint_total,
                    "active": cint_active,
                    "inactive": cint_total - cint_active
                },
                "total": {
                    "total": cpx_total + cint_total,
                    "active": cpx_active + cint_active,
                    "inactive": (cpx_total + cint_total) - (cpx_active + cint_active)
                },
                "last_sync": self._get_last_sync_time()
            }
        except Exception as e:
            logger.error(f"Error getting pool stats: {e}")
            return {"error": str(e)}
    
    def _get_last_sync_time(self) -> Optional[str]:
        """Get the last sync time from settings"""
        try:
            sync_status = self.settings_collection.find_one({"_id": "survey_sync_status"})
            if sync_status and "last_sync" in sync_status:
                return sync_status["last_sync"].isoformat()
        except Exception:
            pass
        return None
    
    def _update_sync_time(self):
        """Update the last sync time in settings"""
        try:
            self.settings_collection.update_one(
                {"_id": "survey_sync_status"},
                {"$set": {"last_sync": datetime.utcnow()}},
                upsert=True
            )
        except Exception as e:
            logger.warning(f"Could not update sync time: {e}")

    def sync_and_activate_surveys(self, filters: Dict[str, Any] = None) -> Dict[str, int]:
        """
        Sync surveys from CPX/Cint pools to allocation engine based on filters.
        
        Process:
        1. Parse filters (or defaults from settings)
        2. Iterate source collections (all downloaded surveys in the pool)
        3. If matches filter -> Set is_active_in_pool=True + Upsert to Allocation Engine
        4. If NOT matches -> Set is_active_in_pool=False + Pause in Allocation Engine
        
        This ensures:
        - All surveys are downloaded to the pool first
        - Only surveys matching filters are marked as active
        - Traffic routing only uses active surveys
        
        Returns:
            Stats dict with activation counts
        """
        if filters is None:
            filters = self._get_default_filters()
        
        logger.info(f"🔄 Starting survey sync with filters: {filters}")
            
        stats = {
            "cpx_activated": 0,
            "cpx_deactivated": 0,
            "cpx_total": 0,
            "cint_activated": 0,
            "cint_deactivated": 0,
            "cint_total": 0
        }

        # 1. Sync CPX
        self._sync_provider("CPX", self.cpx_surveys, filters, stats)
        
        # 2. Sync CINT
        self._sync_provider("CINT", self.cint_surveys, filters, stats)
        
        # Update last sync time
        self._update_sync_time()
        
        logger.info(f"✅ Survey sync complete: {stats}")
        return stats
        
        return stats

    def _sync_provider(self, provider_name: str, collection, filters: Dict[str, Any], stats: Dict[str, int]):
        """
        Sync a specific provider's collection.
        
        Evaluates each survey against filters and updates is_active_in_pool accordingly.
        Active surveys are also upserted to the allocation engine.
        """
        logger.info(f"Syncing {provider_name} surveys with filters: {filters}")
        
        # Get all surveys from the pool
        cursor = collection.find({})
        provider_key = provider_name.lower()
        
        for survey_doc in cursor:
            stats[f"{provider_key}_total"] = stats.get(f"{provider_key}_total", 0) + 1
            is_eligible = self._evaluate_survey(survey_doc, filters, provider_name)
            survey_id = str(survey_doc.get("survey_id") or survey_doc.get("_id"))
            was_active = survey_doc.get("is_active_in_pool", False)
            
            if is_eligible:
                # Mark as active in pool
                collection.update_one(
                    {"_id": survey_doc["_id"]},
                    {"$set": {
                        "is_active_in_pool": True,
                        "activated_at": datetime.utcnow() if not was_active else survey_doc.get("activated_at")
                    }}
                )
                
                # Upsert to Allocation Engine for routing
                self._upsert_to_allocator(provider_name, survey_doc)
                
                stats[f"{provider_key}_activated"] += 1
            else:
                # Mark as inactive in pool
                collection.update_one(
                    {"_id": survey_doc["_id"]},
                    {"$set": {"is_active_in_pool": False}}
                )
                
                # If was previously active, pause in allocation engine
                if was_active:
                    existing = self.allocation_service.surveys.find_one({
                        "external_id": survey_id,
                        "provider": provider_name
                    })
                    if existing:
                        self.allocation_service.update_survey_status(
                            str(existing["_id"]),
                            SurveyStatus.PAUSED,
                            reason="Filtered out by sync - does not meet criteria"
                        )

                stats[f"{provider_key}_deactivated"] += 1
        
        logger.info(f"Synced {provider_name}: {stats.get(f'{provider_key}_activated', 0)} active, "
                    f"{stats.get(f'{provider_key}_deactivated', 0)} inactive")

    def _evaluate_survey(self, survey: Dict, filters: Dict, provider: str = "") -> bool:
        """
        Evaluate if a survey meets the activation criteria.
        
        A survey is eligible if:
        - It is live/active (not deactivated)
        - LOI <= max_loi filter
        - Payout >= min_cpi filter
        - Incidence/IR >= min_ir filter (optional)
        """
        # Check if survey is live (CINT has is_live, CPX surveys are live if they have a live_link)
        if provider.upper() == "CINT":
            if not survey.get("is_live", True):
                return False
            if survey.get("message_reason") == "deactivated":
                return False
        elif provider.upper() == "CPX":
            # CPX surveys are live if they have a live_link
            if not (survey.get("live_link") or survey.get("entry_link")):
                return False

        # Filter: LOI (length of interview in minutes)
        loi = float(survey.get("loi") or survey.get("length_of_interview") or 0)
        if loi > filters.get("max_loi", 999):
            return False
            
        # Filter: Payout / CPI
        payout = float(survey.get("payout") or survey.get("cpi") or 0)
        if payout < filters.get("min_cpi", 0):
            return False
            
        # Filter: Conversion (Incidence)
        ir = float(survey.get("conversion_rate") or survey.get("incidence_rate") or 0)
        if ir < filters.get("min_ir", 0):
            return False
            
        return True

    def _upsert_to_allocator(self, provider: str, survey_doc: Dict):
        """Map source doc to SurveyCreate and upsert"""
        
        # Map fields
        external_id = str(survey_doc.get("survey_id") or survey_doc.get("_id"))
        
        # Handle payouts/LOI normalization
        loi = float(survey_doc.get("loi") or survey_doc.get("length_of_interview") or 0)
        payout = float(survey_doc.get("payout") or survey_doc.get("cpi") or 0)
        ir = float(survey_doc.get("conversion_rate") or survey_doc.get("incidence_rate") or 0)
        
        # Default Country to specific list or "GLOBAL"
        country_codes = survey_doc.get("country") or survey_doc.get("country_language") or "US" # Normalize logic needed
        # CPX: "country" like "IN", "US"
        # Cint: "country_language" like "eng_us" -> needs mapping? or just store as is and handle in frontend?
        # Allocation engine expects standard codes?
        
        # Name
        name = survey_doc.get("title") or survey_doc.get("survey_name") or f"{provider} Survey {external_id}"
        
        # URLs
        entry_link = survey_doc.get("entry_link") or survey_doc.get("live_link") or ""

        # Create model
        survey_create = SurveyCreate(
            external_id=external_id,
            provider=provider,
            name=name,
            country_codes=country_codes,
            loi=loi,
            cpi=payout,
            ir=ir,
            entry_url=entry_link,
            remaining_quota=int(survey_doc.get("remaining_quota") or survey_doc.get("total_remaining") or 1000) # Default quota
        )
        
        self.allocation_service.upsert_survey(survey_create)

    def _get_default_filters(self) -> Dict[str, Any]:
        """Get filters from DB or defaults"""
        try:
            stored = self.settings_collection.find_one({"_id": "survey_filters"})
            if stored:
                return {
                    "max_loi": stored.get("max_loi", 30),
                    "min_cpi": stored.get("min_cpi", 0.5),
                    "min_ir": stored.get("min_incidence", 5)
                }
        except Exception:
            pass
            
        return {
            "max_loi": 30,
            "min_cpi": 0.5,
            "min_ir": 5
        }
    
    def get_active_surveys_from_pool(self, provider: str = None, limit: int = 100) -> List[Dict]:
        """
        Get surveys that are marked as active in the pool.
        
        Args:
            provider: Optional filter by provider ("CPX" or "CINT")
            limit: Maximum number of surveys to return
            
        Returns:
            List of active survey documents
        """
        active_surveys = []
        
        if provider is None or provider.upper() == "CPX":
            cpx_active = list(self.cpx_surveys.find(
                {"is_active_in_pool": True}
            ).limit(limit))
            for s in cpx_active:
                s["_id"] = str(s["_id"])
                s["provider"] = "CPX"
            active_surveys.extend(cpx_active)
        
        if provider is None or provider.upper() == "CINT":
            cint_active = list(self.cint_surveys.find(
                {"is_active_in_pool": True}
            ).limit(limit))
            for s in cint_active:
                s["_id"] = str(s["_id"])
                s["provider"] = "CINT"
            active_surveys.extend(cint_active)
        
        return active_surveys
    
    def toggle_survey_activation(self, survey_id: str, provider: str, activate: bool) -> Dict[str, Any]:
        """
        Manually activate or deactivate a specific survey in the pool.
        
        Args:
            survey_id: The survey ID
            provider: "CPX" or "CINT"
            activate: True to activate, False to deactivate
            
        Returns:
            Dict with success status and message
        """
        try:
            collection = self.cpx_surveys if provider.upper() == "CPX" else self.cint_surveys
            
            # Find the survey
            survey = collection.find_one({
                "$or": [
                    {"_id": survey_id},
                    {"survey_id": survey_id},
                    {"survey_id": int(survey_id) if survey_id.isdigit() else survey_id}
                ]
            })
            
            if not survey:
                return {"success": False, "message": f"Survey {survey_id} not found in {provider}"}
            
            # Update activation status
            collection.update_one(
                {"_id": survey["_id"]},
                {"$set": {
                    "is_active_in_pool": activate,
                    "manually_toggled": True,
                    "toggled_at": datetime.utcnow()
                }}
            )
            
            # Also update allocation engine
            if activate:
                self._upsert_to_allocator(provider, survey)
            else:
                existing = self.allocation_service.surveys.find_one({
                    "external_id": str(survey.get("survey_id") or survey.get("_id")),
                    "provider": provider
                })
                if existing:
                    self.allocation_service.update_survey_status(
                        str(existing["_id"]),
                        SurveyStatus.PAUSED,
                        reason="Manually deactivated"
                    )
            
            action = "activated" if activate else "deactivated"
            return {"success": True, "message": f"Survey {survey_id} {action} successfully"}
            
        except Exception as e:
            logger.error(f"Error toggling survey activation: {e}")
            return {"success": False, "message": str(e)}


# Singleton instance
_activation_service_instance = None


def get_activation_service() -> SurveyActivationService:
    """Get or create singleton activation service instance"""
    global _activation_service_instance
    if _activation_service_instance is None:
        _activation_service_instance = SurveyActivationService()
    return _activation_service_instance
