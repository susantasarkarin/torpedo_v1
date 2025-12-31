"""
Sales Dashboard Router - Conversion-Focused KPIs

Provides:
- 5-stage funnel conversion metrics
- Velocity KPIs (time to contact, qualification time, etc.)
- Revenue-weighted metrics for managers
- Role-based view separation (rep vs manager)
- Threshold-based alerting

Stage Mapping:
- Lead Captured: leads_raw created_at
- Contacted: leads with email_threads or segment != 'lead_generation'
- Qualified: leads_enriched with confidence_score >= 0.7 or discovery_call segment
- RFQ Created: RFQ document created
- Deal Won: RFQ status = 'won'
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Literal
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sales",
    tags=["sales-dashboard"]
)

# MongoDB connections
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

# Databases
email_automation_db = mongo_client["email_automation"]
finance_db = mongo_client["finance_db"]

# Collections
leads_raw_collection = email_automation_db["leads_raw"]
leads_enriched_collection = email_automation_db["leads_enriched"]
email_leads_collection = email_automation_db["email_leads"]
rfqs_collection = email_automation_db["rfqs"]
contacts_collection = email_automation_db["contacts"]
invoices_collection = finance_db["invoices"]
customers_collection = finance_db["customers"]


# ============== ENUMS & MODELS ==============

class ViewRole(str, Enum):
    REP = "rep"
    MANAGER = "manager"


class FunnelStage(str, Enum):
    LEAD_CAPTURED = "lead_captured"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    RFQ_CREATED = "rfq_created"
    DEAL_WON = "deal_won"


class AlertLevel(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class ConversionKPI(BaseModel):
    """Single conversion rate KPI"""
    from_stage: str
    to_stage: str
    from_count: int
    to_count: int
    rate: float  # Percentage 0-100
    is_worst_dropoff: bool = False


class VelocityKPI(BaseModel):
    """Time-based velocity metric"""
    name: str
    value_hours: Optional[float] = None
    value_days: Optional[float] = None
    threshold_hours: Optional[float] = None
    threshold_days: Optional[float] = None
    alert_level: AlertLevel = AlertLevel.NORMAL
    breach_count: int = 0


class RevenueKPI(BaseModel):
    """Revenue-related metric"""
    name: str
    value: float
    currency: str = "USD"
    target: Optional[float] = None
    alert_level: AlertLevel = AlertLevel.NORMAL


class RFQAgingBucket(BaseModel):
    """RFQ aging distribution"""
    bucket: str  # "0-30", "31-60", "60+"
    count: int
    total_value: float


class FunnelData(BaseModel):
    """Complete funnel visualization data"""
    stages: List[Dict[str, Any]]
    conversions: List[ConversionKPI]
    end_to_end_rate: float
    worst_dropoff_stage: str


class SalesDashboardResponse(BaseModel):
    """Complete dashboard response"""
    # Metadata
    generated_at: datetime
    date_range: Dict[str, str]
    view_role: ViewRole
    
    # Funnel section
    funnel: FunnelData
    
    # Velocity section (rep + manager)
    velocity: List[VelocityKPI]
    
    # Revenue section (rep sees subset, manager sees all)
    revenue: List[RevenueKPI]
    
    # Manager-only sections
    rfq_aging: Optional[List[RFQAgingBucket]] = None
    rep_performance: Optional[List[Dict[str, Any]]] = None
    forecast_vs_actual: Optional[Dict[str, Any]] = None


# ============== HELPER FUNCTIONS ==============

def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime"""
    return datetime.strptime(date_str, "%Y-%m-%d")


def get_date_filter(start_date: str, end_date: str, field: str = "created_at") -> Dict:
    """Build MongoDB date filter"""
    start = parse_date(start_date)
    end = parse_date(end_date) + timedelta(days=1)  # Include end date
    return {field: {"$gte": start, "$lt": end}}


def calculate_conversion_rate(from_count: int, to_count: int) -> float:
    """Calculate conversion percentage"""
    if from_count == 0:
        return 0.0
    return round((to_count / from_count) * 100, 2)


