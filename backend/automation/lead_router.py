"""
Lead Router - Autonomous lead-to-campaign routing

Automatically assigns qualified leads to campaigns based on:
1. Lead segmentation attributes (seniority, industry, company size, etc)
2. Campaign ICP (Ideal Customer Profile)
3. Confidence score matching (strict 0.85+ threshold)

Decision Logging: Every routing decision logged with confidence score and reasoning
"""

import logging
from typing import Optional, Dict, Any, List
from pymongo.database import Database
from datetime import datetime

logger = logging.getLogger(__name__)


class LeadRouter:
    """
    Autonomous lead routing engine.

    Routes qualified leads to campaigns based on ICP matching.
    Uses strict 0.85+ confidence threshold to ensure high quality matches.
    """

    # Strict confidence threshold
    MIN_CONFIDENCE_THRESHOLD = 0.85

    # Attribute weights for ICP matching
    ICP_MATCH_WEIGHTS = {
        "seniority_level": 0.25,      # Job level importance
        "department": 0.20,            # Department fit
        "company_size": 0.20,          # Company size alignment
        "industry": 0.15,              # Industry match
        "persona": 0.10,               # Buyer persona fit
        "region": 0.10                 # Geographic alignment
    }

    def __init__(self, db: Database, decision_logger=None):
        """
        Initialize router.

        Args:
            db: MongoDB database instance
            decision_logger: Optional DecisionLogger instance for compliance logging
        """
        self.db = db
        self.leads = db["leads_enriched"]
        self.campaigns = db["campaigns"]
        self.campaign_recipients = db["campaign_recipients"]
        self.decision_logger = decision_logger

    def route_qualified_leads(self, campaign_id: str, auto_route: bool = True) -> Dict[str, Any]:
        """
        Auto-route all qualified leads to a campaign based on its ICP.

        Args:
            campaign_id: Campaign to route leads to
            auto_route: If True, actually create recipients; if False, just return results

        Returns:
            Dict with routing_results:
            {
                "campaign_id": "...",
                "routed_count": 42,
                "skipped_count": 8,
                "details": [
                    {
                        "lead_id": "...",
                        "lead_name": "John Doe",
                        "confidence_score": 0.90,
                        "matches": ["seniority", "industry"],
                        "action": "routed|skipped"
                    }
                ],
                "decision_logs": ["decision_id_1", "decision_id_2", ...]
            }
        """
        # Get campaign and its ICP
        campaign = self.campaigns.find_one({"_id": campaign_id})
        if not campaign:
            logger.error(f"Campaign {campaign_id} not found")
            return {
                "campaign_id": campaign_id,
                "error": "Campaign not found",
                "routed_count": 0,
                "skipped_count": 0
            }

        # Extract ICP from campaign
        icp = self._extract_campaign_icp(campaign)
        logger.info(f"Routing leads to campaign {campaign_id} with ICP: {icp}")

        # Find all qualified leads not already in campaign
        existing_lead_ids = set(
            self.campaign_recipients.find(
                {"campaign_id": campaign_id},
                {"lead_id": 1}
            ).distinct("lead_id")
        )

        # Find qualified, unrouted leads
        qualified_leads = list(self.leads.find({
            "_id": {"$nin": list(existing_lead_ids)},
            "engagement_status": {"$ne": "unsubscribed"},
            "priority_score": {"$gte": 0.50}  # Only qualified leads
        }))

        logger.info(f"Found {len(qualified_leads)} qualified unrouted leads for campaign {campaign_id}")

        routed_leads = []
        skipped_leads = []
        decision_ids = []

        # Route each lead
        for lead in qualified_leads:
            confidence, matches = self._calculate_icp_match(lead, icp)

            decision_type = "lead_routing"
            action = "skip"  # Default

            if confidence >= self.MIN_CONFIDENCE_THRESHOLD:
                action = "route_to_campaign"
                routed_leads.append(lead)

                # Actually create recipient if auto_route=True
                if auto_route:
                    try:
                        recipient_doc = {
                            "campaign_id": campaign_id,
                            "lead_id": str(lead["_id"]),
                            "lead_email": lead.get("email", ""),
                            "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                            "lead_company": lead.get("company_name", ""),
                            "status": "PENDING",
                            "current_step": 0,
                            "created_at": datetime.utcnow()
                        }
                        self.campaign_recipients.insert_one(recipient_doc)
                        logger.debug(f"Added lead {lead.get('email')} to campaign {campaign_id}")
                    except Exception as e:
                        logger.error(f"Failed to add lead to campaign: {e}")
                        action = "failed"
            else:
                skipped_leads.append(lead)

            # Log decision for compliance
            if self.decision_logger:
                decision_id = self.decision_logger.log_decision(
                    decision_type="lead_routing",
                    action=action,
                    autonomous=True,
                    lead_id=str(lead["_id"]),
                    campaign_id=campaign_id,
                    confidence_score=confidence,
                    reasoning={
                        "rule_matched": "ICP matching",
                        "icp_weights": self.ICP_MATCH_WEIGHTS,
                        "matched_attributes": matches,
                        "threshold_used": self.MIN_CONFIDENCE_THRESHOLD
                    },
                    input_context={
                        "lead_attributes": {
                            "seniority": lead.get("seniority_level"),
                            "department": lead.get("department"),
                            "company_size": lead.get("company_size"),
                            "industry": lead.get("industry"),
                            "persona": lead.get("persona"),
                            "region": lead.get("region")
                        },
                        "campaign_icp": icp
                    },
                    decision_params={
                        "action": action,
                        "campaign_id": campaign_id
                    }
                )
                decision_ids.append(decision_id)

        logger.info(
            f"Routing complete: {len(routed_leads)} routed, {len(skipped_leads)} skipped"
        )

        return {
            "campaign_id": campaign_id,
            "routed_count": len(routed_leads),
            "skipped_count": len(skipped_leads),
            "details": [
                {
                    "lead_id": str(lead["_id"]),
                    "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                    "lead_email": lead.get("email"),
                    "confidence_score": round(self._calculate_icp_match(lead, icp)[0], 3),
                    "action": "routed"
                }
                for lead in routed_leads
            ] + [
                {
                    "lead_id": str(lead["_id"]),
                    "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                    "lead_email": lead.get("email"),
                    "confidence_score": round(self._calculate_icp_match(lead, icp)[0], 3),
                    "action": "skipped (low confidence)"
                }
                for lead in skipped_leads
            ],
            "decision_logs": decision_ids
        }

    def _extract_campaign_icp(self, campaign: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract ICP (Ideal Customer Profile) from campaign.

        Looks for:
        - ideal_seniority_levels
        - ideal_departments
        - ideal_industries
        - ideal_company_sizes
        - ideal_personas
        - ideal_regions
        """
        settings = campaign.get("settings", {})

        return {
            "seniority_levels": settings.get("ideal_seniority_levels", []),
            "departments": settings.get("ideal_departments", []),
            "industries": settings.get("ideal_industries", []),
            "company_sizes": settings.get("ideal_company_sizes", []),
            "personas": settings.get("ideal_personas", []),
            "regions": settings.get("ideal_regions", [])
        }

    def _calculate_icp_match(
        self,
        lead: Dict[str, Any],
        icp: Dict[str, Any]
    ) -> tuple:
        """
        Calculate ICP match confidence score for a lead.

        Returns:
            (confidence_score: float, matched_attributes: list)
            confidence_score ranges from 0.0 to 1.0
        """
        matched_attributes = []
        total_score = 0.0

        # Check seniority level match
        if lead.get("seniority_level") in icp.get("seniority_levels", []):
            matched_attributes.append("seniority_level")
            total_score += self.ICP_MATCH_WEIGHTS["seniority_level"]

        # Check department match
        if lead.get("department") in icp.get("departments", []):
            matched_attributes.append("department")
            total_score += self.ICP_MATCH_WEIGHTS["department"]

        # Check company size match
        if lead.get("company_size") in icp.get("company_sizes", []):
            matched_attributes.append("company_size")
            total_score += self.ICP_MATCH_WEIGHTS["company_size"]

        # Check industry match
        if lead.get("industry") in icp.get("industries", []):
            matched_attributes.append("industry")
            total_score += self.ICP_MATCH_WEIGHTS["industry"]

        # Check persona match
        if lead.get("persona") in icp.get("personas", []):
            matched_attributes.append("persona")
            total_score += self.ICP_MATCH_WEIGHTS["persona"]

        # Check region match
        if lead.get("region") in icp.get("regions", []):
            matched_attributes.append("region")
            total_score += self.ICP_MATCH_WEIGHTS["region"]

        # If ICP is empty/not set, be conservative (lower confidence)
        if not any(icp.values()):
            total_score = 0.5  # Default to 0.5 if no ICP criteria set

        return (total_score, matched_attributes)

    def get_routing_stats(self, campaign_id: str) -> Dict[str, Any]:
        """
        Get routing statistics for a campaign.

        Returns routing counts, confidence score distribution, etc.
        """
        recipients = list(self.campaign_recipients.find({"campaign_id": campaign_id}))

        stats = {
            "campaign_id": campaign_id,
            "total_recipients": len(recipients),
            "by_status": {}
        }

        # Count by status
        for status in ["PENDING", "IN_SEQUENCE", "REPLIED", "COMPLETED"]:
            count = len([r for r in recipients if r.get("status") == status])
            if count > 0:
                stats["by_status"][status] = count

        return stats
