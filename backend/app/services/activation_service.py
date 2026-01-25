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
            if not survey.get("is_live", False):  # Default to False if missing
                return False
            if survey.get("message_reason") == "deactivated":
                return False
        elif provider.upper() == "CPX":
            # CPX surveys are live if they have a live_link
            if not (survey.get("live_link") or survey.get("entry_link")):
                return False

        # Get filter thresholds with sensible defaults matching settings UI
        max_loi = filters.get("max_loi", 20)  # Default 20 minutes
        min_cpi = filters.get("min_cpi", 1.0)  # Default $1.00
        min_ir = filters.get("min_ir", filters.get("min_incidence", 5))  # Default 5%

        # Filter: LOI (length of interview in minutes)
        # CINT uses length_of_interview or bid_length_of_interview, CPX uses loi
        loi = 0
        if provider.upper() == "CINT":
            loi = survey.get("length_of_interview") or survey.get("bid_length_of_interview") or survey.get("loi") or 0
        else:
            loi = survey.get("loi") or survey.get("length_of_interview") or 0
        
        try:
            loi = float(loi) if loi else 0
        except (ValueError, TypeError):
            loi = 0
            
        if loi > 0 and loi > max_loi:
            return False
            
        # Filter: Payout / CPI
        # CINT may have payout or RPI in raw_data, CPX uses payout or cpi
        payout = 0
        if provider.upper() == "CINT":
            payout = survey.get("payout", 0)
            # Check raw_data.RPI.value (main source for CINT payout)
            if not payout and "raw_data" in survey:
                raw_data = survey.get("raw_data", {})
                if isinstance(raw_data, dict):
                    rpi = raw_data.get("RPI", {})
                    if isinstance(rpi, dict):
                        payout = rpi.get("value", 0)
                    elif isinstance(rpi, (int, float)):
                        payout = rpi
            # Fallback to revenue_per_interview
            if not payout and "revenue_per_interview" in survey:
                rpi = survey["revenue_per_interview"]
                if isinstance(rpi, dict):
                    payout = rpi.get("value", 0)
                elif isinstance(rpi, (int, float)):
                    payout = rpi
        else:
            payout = survey.get("payout") or survey.get("cpi") or 0
            
        try:
            payout = float(payout) if payout else 0
        except (ValueError, TypeError):
            payout = 0
            
        if payout < min_cpi:
            return False
            
        # Filter: Conversion/Incidence Rate
        # CINT uses bid_incidence, CPX uses conversion_rate
        ir = 0
        if provider.upper() == "CINT":
            ir = survey.get("bid_incidence") or survey.get("incidence_rate") or survey.get("conversion_rate") or 0
        else:
            ir = survey.get("conversion_rate") or survey.get("incidence_rate") or 0
            
        try:
            ir = float(ir) if ir else 0
        except (ValueError, TypeError):
            ir = 0
            
        if ir > 0 and ir < min_ir:
            return False
            
        return True

    def _upsert_to_allocator(self, provider: str, survey_doc: Dict):
        """Map source doc to SurveyCreate and upsert"""
        
        # Map fields
        external_id = str(survey_doc.get("survey_id") or survey_doc.get("_id"))
        
        # Handle payouts/LOI normalization
        loi = int(float(survey_doc.get("loi") or survey_doc.get("length_of_interview") or 0))
        payout = float(survey_doc.get("payout") or survey_doc.get("cpi") or 0)
        ir = float(survey_doc.get("conversion_rate") or survey_doc.get("incidence_rate") or 0)
        
        # Country codes must be a list
        # CPX: "country" is a string like "IN", "US"
        # Cint: "country_language" is like "eng_us"
        country_raw = survey_doc.get("country") or survey_doc.get("country_language") or "US"
        if isinstance(country_raw, list):
            country_codes = country_raw
        else:
            # Convert string to list
            country_codes = [str(country_raw).upper()]
        
        # Name
        name = survey_doc.get("title") or survey_doc.get("survey_name") or f"{provider} Survey {external_id}"
        
        # URLs
        entry_link = survey_doc.get("entry_link") or survey_doc.get("live_link") or ""

        # Quota - both remaining_quota and total_quota are required
        remaining_quota = int(survey_doc.get("remaining_quota") or survey_doc.get("total_remaining") or 1000)
        total_quota = int(survey_doc.get("total_quota") or survey_doc.get("total_n") or remaining_quota or 1000)

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
            remaining_quota=remaining_quota,
            total_quota=total_quota
        )
        
        self.allocation_service.upsert_survey(survey_create)

    def _get_default_filters(self) -> Dict[str, Any]:
        """Get filters from DB or defaults matching settings UI"""
        try:
            stored = self.settings_collection.find_one({"_id": "survey_filters"})
            if stored:
                logger.info(f"Loaded filter settings from DB: max_loi={stored.get('max_loi')}, min_cpi={stored.get('min_cpi')}, min_incidence={stored.get('min_incidence')}")
                return {
                    "max_loi": stored.get("max_loi", 20),
                    "min_cpi": stored.get("min_cpi", 1.0),
                    "min_ir": stored.get("min_incidence", 60)  # Match CINT default of 60%
                }
        except Exception as e:
            logger.warning(f"Could not load filter settings: {e}")
            
        # Default values matching the settings UI defaults
        logger.info("Using default filter settings: max_loi=20, min_cpi=1.0, min_ir=60")
        return {
            "max_loi": 20,
            "min_cpi": 1.0,
            "min_ir": 60  # 60% minimum incidence - matches CINT default
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
