"""
CPX Audit API Router
Provides endpoints for CPX traffic audit and diagnostics
"""

from fastapi import APIRouter, HTTPException, Query, Request
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

router = APIRouter(prefix="/audit", tags=["audit"])

# Service instance (will be injected from main.py)
audit_service: Optional['AuditService'] = None  # Type hint for better IDE support


def set_audit_service(service: Any):
    """Set the audit service instance"""
    global audit_service
    audit_service = service


def get_audit_service() -> Any:
    """Get the audit service instance"""
    if audit_service is None:
        raise HTTPException(status_code=500, detail="Audit service not initialized")
    return audit_service


@router.get("/screenout-analysis")
async def get_screenout_analysis(
    lookback_hours: int = Query(24, ge=1, le=168, description="Hours to look back (max 7 days)")
) -> Dict[str, Any]:
    """
    Analyze screen-out patterns to identify root causes
    
    Returns breakdown by screen-out type:
    - IMMEDIATE_REJECT: < 5 seconds (geo/device/quota mismatch)
    - SCREENER_FAIL: < 30 seconds (demographic mismatch)
    - QUALITY_REJECT: > 30 seconds (traffic quality issues)
    """
    try:
        service = get_audit_service()
        analysis = service.analyze_screenout_patterns(lookback_hours)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/screenout-rate")