def hours_between(dt1: Optional[datetime], dt2: Optional[datetime]) -> Optional[float]:
    """Calculate hours between two datetimes"""
    if not dt1 or not dt2:
        return None
    delta = dt2 - dt1
    return round(delta.total_seconds() / 3600, 2)


def days_between(dt1: Optional[datetime], dt2: Optional[datetime]) -> Optional[float]:
    """Calculate days between two datetimes"""
    if not dt1 or not dt2:
        return None
    delta = dt2 - dt1
    return round(delta.total_seconds() / 86400, 2)


# ============== STAGE COUNTING FUNCTIONS ==============

def count_leads_captured(date_filter: Dict) -> int:
    """Count leads captured in date range"""
    return leads_raw_collection.count_documents(date_filter)


def count_contacted(date_filter: Dict) -> int:
    """
    Count leads that have been contacted.
    A lead is 'contacted' if:
    - Has email_threads (in leads_enriched)
    - OR exists in email_leads with outreach/discovery segment
    """
    # Get leads with email threads
    leads_with_threads = leads_enriched_collection.count_documents({
        **date_filter,
        "email_threads": {"$exists": True, "$ne": []}
    })
    
    # Get leads with outreach emails
    email_leads_contacted = email_leads_collection.count_documents({
        **date_filter,
        "segment": {"$in": ["outreach", "discovery", "presentation", "rfq_pricing", "negotiation"]}
    })
    
    return max(leads_with_threads, email_leads_contacted)


def count_qualified(date_filter: Dict) -> int:
    """
    Count qualified leads.
    A lead is 'qualified' if:
    - Has confidence_score >= 0.7 in leads_enriched
    - OR has segment = discovery/presentation in email_leads
    """
    high_confidence = leads_enriched_collection.count_documents({
        **date_filter,
        "confidence_score": {"$gte": 0.7}
    })
    
    discovery_segment = email_leads_collection.count_documents({
        **date_filter,
        "segment": {"$in": ["discovery", "presentation"]}
    })
    
    return max(high_confidence, discovery_segment)


def count_rfqs_created(date_filter: Dict) -> int:
    """Count RFQs created in date range"""
    return rfqs_collection.count_documents(date_filter)


def count_deals_won(date_filter: Dict) -> int:
    """Count won deals in date range"""
    return rfqs_collection.count_documents({
        **date_filter,
        "status": "won"
    })


def count_deals_lost(date_filter: Dict) -> int:
    """Count lost deals in date range"""
    return rfqs_collection.count_documents({
        **date_filter,
        "status": "lost"
    })


# ============== VELOCITY CALCULATIONS ==============

