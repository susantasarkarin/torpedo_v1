"""
Automation API Endpoints
Provides REST API for autonomous campaign setup features:
- Lead routing
- Email optimization
- Campaign scheduling

All endpoints include full compliance logging for GDPR/CAN-SPAM
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pymongo.database import Database
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/automation", tags=["Automation"])


# Dependency: Get database
def get_database() -> Database:
    """Get MongoDB database instance"""
    from pymongo import MongoClient
    import os
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return client['email_automation']


@router.post("/campaigns/{campaign_id}/auto-route")
async def trigger_auto_routing(
    campaign_id: str,
    log_decisions: bool = True,
    db: Database = Depends(get_database)
) -> dict:
    """
    Autonomously route qualified leads to campaign (0.85+ confidence threshold).

    Endpoint: POST /automation/campaigns/{campaign_id}/auto-route

    Request:
    {
        "campaign_id": "...",
        "log_decisions": true
    }

    Response:
    {
        "campaign_id": "...",
        "routed_count": 42,
        "skipped_count": 8,
        "decision_logs": ["decision_id_1", ...]
    }

    Full audit trail logged to campaign_decisions collection for compliance.
    """
    try:
        from backend.automation.lead_router import LeadRouter
        from backend.automation.decision_logger import DecisionLogger

        decision_logger = None
        if log_decisions:
            decision_logger = DecisionLogger(db)

        router = LeadRouter(db, decision_logger=decision_logger)
        result = router.route_qualified_leads(campaign_id, auto_route=True)

        logger.info(f"Auto-routing completed for campaign {campaign_id}: {result['routed_count']} routed")

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "routed_count": result.get("routed_count", 0),
            "skipped_count": result.get("skipped_count", 0),
            "details": result.get("details", []),
            "decision_logs": result.get("decision_logs", []),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Auto-routing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/auto-generate-email-variants")
async def trigger_email_optimization(
    campaign_id: str,
    base_template_id: str,
    auto_select: bool = True,
    log_decisions: bool = True,
    db: Database = Depends(get_database)
) -> dict:
    """
    Generate optimized email variants with maximum personalization.

    Endpoint: POST /automation/campaigns/{campaign_id}/auto-generate-email-variants

    Request:
    {
        "campaign_id": "...",
        "base_template_id": "...",
        "auto_select": true,
        "log_decisions": true
    }

    Response:
    {
        "campaign_id": "...",
        "variants": [
            {
                "name": "Executive Focus",
                "subject": "...",
                "confidence_score": 0.92
            },
            ...
        ],
        "selected_variant_id": "Executive Focus"
    }

    Generates 3 variants with completely different tones:
    1. Executive Focus - authority-driven for C-level
    2. Problem Solver - consultative for practitioners
    3. Innovator - dynamic for forward-thinking leaders

    Full reasoning and all variants logged for compliance.
    """
    try:
        from backend.automation.email_optimizer import EmailOptimizer
        from backend.leads.openai_wrapper import get_openai_client
        from backend.leads.openai_wrapper import chat_completion
        from backend.automation.decision_logger import DecisionLogger

        decision_logger = None
        if log_decisions:
            decision_logger = DecisionLogger(db)

        optimizer = EmailOptimizer(
            db,
            openai_wrapper=type('obj', (object,), {'chat_completion': chat_completion})(),
            decision_logger=decision_logger
        )

        result = optimizer.generate_variants(campaign_id, base_template_id, auto_select=auto_select)

        logger.info(f"Email optimization completed for campaign {campaign_id}: {len(result.get('variants', []))} variants generated")

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "variants": result.get("variants", []),
            "selected_variant_id": result.get("selected_variant_id"),
            "decision_log_id": result.get("decision_log_id"),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Email optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/{campaign_id}/auto-optimize-schedule")
async def trigger_schedule_optimization(
    campaign_id: str,
    log_decisions: bool = True,
    db: Database = Depends(get_database)
) -> dict:
    """
    Optimize campaign send schedule using historical data + industry defaults.

    Endpoint: POST /automation/campaigns/{campaign_id}/auto-optimize-schedule

    Request:
    {
        "campaign_id": "...",
        "log_decisions": true
    }

    Response:
    {
        "campaign_id": "...",
        "send_schedule": {
            "step_0": {"delay_days": 0, "send_hours": [9, 14], ...},
            "step_1": {"delay_days": 3, "send_hours": [9, 14], ...},
            ...
        },
        "optimization_reasoning": "Hybrid approach..."
    }

    Hybrid approach:
    - Analyzes historical engagement by hour/day if available (>20 samples)
    - Falls back to industry best practices (9am, 2pm, Mon-Thu)
    - Adjusts sequence delays based on lead seniority distribution
    - Timezone-aware sending recommendations

    Full reasoning logged for compliance.
    """
    try:
        from backend.automation.campaign_scheduler import CampaignScheduler
        from backend.automation.decision_logger import DecisionLogger

        decision_logger = None
        if log_decisions:
            decision_logger = DecisionLogger(db)

        scheduler = CampaignScheduler(db, decision_logger=decision_logger)
        result = scheduler.optimize_schedule(campaign_id)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        logger.info(f"Schedule optimization completed for campaign {campaign_id}")

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "send_schedule": result.get("send_schedule"),
            "optimization_reasoning": result.get("optimization_reasoning"),
            "confidence_score": result.get("confidence_score"),
            "decision_log_id": result.get("decision_log_id"),
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Schedule optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns/{campaign_id}/automation-status")
async def get_automation_status(
    campaign_id: str,
    db: Database = Depends(get_database)
) -> dict:
    """
    Get automation status and history for campaign.

    Shows:
    - Lead routing: # routed, confidence scores
    - Email variants: selected variant, alternatives
    - Schedule: current schedule, optimization approach

    Endpoint: GET /automation/campaigns/{campaign_id}/automation-status
    """
    try:
        campaigns = db["campaigns"]
        campaign = campaigns.find_one({"_id": campaign_id})

        if not campaign:
            raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")

        return {
            "campaign_id": campaign_id,
            "routing": {
                "enabled": campaign.get("auto_routing_enabled", False),
                "mode": "ICP matching (0.85+ confidence threshold)",
            },
            "email_optimization": {
                "enabled": campaign.get("email_variants") is not None,
                "selected_variant": campaign.get("selected_email_variant"),
                "variant_count": len(campaign.get("email_variants", [])) if "email_variants" in campaign else 0,
                "variant_selection_confidence": "high"
            },
            "schedule_optimization": {
                "enabled": campaign.get("optimized_schedule") is not None,
                "approach": campaign.get("schedule_approach", "default"),
                "optimization_time": campaign.get("schedule_optimization_time"),
            },
            "compliance_logging": {
                "enabled": True,
                "collection": "campaign_decisions",
                "audit_trail": "Full decision reasoning with confidence scores"
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get automation status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions/audit-trail")
async def get_audit_trail(
    campaign_id: Optional[str] = None,
    decision_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 50,
    db: Database = Depends(get_database)
) -> dict:
    """
    Get compliance audit trail of all autonomous decisions.

    Endpoint: GET /automation/decisions/audit-trail?campaign_id=...&decision_type=...

    Query params:
    - campaign_id: Filter by campaign
    - decision_type: Filter by decision type (lead_routing, email_generation, schedule_optimization)
    - hours: Look back N hours (default 24)
    - limit: Max results (default 50)

    Response: Array of decisions with full reasoning, confidence scores, and input context
    """
    try:
        from backend.automation.decision_logger import DecisionLogger

        decision_logger = DecisionLogger(db)
        decisions = decision_logger.get_decision_history(
            campaign_id=campaign_id,
            decision_type=decision_type,
            limit=limit
        )

        return {
            "status": "success",
            "total": len(decisions),
            "decisions": decisions,
            "filters": {
                "campaign_id": campaign_id,
                "decision_type": decision_type,
                "limit": limit
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get audit trail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions/confidence-stats")
async def get_confidence_stats(
    decision_type: Optional[str] = None,
    hours: int = 24,
    db: Database = Depends(get_database)
) -> dict:
    """
    Get quality metrics for autonomous decisions.

    Shows:
    - Average confidence score by decision type
    - Percentage of decisions below 0.85 threshold
    - Volume of decisions

    Endpoint: GET /automation/decisions/confidence-stats?decision_type=...&hours=...

    Used to monitor automation quality and ensure high confidence before fully deploying.
    """
    try:
        from backend.automation.decision_logger import DecisionLogger

        decision_logger = DecisionLogger(db)
        stats = decision_logger.get_confidence_stats(
            decision_type=decision_type,
            hours=hours
        )

        return {
            "status": "success",
            "stats": stats,
            "filters": {
                "decision_type": decision_type,
                "hours": hours
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get confidence stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