async def get_screenout_rate(
    last_n: int = Query(100, ge=10, le=1000, description="Number of recent records to analyze")
) -> Dict[str, Any]:
    """
    Calculate current screen-out rate
    
    Used for auto-pause monitoring
    """
    try:
        service = get_audit_service()
        rate = service.get_screenout_rate(last_n)
        should_pause, reason = service.check_auto_pause_condition()
        
        return {
            "screenout_rate": rate,
            "last_n": last_n,
            "should_auto_pause": should_pause,
            "auto_pause_reason": reason,
            "threshold": service.SCREENOUT_RATE_THRESHOLD
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rate calculation failed: {str(e)}")


@router.get("/time-of-day-analysis")
async def get_time_of_day_analysis(
    lookback_days: int = Query(7, ge=1, le=30, description="Days to look back")
) -> Dict[str, Any]:
    """
    Analyze screen-out rates by hour of day to detect inventory issues
    
    If screen-outs spike during certain hours, indicates no live inventory
    """
    try:
        service = get_audit_service()
        analysis = service.analyze_time_of_day_patterns(lookback_days)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/fingerprint-stats")
async def get_fingerprint_stats() -> Dict[str, Any]:
    """
    Get statistics about user fingerprinting
    
    Shows:
    - Total unique users
    - Repeat attempts blocked
    - Status distribution
    """
    try:
        service = get_audit_service()
        
        # Get total fingerprints
        total = service.fingerprint_collection.count_documents({})
        
        # Get status breakdown
        pipeline = [
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }
            }
        ]
        status_breakdown = list(service.fingerprint_collection.aggregate(pipeline))
        
        # Get repeat attempts
        repeat_attempts = service.fingerprint_collection.count_documents({
            "attempt_count": {"$gt": 1}
        })
        
        # Get blocked users
        blocked_users = service.fingerprint_collection.count_documents({
            "status": "BLOCKED"
        })
        
        return {
            "total_unique_users": total,
            "repeat_attempts": repeat_attempts,
            "blocked_users": blocked_users,
            "status_breakdown": {
                result["_id"]: result["count"] 
                for result in status_breakdown
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats retrieval failed: {str(e)}")


@router.get("/audit-logs")
async def get_audit_logs(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum logs to return")
) -> Dict[str, Any]:
    """
    Retrieve audit logs for investigation
    
    Event types:
    - user_blocked_repeat_attempt
    - pre_screen_data
    - cpx_redirect_out
    - cpx_redirect_in
    - parameter_integrity_violation
    - postback_validation_failed
    """
    try:
        service = get_audit_service()
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        query = {"timestamp": {"$gte": cutoff}}
        if event_type:
            query["event_type"] = event_type
        
        logs = list(
            service.audit_logs_collection.find(query)
            .sort("timestamp", -1)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for log in logs:
            log["_id"] = str(log["_id"])
        
        return {
            "logs": logs,
            "count": len(logs),
            "event_type_filter": event_type,
            "hours": hours
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Log retrieval failed: {str(e)}")


@router.get("/alerts")
async def get_alerts(
    resolved: Optional[bool] = Query(None, description="Filter by resolved status"),
    severity: Optional[str] = Query(None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    limit: int = Query(50, ge=1, le=500, description="Maximum alerts to return")
) -> Dict[str, Any]:
    """
    Retrieve automated alerts
    
    Alert types:
    - high_screenout_rate
    - subid_mismatch
    - instant_reject_spike
    - fingerprint_violation
    """
    try:
        service = get_audit_service()
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        query = {"timestamp": {"$gte": cutoff}}
        if resolved is not None:
            query["resolved"] = resolved
        if severity:
            query["severity"] = severity
        
        alerts = list(
            service.alerts_collection.find(query)
            .sort("timestamp", -1)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for alert in alerts:
            alert["_id"] = str(alert["_id"])
        
        return {
            "alerts": alerts,
            "count": len(alerts),
            "filters": {
                "resolved": resolved,
                "severity": severity,
                "hours": hours
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Alert retrieval failed: {str(e)}")


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str) -> Dict[str, Any]:
    """Mark an alert as resolved"""
    try:
        service = get_audit_service()
        from bson import ObjectId
        
        result = service.alerts_collection.update_one(
            {"_id": ObjectId(alert_id)},
            {
                "$set": {
                    "resolved": True,
                    "resolved_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Alert not found")
        
        return {"message": "Alert resolved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resolution failed: {str(e)}")


@router.get("/diagnostic-summary")
async def get_diagnostic_summary(
    hours: int = Query(24, ge=1, le=168, description="Hours to look back")
) -> Dict[str, Any]:
    """
    Get comprehensive diagnostic summary implementing the decision tree
    
    Checks for:
    - Same fingerprints (loop detection)
    - Instant rejects (geo/device mismatch)
    - Screener fails (pre-screen issues)
    - Long fails (traffic quality)
    - Subid mismatches (tracking issues)
    """
    try:
        service = get_audit_service()
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Check for fingerprint loops
        repeat_fingerprints = service.fingerprint_collection.count_documents({
            "attempt_count": {"$gt": 1},
            "last_attempt_at": {"$gte": cutoff}
        })
        
        # Get screenout analysis
        screenout_analysis = service.analyze_screenout_patterns(hours)
        
        # Get parameter integrity violations
        integrity_violations = service.audit_logs_collection.count_documents({
            "event_type": "parameter_integrity_violation",
            "timestamp": {"$gte": cutoff}
        })
        
        # Get current screenout rate
        screenout_rate = service.get_screenout_rate(100)
        
        # Determine primary issue
        issues = []
        if repeat_fingerprints > 10:
            issues.append({
                "type": "fingerprint_loop",
                "severity": "HIGH",
                "message": f"{repeat_fingerprints} repeat fingerprints detected - user recycling loop",
                "fix": "Implement harder blocking or increase cooldown period"
            })
        
        immediate_reject_pct = screenout_analysis.get("by_type", {}).get("IMMEDIATE_REJECT", {}).get("percentage", 0)
        if immediate_reject_pct > 50:
            issues.append({
                "type": "instant_rejects",
                "severity": "CRITICAL",
                "message": f"{immediate_reject_pct:.1f}% instant rejects - wrong geo/device/quota",
                "fix": "Check CPX targeting settings and traffic source geo/device match"
            })
        
        screener_fail_pct = screenout_analysis.get("by_type", {}).get("SCREENER_FAIL", {}).get("percentage", 0)
        if screener_fail_pct > 50:
            issues.append({
                "type": "screener_fails",
                "severity": "HIGH",
                "message": f"{screener_fail_pct:.1f}% screener fails - demographic mismatch",
                "fix": "Improve pre-screening or adjust CPX demographic targeting"
            })
        
        quality_reject_pct = screenout_analysis.get("by_type", {}).get("QUALITY_REJECT", {}).get("percentage", 0)
        if quality_reject_pct > 40:
            issues.append({
                "type": "quality_rejects",
                "severity": "MEDIUM",
                "message": f"{quality_reject_pct:.1f}% quality rejects - traffic reputation problem",
                "fix": "Review traffic source quality and consider changing vendors"
            })
        
        if integrity_violations > 0:
            issues.append({
                "type": "tracking_broken",
                "severity": "CRITICAL",
                "message": f"{integrity_violations} parameter integrity violations - broken tracking",
                "fix": "Investigate URL generation and callback parameter handling"
            })
        
        return {
            "timeframe_hours": hours,
            "screenout_rate": screenout_rate,
            "repeat_fingerprints": repeat_fingerprints,
            "integrity_violations": integrity_violations,
            "screenout_breakdown": screenout_analysis.get("by_type", {}),
            "issues": issues,
            "health_status": "CRITICAL" if any(i["severity"] == "CRITICAL" for i in issues) else (
                "WARNING" if issues else "HEALTHY"
            )
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Diagnostic summary failed: {str(e)}")