def calculate_velocity_metrics(date_filter: Dict) -> List[VelocityKPI]:
    """Calculate all velocity KPIs"""
    velocities = []
    
    # Time to First Contact (hours)
    # Compare leads_raw.created_at to first email_thread date
    pipeline = [
        {"$match": {
            **date_filter,
            "email_threads": {"$exists": True, "$ne": []}
        }},
        {"$project": {
            "created_at": 1,
            "first_email": {"$arrayElemAt": ["$email_threads", 0]}
        }},
        {"$project": {
            "hours_to_contact": {
                "$divide": [
                    {"$subtract": ["$first_email.date", "$created_at"]},
                    3600000  # ms to hours
                ]
            }
        }},
        {"$group": {
            "_id": None,
            "avg_hours": {"$avg": "$hours_to_contact"},
            "breach_count": {
                "$sum": {"$cond": [{"$gt": ["$hours_to_contact", 24]}, 1, 0]}
            }
        }}
    ]
    
    result = list(leads_enriched_collection.aggregate(pipeline))
    if result:
        avg_hours = result[0].get("avg_hours", 0) or 0
        breach_count = result[0].get("breach_count", 0)
        alert = AlertLevel.CRITICAL if avg_hours > 24 else (AlertLevel.WARNING if avg_hours > 12 else AlertLevel.NORMAL)
        velocities.append(VelocityKPI(
            name="Time to First Contact",
            value_hours=round(avg_hours, 1),
            threshold_hours=24,
            alert_level=alert,
            breach_count=breach_count
        ))
    else:
        velocities.append(VelocityKPI(
            name="Time to First Contact",
            value_hours=None,
            threshold_hours=24,
            alert_level=AlertLevel.NORMAL
        ))
    
    # RFQ Cycle Time (days from created to closed)
    rfq_pipeline = [
        {"$match": {
            **date_filter,
            "status": {"$in": ["won", "lost"]},
            "closed_date": {"$exists": True, "$ne": None}
        }},
        {"$project": {
            "cycle_days": {
                "$divide": [
                    {"$subtract": ["$closed_date", "$created_at"]},
                    86400000  # ms to days
                ]
            }
        }},
        {"$group": {
            "_id": None,
            "avg_days": {"$avg": "$cycle_days"},
            "count": {"$sum": 1}
        }}
    ]
    
    rfq_result = list(rfqs_collection.aggregate(rfq_pipeline))
    if rfq_result and rfq_result[0].get("avg_days"):
        avg_days = rfq_result[0].get("avg_days", 0)
        velocities.append(VelocityKPI(
            name="RFQ Cycle Time",
            value_days=round(avg_days, 1),
            threshold_days=30,
            alert_level=AlertLevel.WARNING if avg_days > 30 else AlertLevel.NORMAL
        ))
    else:
        velocities.append(VelocityKPI(
            name="RFQ Cycle Time",
            value_days=None,
            threshold_days=30,
            alert_level=AlertLevel.NORMAL
        ))
    
    # Full Sales Cycle (lead created to deal won)
    # This requires joining data - simplified approach
    full_cycle_pipeline = [
        {"$match": {
            **date_filter,
            "status": "won",
            "closed_date": {"$exists": True, "$ne": None}
        }},
        {"$lookup": {
            "from": "leads_enriched",
            "localField": "contact_email",
            "foreignField": "email",
            "as": "lead"
        }},
        {"$unwind": {"path": "$lead", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "full_cycle_days": {
                "$divide": [
                    {"$subtract": ["$closed_date", {"$ifNull": ["$lead.created_at", "$created_at"]}]},
                    86400000
                ]
            }
        }},
        {"$group": {
            "_id": None,
            "avg_days": {"$avg": "$full_cycle_days"}
        }}
    ]
    
    full_result = list(rfqs_collection.aggregate(full_cycle_pipeline))
    if full_result and full_result[0].get("avg_days"):
        velocities.append(VelocityKPI(
            name="Full Sales Cycle",
            value_days=round(full_result[0]["avg_days"], 1),
            threshold_days=60,
            alert_level=AlertLevel.NORMAL
        ))
    else:
        velocities.append(VelocityKPI(
            name="Full Sales Cycle",
            value_days=None,
            threshold_days=60,
            alert_level=AlertLevel.NORMAL
        ))
    
    return velocities


# ============== REVENUE CALCULATIONS ==============

