"""
Cint Integration Extension for Survey Allocation Service

Extends the core survey allocation logic to support:
- Multi-provider survey allocation (CPX + Cint)
- Respondent matching across providers
- Unified metrics tracking
- Provider-specific entry link generation
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
from pymongo.collection import Collection

from app.models.cint import CintOpportunity, SupplierLink
from app.models.survey_allocation import Respondent, Survey, SurveyMetrics

logger = logging.getLogger(__name__)


class CintAllocationExtension:
    """
    Extension class to integrate Cint allocation with existing survey allocation service
    """
    
    def __init__(
        self,
        cint_surveys_collection: Optional[Collection] = None,
        cint_entry_links_collection: Optional[Collection] = None,
        cint_metrics_collection: Optional[Collection] = None,
        surveys_collection: Optional[Collection] = None,
        respondents_collection: Optional[Collection] = None,
        survey_metrics_collection: Optional[Collection] = None,
    ):
        """
        Initialize Cint allocation extension
        
        Args:
            cint_surveys_collection: MongoDB collection for Cint surveys
            cint_entry_links_collection: MongoDB collection for entry links
            cint_metrics_collection: MongoDB collection for Cint metrics
            surveys_collection: Shared surveys collection
            respondents_collection: Shared respondents collection
            survey_metrics_collection: Shared metrics collection
        """
        self.cint_surveys_collection = cint_surveys_collection
        self.cint_entry_links_collection = cint_entry_links_collection
        self.cint_metrics_collection = cint_metrics_collection
        self.surveys_collection = surveys_collection
        self.respondents_collection = respondents_collection
        self.survey_metrics_collection = survey_metrics_collection

    # ============================================
    # Respondent Matching
    # ============================================

    async def match_respondent_to_cint_surveys(
        self,
        respondent: Respondent,
        min_cpi: float = 0.0,
        max_loi: int = 60,
        preferred_countries: Optional[List[str]] = None,
    ) -> Optional[CintOpportunity]:
        """
        Match a respondent to the best available Cint survey
        
        Based on:
        - Country eligibility
        - Survey LOI vs respondent preference
        - CPI within budget
        - Remaining quota
        - Conversion rates (quality)
        
        Args:
            respondent: Respondent object with country_code
            min_cpi: Minimum acceptable CPI
            max_loi: Maximum acceptable LOI
            preferred_countries: List of preferred country codes (uses respondent.cc if None)
        
        Returns:
            Best matching CintOpportunity or None if no match
        """
        if self.cint_surveys_collection is None:
            return None
        
        try:
            # Build country filter
            if not preferred_countries:
                preferred_countries = [respondent.cc]
            
            # Query active surveys matching criteria
            query = {
                "is_active": True,
                "is_live": True,
                "total_remaining": {"$gt": 0},  # Has quota
                "country_language": {"$regex": f"^{respondent.cc}"},  # Country match
                "bid_length_of_interview": {"$lte": max_loi},
            }
            
            # Get available surveys sorted by quality metrics
            # Prioritize: high conversion > high CPI (revenue) > low LOI (faster)
            surveys = list(
                self.cint_surveys_collection.find(query)
                .sort([
                    ("conversion", -1),  # Higher completion rate first
                    ("mobile_conversion", -1),
                    ("revenue_per_interview.value", -1),  # Higher CPI second
                    ("bid_length_of_interview", 1),  # Shorter LOI third
                ])
                .limit(1)
            )
            
            if surveys:
                best_survey_data = surveys[0]
                opportunity = CintOpportunity(**best_survey_data)
                
                logger.info(
                    f"Matched respondent {respondent.rid} to Cint survey "
                    f"{opportunity.survey_id} ({opportunity.survey_name})"
                )
                
                return opportunity
        
        except Exception as e:
            logger.error(f"Error matching respondent to Cint surveys: {str(e)}")
        
        return None

    # ============================================
    # Entry Link Generation
    # ============================================

    async def build_cint_entry_link(
        self,
        respondent: Respondent,
        survey: CintOpportunity,
        cint_service: Optional[Any] = None,
    ) -> Optional[str]:
        """
        Build complete Cint entry link for respondent
        
        Args:
            respondent: Respondent object with country_code, rid
            survey: CintOpportunity to allocate
            cint_service: CintService instance for link building
        
        Returns:
            Complete entry link URL or None on error
        """
        try:
            # Get entry link from cache
            if self.cint_entry_links_collection is not None:
                link_doc = self.cint_entry_links_collection.find_one(
                    {"survey_id": survey.survey_id}
                )
                
                if link_doc:
                    entry_link = SupplierLink(**link_doc)
                    
                    # CRITICAL: Use live_link AS-IS from Cint API
                    # The live_link contains [%MID%] and other Cint placeholders
                    # that Cint replaces when respondent clicks
                    # DO NOT append custom parameters - they conflict with Cint's system
                    if entry_link.live_link:
                        logger.debug(
                            f"Using Cint live_link for survey {survey.survey_id}: "
                            f"respondent {respondent.rid}"
                        )
                        return entry_link.live_link
                    else:
                        logger.error(
                            f"Entry link exists but has no live_link for survey {survey.survey_id}"
                        )
        
        except Exception as e:
            logger.error(f"Error getting Cint entry link: {str(e)}")
        
        return None

    # ============================================
    # Metrics Tracking
    # ============================================

    async def update_cint_survey_metrics(
        self,
        survey_id: int,
        event_type: str,  # "sent", "started", "completed", "terminated", "quota_full"
    ) -> None:
        """
        Update survey metrics for Cint surveys
        
        Args:
            survey_id: Cint survey ID
            event_type: Type of event that occurred
        """
        if self.cint_metrics_collection is None:
            return
        
        try:
            update_doc = {
                "last_updated": datetime.utcnow(),
            }
            
            # Increment counter for event type
            if event_type == "sent":
                update_doc["$inc"] = {"sent_n": 1}
            elif event_type == "started":
                update_doc["$inc"] = {"entrants_n": 1}
            elif event_type == "completed":
                update_doc["$inc"] = {"completes_n": 1, "entrants_n": 1}
            elif event_type == "terminated":
                update_doc["$inc"] = {"terminates_n": 1, "entrants_n": 1}
            elif event_type == "quota_full":
                update_doc["$inc"] = {"quota_full_n": 1}
            
            # Upsert metrics document
            self.cint_metrics_collection.update_one(
                {"survey_id": survey_id},
                {"$set": update_doc, "$setOnInsert": {"survey_id": survey_id}},
                upsert=True,
            )
            
        except Exception as e:
            logger.error(f"Error updating Cint metrics for survey {survey_id}: {str(e)}")

    # ============================================
    # Multi-Provider Respondent Tracking
    # ============================================

    async def store_allocated_respondent(
        self,
        respondent: Respondent,
        provider: str,  # "cint" or "cpx"
        survey_id: int,
        survey_name: str,
        entry_link: str,
    ) -> Optional[str]:
        """
        Store respondent allocation in shared collection with provider info
        
        Args:
            respondent: Respondent object
            provider: Provider name ("cint" or "cpx")
            survey_id: External survey ID from provider
            survey_name: Survey name
            entry_link: Generated entry link
        
        Returns:
            MongoDB ObjectId of created/updated document
        """
        if self.respondents_collection is None:
            return None
        
        try:
            respondent_doc = {
                "vid": respondent.vid,
                "cc": respondent.cc,
                "rid": respondent.rid,
                "status": "allocated",
                "provider": provider,
                "survey_id": survey_id,
                "survey_name": survey_name,
                "entry_link": entry_link,
                "allocation_timestamp": datetime.utcnow(),
                "created_at": datetime.utcnow(),
            }
            
            # Upsert respondent
            result = self.respondents_collection.update_one(
                {"rid": respondent.rid, "cc": respondent.cc},
                {"$set": respondent_doc},
                upsert=True,
            )
            
            return str(result.upserted_id or result.modified_count)
        
        except Exception as e:
            logger.error(f"Error storing allocated respondent: {str(e)}")
        
        return None

    # ============================================
    # Auto-Pause Logic
    # ============================================

    async def evaluate_survey_for_pause(
        self,
        survey_id: int,
        min_incidence_rate: float = 10.0,
        max_incomplete_rate: float = 40.0,
        minimum_entrants: int = 50,
    ) -> bool:
        """
        Evaluate if Cint survey should be auto-paused based on quality metrics
        
        Args:
            survey_id: Cint survey ID
            min_incidence_rate: Minimum acceptable IR
            max_incomplete_rate: Maximum acceptable incomplete rate
            minimum_entrants: Minimum entrants before evaluation
        
        Returns:
            True if survey should be paused, False otherwise
        """
        if self.cint_metrics_collection is None or self.cint_surveys_collection is None:
            return False
        
        try:
            # Get metrics
            metrics = self.cint_metrics_collection.find_one({"survey_id": survey_id})
            
            if not metrics or metrics.get("entrants_n", 0) < minimum_entrants:
                return False  # Not enough data
            
            entrants = metrics["entrants_n"]
            completes = metrics.get("completes_n", 0)
            incompletes = metrics.get("incompletes_n", 0)
            
            # Calculate rates
            incidence_rate = (completes / entrants * 100) if entrants > 0 else 0
            incomplete_rate = (incompletes / entrants * 100) if entrants > 0 else 0
            
            # Check pause criteria
            should_pause = (
                incidence_rate < min_incidence_rate or
                incomplete_rate > max_incomplete_rate
            )
            
            if should_pause:
                logger.warning(
                    f"Survey {survey_id} quality threshold breached: "
                    f"IR={incidence_rate:.1f}% (min={min_incidence_rate}%), "
                    f"IR={incomplete_rate:.1f}% (max={max_incomplete_rate}%)"
                )
            
            return should_pause
        
        except Exception as e:
            logger.error(f"Error evaluating survey for pause: {str(e)}")
        
        return False

    # ============================================
    # Opportunity Updates
    # ============================================

    async def update_opportunity_from_webhook(
        self,
        survey_id: int,
        opportunity_data: Dict[str, Any],
    ) -> bool:
        """
        Update Cint opportunity from webhook data
        
        Args:
            survey_id: Cint survey ID
            opportunity_data: Updated opportunity data from webhook
        
        Returns:
            True if updated successfully
        """
        if self.cint_surveys_collection is None:
            return False
        
        try:
            # Determine if survey should be deactivated
            is_active = (
                opportunity_data.get("is_live", True) and
                opportunity_data.get("message_reason") != "deactivated"
            )
            
            update_doc = {
                **opportunity_data,
                "is_active": is_active,
                "last_updated_at": datetime.utcnow(),
            }
            
            result = self.cint_surveys_collection.update_one(
                {"survey_id": survey_id},
                {"$set": update_doc},
                upsert=True,
            )
            
            logger.info(
                f"Updated opportunity {survey_id}: "
                f"active={is_active}, reason={opportunity_data.get('message_reason')}"
            )
            
            return result.matched_count > 0 or result.upserted_id is not None
        
        except Exception as e:
            logger.error(f"Error updating opportunity: {str(e)}")
        
        return False

    # ============================================
    # Statistics & Reporting
    # ============================================

    async def get_cint_survey_stats(
        self,
        survey_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get performance statistics for Cint survey
        
        Args:
            survey_id: Cint survey ID
        
        Returns:
            Dictionary with performance metrics
        """
        if self.cint_metrics_collection is None:
            return None
        
        try:
            metrics = self.cint_metrics_collection.find_one({"survey_id": survey_id})
            
            if not metrics:
                return None
            
            # Calculate derived metrics
            entrants = metrics.get("entrants_n", 0)
            completes = metrics.get("completes_n", 0)
            incompletes = metrics.get("incompletes_n", 0)
            sent = metrics.get("sent_n", 0)
            
            return {
                "survey_id": survey_id,
                "sent": sent,
                "entrants": entrants,
                "completes": completes,
                "incompletes": incompletes,
                "terminates": metrics.get("terminates_n", 0),
                "quota_full": metrics.get("quota_full_n", 0),
                "incidence_rate": round((completes / entrants * 100) if entrants > 0 else 0, 2),
                "incomplete_rate": round((incompletes / entrants * 100) if entrants > 0 else 0, 2),
                "conversion_rate": round((completes / sent * 100) if sent > 0 else 0, 2),
                "last_updated": metrics.get("last_updated", datetime.utcnow()),
            }
        
        except Exception as e:
            logger.error(f"Error getting survey stats: {str(e)}")
        
        return None

    async def get_respondent_allocation_history(
        self,
        respondent_id: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get allocation history for a respondent
        
        Args:
            respondent_id: Respondent's unique ID
        
        Returns:
            List of allocation records or None
        """
        if self.respondents_collection is None:
            return None
        
        try:
            records = list(
                self.respondents_collection.find(
                    {"rid": respondent_id}
                ).sort([("allocation_timestamp", -1)])
            )
            
            return records
        
        except Exception as e:
            logger.error(f"Error getting respondent history: {str(e)}")
        
        return None
