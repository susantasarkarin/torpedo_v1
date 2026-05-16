import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict

try:
    from ...database import get_client
except ImportError:
    from database import get_client

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
            self.client = get_client()
            self.allocation_service = SurveyAllocationService(mongo_uri)

        self.db = self.client["survey_allocation"]
        
        # Source collections (the survey pool)
        self.cpx_surveys = self.client["cpx_research"]["cpx_surveys"]
        self.cint_surveys = self.client["cint_research"]["cint_surveys"]
        self.cint_outcomes = self.client["cint_research"]["cint_respondent_outcomes"]
        
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

        # 1. Sync CPX (disabled - keep all CPX surveys inactive in pool)
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
        - Payout > min_cpi filter
        """
        # Check if survey is live (CINT has is_live, CPX surveys are live if they have a live_link)
        if provider.upper() == "CINT":
            if not survey.get("is_live", False):  # Default to False if missing
                return False
            if survey.get("message_reason") == "deactivated":
                return False
        elif provider.upper() == "CPX":
            # CPX is removed from the study pool
            return False

        # Get filter thresholds with sensible defaults matching settings UI
        min_cpi = filters.get("min_cpi", 1.0)  # Default $1.00

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
            
        if payout <= min_cpi:
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
                logger.info(f"Loaded filter settings from DB: min_cpi={stored.get('min_cpi')}")
                return {
                    "min_cpi": stored.get("min_cpi", 1.0),
                }
        except Exception as e:
            logger.warning(f"Could not load filter settings: {e}")
            
        # Default values matching the settings UI defaults
        logger.info("Using default filter settings: min_cpi=1.0")
        return {
            "min_cpi": 1.0,
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
        
        if provider is None or provider.upper() == "CINT":
            cint_active = list(self.cint_surveys.find(
                {"is_active_in_pool": True}
            ).limit(limit))
            for s in cint_active:
                s["_id"] = str(s["_id"])
                s["provider"] = "CINT"
            active_surveys.extend(cint_active)
        
        return active_surveys

    def get_top_surveys_by_country(
        self,
        limit: int = 5,
        country_code: Optional[str] = None,
        ir_weight: float = 0.5,
        cpi_weight: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Rank active Cint pool surveys country-wise using IR and CPI.

        The active pool already applies the hard eligibility filter. This method
        adds a relative ranking inside each country group so operations can see
        the best current inventory to prioritize.
        """
        if limit < 1:
            raise ValueError("limit must be greater than 0")

        normalized_country = country_code.upper() if country_code else None
        surveys = list(
            self.cint_surveys.find(
                {
                    "is_active_in_pool": True,
                    "is_live": True,
                    "message_reason": {"$ne": "deactivated"},
                }
            )
        )

        # Batch-load internal performance from outcomes (avoids N+1 queries)
        # Per Cint guide: use internal IR after 20 sessions; exclude quality_terminates (status 40)
        survey_ids = [s.get("survey_id") for s in surveys if s.get("survey_id")]
        internal_ir_map: Dict[int, float] = {}
        if survey_ids:
            try:
                pipeline = [
                    {"$match": {
                        "survey_id": {"$in": survey_ids},
                        "marketplace_status": {"$ne": 40},  # Exclude quality-terminates
                    }},
                    {"$group": {
                        "_id": "$survey_id",
                        "total_sessions": {"$sum": 1},
                        "completes": {"$sum": {
                            "$cond": [{"$eq": ["$marketplace_status", 10]}, 1, 0]
                        }},
                    }},
                ]
                for row in self.cint_outcomes.aggregate(pipeline):
                    if row["total_sessions"] >= 20:  # Per Cint: use internal data after 20 sessions
                        internal_ir_map[row["_id"]] = round(
                            row["completes"] / row["total_sessions"] * 100, 4
                        )
            except Exception as _outcomes_err:
                logger.warning(f"Could not load internal outcomes for ranking: {_outcomes_err}")

        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for survey in surveys:
            derived_country = self._extract_country_code(survey)
            if not derived_country:
                continue
            if normalized_country and derived_country != normalized_country:
                continue

            payout = self._get_cint_payout(survey)
            survey_id_int = survey.get("survey_id")
            internal_ir = internal_ir_map.get(survey_id_int) if survey_id_int else None
            effective_ir = internal_ir if internal_ir is not None else self._get_effective_ir(survey)
            effective_loi = self._get_effective_loi(survey)
            rpc = self._to_float(survey.get("revenue_per_click"))

            grouped[derived_country].append(
                {
                    **survey,
                    "country_code": derived_country,
                    "effective_ir": round(effective_ir, 4),
                    "effective_loi": effective_loi,
                    "payout": payout,
                    "revenue_per_click": rpc,
                }
            )

        countries: List[Dict[str, Any]] = []

        for code, country_surveys in sorted(grouped.items()):
            payout_values = [item["payout"] for item in country_surveys]
            ir_values = [item["effective_ir"] for item in country_surveys]

            min_payout = min(payout_values) if payout_values else 0.0
            max_payout = max(payout_values) if payout_values else 0.0
            min_ir = min(ir_values) if ir_values else 0.0
            max_ir = max(ir_values) if ir_values else 0.0

            ranked_surveys = []
            for survey in country_surveys:
                payout_score = self._normalize_metric(survey["payout"], min_payout, max_payout)
                ir_score = self._normalize_metric(survey["effective_ir"], min_ir, max_ir)
                composite_score = (ir_score * ir_weight) + (payout_score * cpi_weight)

                ranked_surveys.append(
                    {
                        "survey_id": survey.get("survey_id"),
                        "survey_name": survey.get("survey_name"),
                        "account_name": survey.get("account_name"),
                        "country_language": survey.get("country_language"),
                        "country_code": code,
                        "study_type": survey.get("study_type"),
                        "conversion": self._to_float(survey.get("conversion")),
                        "bid_incidence": self._to_float(survey.get("bid_incidence")),
                        "effective_ir": survey["effective_ir"],
                        "payout": survey["payout"],
                        "revenue_per_click": survey.get("revenue_per_click", 0.0),
                        "length_of_interview": self._to_int(survey.get("length_of_interview")),
                        "bid_length_of_interview": self._to_int(survey.get("bid_length_of_interview")),
                        "effective_loi": survey["effective_loi"],
                        "total_remaining": self._to_int(survey.get("total_remaining")),
                        "overall_completes": self._to_int(survey.get("overall_completes")),
                        "internal_ir": internal_ir_map.get(survey.get("survey_id")),
                        "score": round(composite_score, 6),
                        "score_components": {
                            "ir_weight": ir_weight,
                            "cpi_weight": cpi_weight,
                            "normalized_ir": round(ir_score, 6),
                            "normalized_cpi": round(payout_score, 6),
                        },
                    }
                )

            ranked_surveys.sort(
                key=lambda item: (
                    item["score"],
                    item["effective_ir"],
                    item["payout"],
                    item["revenue_per_click"],
                    -item["effective_loi"],
                ),
                reverse=True,
            )

            countries.append(
                {
                    "country_code": code,
                    "count": min(limit, len(ranked_surveys)),
                    "total_active_surveys": len(ranked_surveys),
                    "top_surveys": ranked_surveys[:limit],
                }
            )

        return {
            "countries": countries,
            "country_count": len(countries),
            "limit": limit,
            "weights": {
                "ir": ir_weight,
                "cpi": cpi_weight,
            },
        }

    def _extract_country_code(self, survey: Dict[str, Any]) -> Optional[str]:
        country_language = survey.get("country_language")
        if isinstance(country_language, str) and "_" in country_language:
            return country_language.rsplit("_", 1)[-1].upper()

        country = survey.get("country")
        if isinstance(country, str) and country.strip():
            return country.strip().upper()

        return None

    def _get_cint_payout(self, survey: Dict[str, Any]) -> float:
        payout = self._to_float(survey.get("payout"))
        if payout > 0:
            return payout

        revenue_per_interview = survey.get("revenue_per_interview")
        if isinstance(revenue_per_interview, dict):
            payout = self._to_float(revenue_per_interview.get("value"))
            if payout > 0:
                return payout

        raw_data = survey.get("raw_data")
        if isinstance(raw_data, dict):
            rpi = raw_data.get("RPI")
            if isinstance(rpi, dict):
                return self._to_float(rpi.get("value"))
            return self._to_float(rpi)

        return 0.0

    def _get_effective_ir(self, survey: Dict[str, Any]) -> float:
        conversion = self._to_float(survey.get("conversion"))
        if conversion > 0:
            return conversion * 100 if conversion <= 1 else conversion

        bid_incidence = self._to_float(survey.get("bid_incidence"))
        if bid_incidence > 0:
            return bid_incidence

        # AI-predicted score as last resort for cold-start surveys
        predicted = self._to_float(survey.get("predicted_score"))
        if predicted > 0:
            return predicted

        return 0.0

    def _get_effective_loi(self, survey: Dict[str, Any]) -> int:
        actual_loi = self._to_int(survey.get("length_of_interview"))
        if actual_loi > 0:
            return actual_loi
        return self._to_int(survey.get("bid_length_of_interview"))

    @staticmethod
    def _normalize_metric(value: float, minimum: float, maximum: float) -> float:
        if maximum <= minimum:
            return 1.0 if value > 0 else 0.0
        return (value - minimum) / (maximum - minimum)

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            if value is None or value == "":
                return 0
            return int(float(value))
        except (TypeError, ValueError):
            return 0
    
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


    # ------------------------------------------------------------------
    # Survey Ranking: Top-N surveys by composite IR + CPI score
    # ------------------------------------------------------------------

    def get_top_surveys_by_country(
        self,
        limit: int = 5,
        country_code: Optional[str] = None,
        ir_weight: float = 0.5,
        cpi_weight: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Return top-N active Cint surveys ranked by composite IR+CPI score,
        grouped by country.  Uses internal IR when ≥20 sessions exist,
        otherwise falls back to bid_incidence or AI predicted_score.
        """
        try:
            # 1. Fetch active surveys (optionally filtered by country)
            query: Dict[str, Any] = {"is_active_in_pool": True, "is_live": True}
            if country_code:
                query["country_language"] = {"$regex": f"_{country_code.lower()}$", "$options": "i"}

            surveys = list(self.cint_surveys.find(
                query,
                {
                    "survey_id": 1, "country_language": 1,
                    "conversion": 1, "bid_incidence": 1, "predicted_score": 1,
                    "revenue_per_interview": 1, "revenue_per_click": 1,
                    "bid_length_of_interview": 1, "length_of_interview": 1,
                    "study_type": 1, "account_name": 1, "payout": 1,
                    "message_reason": 1,
                }
            ))

            if not surveys:
                return {
                    "countries": {},
                    "country_count": 0,
                    "total_surveys_evaluated": 0,
                    "weights": {"ir": ir_weight, "cpi": cpi_weight},
                }

            # 2. Batch fetch internal IR from outcomes (for surveys with ≥20 sessions)
            survey_ids = [s["survey_id"] for s in surveys if "survey_id" in s]
            internal_ir_map = self._batch_get_internal_ir(survey_ids, min_sessions=20)

            # 3. Group surveys by country
            by_country: Dict[str, list] = defaultdict(list)
            for s in surveys:
                cc = self._extract_country_code(s)
                by_country[cc].append(s)

            # 4. Score and rank within each country
            result: Dict[str, Any] = {}
            for cc, country_surveys in by_country.items():
                ranked = self._rank_surveys(
                    country_surveys, internal_ir_map, ir_weight, cpi_weight, limit
                )
                result[cc] = ranked

            return {
                "countries": result,
                "country_count": len(result),
                "total_surveys_evaluated": len(surveys),
                "weights": {"ir": ir_weight, "cpi": cpi_weight},
            }

        except Exception as e:
            logger.error(f"Error in get_top_surveys_by_country: {e}", exc_info=True)
            raise

    def _batch_get_internal_ir(self, survey_ids: list, min_sessions: int = 20) -> Dict[int, float]:
        """
        Aggregate outcomes collection to compute internal IR per survey.
        Only returns surveys with at least min_sessions (excluding quality_terminates).
        marketplace_status: 10=complete, 20=terminate, 30=over_quota, 40=quality_terminate (excluded), 50=closed
        """
        if not survey_ids:
            return {}
        try:
            pipeline = [
                {"$match": {
                    "survey_id": {"$in": survey_ids},
                    "marketplace_status": {"$ne": 40},
                }},
                {"$group": {
                    "_id": "$survey_id",
                    "completes": {"$sum": {"$cond": [{"$eq": ["$marketplace_status", 10]}, 1, 0]}},
                    "total": {"$sum": 1},
                }},
                {"$match": {"total": {"$gte": min_sessions}}},
            ]
            rows = list(self.cint_outcomes.aggregate(pipeline))
            return {
                r["_id"]: (r["completes"] / r["total"] * 100.0)
                for r in rows if r["total"] > 0
            }
        except Exception as e:
            logger.warning(f"Could not fetch internal IR: {e}")
            return {}

    def _get_effective_ir(self, survey: dict, internal_ir_map: Dict[int, float]) -> Optional[float]:
        """Three-tier IR fallback: internal outcomes → bid_incidence → predicted_score."""
        sid = survey.get("survey_id")
        if sid and sid in internal_ir_map:
            return internal_ir_map[sid]
        conv = survey.get("conversion")
        if conv and conv > 0:
            return conv * 100.0
        bi = survey.get("bid_incidence")
        if bi and bi > 0:
            return float(bi)
        ps = survey.get("predicted_score")
        if ps and ps > 0:
            return float(ps)
        return None

    def _get_cint_payout(self, survey: dict) -> Optional[float]:
        """Extract CPI (revenue_per_interview) handling string-valued field."""
        rpi = survey.get("revenue_per_interview")
        if rpi and isinstance(rpi, dict):
            try:
                return float(rpi.get("value", 0) or 0)
            except (TypeError, ValueError):
                pass
        payout = survey.get("payout")
        if payout:
            try:
                return float(payout)
            except (TypeError, ValueError):
                pass
        return None

    def _extract_country_code(self, survey: dict) -> str:
        """Extract ISO country code from country_language string e.g. 'eng_us' → 'us'."""
        cl = str(survey.get("country_language") or "")
        parts = cl.split("_")
        return parts[-1].upper() if len(parts) >= 2 else cl.upper() or "UNKNOWN"

    def _normalize_metric(self, value: float, min_val: float, max_val: float) -> float:
        """Min-max normalize to [0, 1]. Returns 0.5 if all values are the same."""
        if max_val == min_val:
            return 0.5
        return (value - min_val) / (max_val - min_val)

    def _rank_surveys(
        self,
        surveys: list,
        internal_ir_map: Dict[int, float],
        ir_weight: float,
        cpi_weight: float,
        limit: int,
    ) -> list:
        """Normalize IR and CPI within group, compute composite score, return top-N."""
        scored = []
        for s in surveys:
            ir = self._get_effective_ir(s, internal_ir_map)
            cpi = self._get_cint_payout(s)
            if ir is None and cpi is None:
                continue
            scored.append({
                "survey_id": s.get("survey_id"),
                "country_language": s.get("country_language"),
                "ir_raw": ir,
                "cpi_raw": cpi,
                "loi": s.get("bid_length_of_interview") or s.get("length_of_interview"),
                "study_type": s.get("study_type"),
                "account_name": s.get("account_name"),
                "message_reason": s.get("message_reason"),
            })

        if not scored:
            return []

        # Normalize IR and CPI across the country group
        ir_values = [x["ir_raw"] for x in scored if x["ir_raw"] is not None]
        cpi_values = [x["cpi_raw"] for x in scored if x["cpi_raw"] is not None]
        ir_min, ir_max = (min(ir_values), max(ir_values)) if ir_values else (0, 1)
        cpi_min, cpi_max = (min(cpi_values), max(cpi_values)) if cpi_values else (0, 1)

        for x in scored:
            norm_ir = self._normalize_metric(x["ir_raw"], ir_min, ir_max) if x["ir_raw"] is not None else 0.0
            norm_cpi = self._normalize_metric(x["cpi_raw"], cpi_min, cpi_max) if x["cpi_raw"] is not None else 0.0
            x["composite_score"] = round(ir_weight * norm_ir + cpi_weight * norm_cpi, 4)
            x["ir_raw"] = round(x["ir_raw"], 2) if x["ir_raw"] is not None else None
            x["cpi_raw"] = round(x["cpi_raw"], 4) if x["cpi_raw"] is not None else None

        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        return scored[:limit]


# Singleton instance
_activation_service_instance = None


def get_activation_service() -> SurveyActivationService:
    """Get or create singleton activation service instance"""
    global _activation_service_instance
    if _activation_service_instance is None:
        _activation_service_instance = SurveyActivationService()
    return _activation_service_instance