def calculate_revenue_metrics(date_filter: Dict, target: float = 100000) -> List[RevenueKPI]:
    """Calculate revenue KPIs"""
    revenues = []
    
    # Open Pipeline Value
    open_pipeline = rfqs_collection.aggregate([
        {"$match": {
            "status": {"$in": ["pending", "quoted", "negotiating"]}
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": "$value"}
        }}
    ])
    open_result = list(open_pipeline)
    pipeline_value = open_result[0]["total"] if open_result else 0
    
    # Pipeline Coverage Ratio
    coverage_ratio = pipeline_value / target if target > 0 else 0
    revenues.append(RevenueKPI(
        name="Pipeline Coverage Ratio",
        value=round(coverage_ratio, 2),
        target=3.0,  # 3x coverage is healthy
        alert_level=AlertLevel.CRITICAL if coverage_ratio < 2 else (AlertLevel.WARNING if coverage_ratio < 3 else AlertLevel.NORMAL)
    ))
    
    revenues.append(RevenueKPI(
        name="Open Pipeline Value",
        value=pipeline_value,
        currency="USD"
    ))
    
    # Won Deals Value
    won_pipeline = rfqs_collection.aggregate([
        {"$match": {
            **date_filter,
            "status": "won"
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": "$value"},
            "count": {"$sum": 1}
        }}
    ])
    won_result = list(won_pipeline)
    won_value = won_result[0]["total"] if won_result else 0
    won_count = won_result[0]["count"] if won_result else 0
    
    revenues.append(RevenueKPI(
        name="Won Deals Value",
        value=won_value,
        currency="USD"
    ))
    
    # Average Deal Size
    avg_deal_size = won_value / won_count if won_count > 0 else 0
    revenues.append(RevenueKPI(
        name="Average Deal Size",
        value=round(avg_deal_size, 2),
        currency="USD"
    ))
    
    # Lost Deals Value
    lost_pipeline = rfqs_collection.aggregate([
        {"$match": {
            **date_filter,
            "status": "lost"
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": "$value"}
        }}
    ])
    lost_result = list(lost_pipeline)
    lost_value = lost_result[0]["total"] if lost_result else 0
    
    revenues.append(RevenueKPI(
        name="Lost Deal Value",
        value=lost_value,
        currency="USD"
    ))
    
    # Revenue per Lead
    leads_count = leads_raw_collection.count_documents(date_filter)
    revenue_per_lead = won_value / leads_count if leads_count > 0 else 0
    revenues.append(RevenueKPI(
        name="Revenue per Lead",
        value=round(revenue_per_lead, 2),
        currency="USD"
    ))
    
    return revenues


# ============== MANAGER-ONLY METRICS ==============

def calculate_rfq_aging() -> List[RFQAgingBucket]:
    """Calculate RFQ aging buckets for open RFQs"""
    now = datetime.utcnow()
    
    buckets = []
    
    # 0-30 days
    bucket_0_30 = rfqs_collection.aggregate([
        {"$match": {
            "status": {"$in": ["pending", "quoted", "negotiating"]},
            "created_at": {"$gte": now - timedelta(days=30)}
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "count": {"$sum": 1},
            "total_value": {"$sum": "$value"}
        }}
    ])
    result = list(bucket_0_30)
    buckets.append(RFQAgingBucket(
        bucket="0-30",
        count=result[0]["count"] if result else 0,
        total_value=result[0]["total_value"] if result else 0
    ))
    
    # 31-60 days
    bucket_31_60 = rfqs_collection.aggregate([
        {"$match": {
            "status": {"$in": ["pending", "quoted", "negotiating"]},
            "created_at": {
                "$gte": now - timedelta(days=60),
                "$lt": now - timedelta(days=30)
            }
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "count": {"$sum": 1},
            "total_value": {"$sum": "$value"}
        }}
    ])
    result = list(bucket_31_60)
    buckets.append(RFQAgingBucket(
        bucket="31-60",
        count=result[0]["count"] if result else 0,
        total_value=result[0]["total_value"] if result else 0
    ))
    
    # 60+ days
    bucket_60_plus = rfqs_collection.aggregate([
        {"$match": {
            "status": {"$in": ["pending", "quoted", "negotiating"]},
            "created_at": {"$lt": now - timedelta(days=60)}
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "count": {"$sum": 1},
            "total_value": {"$sum": "$value"}
        }}
    ])
    result = list(bucket_60_plus)
    buckets.append(RFQAgingBucket(
        bucket="60+",
        count=result[0]["count"] if result else 0,
        total_value=result[0]["total_value"] if result else 0
    ))
    
    return buckets


def calculate_forecast_vs_actual(date_filter: Dict, target: float) -> Dict[str, Any]:
    """Calculate forecast vs actual revenue"""
    # Actual won revenue
    won_pipeline = rfqs_collection.aggregate([
        {"$match": {
            **date_filter,
            "status": "won"
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]}
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": "$value"}
        }}
    ])
    won_result = list(won_pipeline)
    actual = won_result[0]["total"] if won_result else 0
    
    # Weighted pipeline (probability-adjusted)
    # pending=10%, quoted=30%, negotiating=60%
    weighted_pipeline = rfqs_collection.aggregate([
        {"$match": {
            "status": {"$in": ["pending", "quoted", "negotiating"]}
        }},
        {"$project": {
            "value": {"$ifNull": ["$manual_value", "$extracted_value"]},
            "weight": {
                "$switch": {
                    "branches": [
                        {"case": {"$eq": ["$status", "pending"]}, "then": 0.1},
                        {"case": {"$eq": ["$status", "quoted"]}, "then": 0.3},
                        {"case": {"$eq": ["$status", "negotiating"]}, "then": 0.6}
                    ],
                    "default": 0
                }
            }
        }},
        {"$project": {
            "weighted_value": {"$multiply": ["$value", "$weight"]}
        }},
        {"$group": {
            "_id": None,
            "forecast": {"$sum": "$weighted_value"}
        }}
    ])
    forecast_result = list(weighted_pipeline)
    forecast = forecast_result[0]["forecast"] if forecast_result else 0
    
    return {
        "target": target,
        "actual": actual,
        "forecast": round(forecast, 2),
        "total_projected": round(actual + forecast, 2),
        "attainment_percent": round((actual / target) * 100, 2) if target > 0 else 0,
        "gap_to_target": round(target - actual, 2)
    }


# ============== MAIN DASHBOARD ENDPOINT ==============

@router.get("/dashboard", response_model=SalesDashboardResponse)
async def get_sales_dashboard(
    start_date: str = Query(
        default=(datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
        description="Start date YYYY-MM-DD"
    ),
    end_date: str = Query(
        default=datetime.utcnow().strftime("%Y-%m-%d"),
        description="End date YYYY-MM-DD"
    ),
    role: ViewRole = Query(default=ViewRole.REP, description="View role: rep or manager"),
    target: float = Query(default=100000, description="Revenue target for coverage calculations")
):
    """
    Get conversion-focused sales dashboard.
    
    - **role=rep**: Stage conversions, win rate, avg deal size, sales cycle
    - **role=manager**: All rep metrics + funnel dropoffs, RFQ aging, forecast vs actual
    """
    try:
        date_filter = get_date_filter(start_date, end_date)
        
        # ========== FUNNEL COUNTS ==========
        lead_captured = count_leads_captured(date_filter)
        contacted = count_contacted(date_filter)
        qualified = count_qualified(date_filter)
        rfq_created = count_rfqs_created(date_filter)
        deal_won = count_deals_won(date_filter)
        
        # ========== CONVERSION RATES ==========
        conversions = []
        
        # Lead → Contacted
        lead_to_contact = calculate_conversion_rate(lead_captured, contacted)
        conversions.append(ConversionKPI(
            from_stage="Lead Captured",
            to_stage="Contacted",
            from_count=lead_captured,
            to_count=contacted,
            rate=lead_to_contact
        ))
        
        # Contacted → Qualified
        contact_to_qualified = calculate_conversion_rate(contacted, qualified)
        conversions.append(ConversionKPI(
            from_stage="Contacted",
            to_stage="Qualified",
            from_count=contacted,
            to_count=qualified,
            rate=contact_to_qualified
        ))
        
        # Qualified → RFQ Created
        qualified_to_rfq = calculate_conversion_rate(qualified, rfq_created)
        conversions.append(ConversionKPI(
            from_stage="Qualified",
            to_stage="RFQ Created",
            from_count=qualified,
            to_count=rfq_created,
            rate=qualified_to_rfq
        ))
        
        # RFQ → Won
        rfq_to_won = calculate_conversion_rate(rfq_created, deal_won)
        conversions.append(ConversionKPI(
            from_stage="RFQ Created",
            to_stage="Deal Won",
            from_count=rfq_created,
            to_count=deal_won,
            rate=rfq_to_won
        ))
        
        # Find worst dropoff
        if conversions:
            worst_idx = min(range(len(conversions)), key=lambda i: conversions[i].rate)
            conversions[worst_idx].is_worst_dropoff = True
            worst_dropoff_stage = conversions[worst_idx].from_stage
        else:
            worst_dropoff_stage = "N/A"
        
        # End-to-end conversion
        end_to_end = calculate_conversion_rate(lead_captured, deal_won)
        
        # Build funnel data
        funnel = FunnelData(
            stages=[
                {"name": "Lead Captured", "count": lead_captured, "icon": "🎯"},
                {"name": "Contacted", "count": contacted, "icon": "📧"},
                {"name": "Qualified", "count": qualified, "icon": "✓"},
                {"name": "RFQ Created", "count": rfq_created, "icon": "💰"},
                {"name": "Deal Won", "count": deal_won, "icon": "🏆"}
            ],
            conversions=conversions,
            end_to_end_rate=end_to_end,
            worst_dropoff_stage=worst_dropoff_stage
        )
        
        # ========== VELOCITY METRICS ==========
        velocity = calculate_velocity_metrics(date_filter)
        
        # ========== REVENUE METRICS ==========
        revenue = calculate_revenue_metrics(date_filter, target)
        
        # Add Win Rate to revenue metrics
        deal_lost = count_deals_lost(date_filter)
        total_closed = deal_won + deal_lost
        win_rate = calculate_conversion_rate(total_closed, deal_won) if total_closed > 0 else 0
        revenue.insert(0, RevenueKPI(
            name="Win Rate",
            value=win_rate,
            target=30.0  # 30% win rate target
        ))
        
        # ========== MANAGER-ONLY METRICS ==========
        rfq_aging = None
        forecast_vs_actual = None
        
        if role == ViewRole.MANAGER:
            rfq_aging = calculate_rfq_aging()
            forecast_vs_actual = calculate_forecast_vs_actual(date_filter, target)
        
        return SalesDashboardResponse(
            generated_at=datetime.utcnow(),
            date_range={"start": start_date, "end": end_date},
            view_role=role,
            funnel=funnel,
            velocity=velocity,
            revenue=revenue,
            rfq_aging=rfq_aging,
            forecast_vs_actual=forecast_vs_actual
        )
        
    except Exception as e:
        logger.error(f"Error generating sales dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== FUNNEL DRILL-DOWN ENDPOINT ==============

@router.get("/funnel/{stage}")
async def get_funnel_stage_details(
    stage: FunnelStage,
    start_date: str = Query(default=(datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")),
    end_date: str = Query(default=datetime.utcnow().strftime("%Y-%m-%d")),
    limit: int = Query(default=50, le=100)
):
    """Get detailed records for a specific funnel stage (drill-down)"""
    date_filter = get_date_filter(start_date, end_date)
    
    if stage == FunnelStage.LEAD_CAPTURED:
        leads = list(leads_raw_collection.find(date_filter).limit(limit))
        for lead in leads:
            lead["_id"] = str(lead["_id"])
        return {"stage": stage, "count": len(leads), "records": leads}
    
    elif stage == FunnelStage.CONTACTED:
        leads = list(leads_enriched_collection.find({
            **date_filter,
            "email_threads": {"$exists": True, "$ne": []}
        }).limit(limit))
        for lead in leads:
            lead["_id"] = str(lead["_id"])
        return {"stage": stage, "count": len(leads), "records": leads}
    
    elif stage == FunnelStage.QUALIFIED:
        leads = list(leads_enriched_collection.find({
            **date_filter,
            "confidence_score": {"$gte": 0.7}
        }).limit(limit))
        for lead in leads:
            lead["_id"] = str(lead["_id"])
        return {"stage": stage, "count": len(leads), "records": leads}
    
    elif stage == FunnelStage.RFQ_CREATED:
        rfqs = list(rfqs_collection.find(date_filter).limit(limit))
        for rfq in rfqs:
            rfq["_id"] = str(rfq["_id"])
        return {"stage": stage, "count": len(rfqs), "records": rfqs}
    
    elif stage == FunnelStage.DEAL_WON:
        rfqs = list(rfqs_collection.find({**date_filter, "status": "won"}).limit(limit))
        for rfq in rfqs:
            rfq["_id"] = str(rfq["_id"])
        return {"stage": stage, "count": len(rfqs), "records": rfqs}
    
    return {"stage": stage, "count": 0, "records": []}
