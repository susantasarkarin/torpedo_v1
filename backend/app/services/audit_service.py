"""
CPX Audit Service
Implements comprehensive audit framework for CPX traffic flow
Including user fingerprinting, parameter tracking, and failure analysis
"""

import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pymongo.collection import Collection
from bson import ObjectId


class AuditService:
    """Service for auditing CPX traffic and detecting issues"""
    
    # Screen-out classification thresholds (in seconds)
    IMMEDIATE_REJECT_THRESHOLD = 5
    SCREENER_FAIL_THRESHOLD = 30
    
    # Alert thresholds
    SCREENOUT_RATE_THRESHOLD = 0.80  # 80%
    INSTANT_REJECT_RATE_THRESHOLD = 0.30  # 30%
    
    def __init__(
        self,
        traffic_collection: Collection,
        audit_logs_collection: Collection,
        fingerprint_collection: Collection,
        alerts_collection: Collection,
    ):
        """
        Initialize Audit Service
        
        Args:
            traffic_collection: Traffic records collection
            audit_logs_collection: Audit event logs collection
            fingerprint_collection: User fingerprint tracking collection
            alerts_collection: Automated alerts collection
        """
        self.traffic_collection = traffic_collection
        self.audit_logs_collection = audit_logs_collection
        self.fingerprint_collection = fingerprint_collection
        self.alerts_collection = alerts_collection
        
        # Ensure indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create necessary indexes for audit queries"""
        try:
            # Fingerprint indexes
            self.fingerprint_collection.create_index("fingerprint_hash", unique=True)
            self.fingerprint_collection.create_index("first_seen_at")
            self.fingerprint_collection.create_index("status")
            
            # Audit log indexes
            self.audit_logs_collection.create_index("event_type")
            self.audit_logs_collection.create_index("timestamp")
            self.audit_logs_collection.create_index("user_id")
            
            # Traffic collection indexes for audit queries
            self.traffic_collection.create_index("fingerprint_hash")
            self.traffic_collection.create_index([("createdAt", -1)])
            self.traffic_collection.create_index("screenout_type")
            self.traffic_collection.create_index("duration_seconds")
            
            # Alert indexes
            self.alerts_collection.create_index("alert_type")
            self.alerts_collection.create_index("timestamp")
            self.alerts_collection.create_index("resolved")
            
        except Exception as e:
            print(f"⚠️ Warning: Could not create audit indexes: {e}")
    
    @staticmethod
    def generate_fingerprint(ip: str, user_agent: str, accept_language: str = "") -> str:
        """
        Generate user fingerprint hash
        
        Args:
            ip: IP address
            user_agent: Browser user agent string
            accept_language: Accept-Language header
            
        Returns:
            SHA256 hash of fingerprint
        """
        raw = f"{ip}|{user_agent}|{accept_language}"
        return hashlib.sha256(raw.encode()).hexdigest()
    
    def check_user_fingerprint(
        self,
        ip: str,
        user_agent: str,
        accept_language: str = ""
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if user fingerprint already exists and should be blocked
        
        Args:
            ip: IP address
            user_agent: User agent string
            accept_language: Accept-Language header
            
        Returns:
            Tuple of (should_block, fingerprint_record)
        """
        fingerprint_hash = self.generate_fingerprint(ip, user_agent, accept_language)
        
        # Look up fingerprint
        fingerprint_record = self.fingerprint_collection.find_one({
            "fingerprint_hash": fingerprint_hash
        })
        
        if not fingerprint_record:
            # New user - create fingerprint record
            fingerprint_record = {
                "fingerprint_hash": fingerprint_hash,
                "first_seen_at": datetime.utcnow(),
                "attempt_count": 0,
                "last_attempt_at": None,
                "status": "NEW",  # NEW | SENT_TO_CPX | SCREENED_OUT | COMPLETED | BLOCKED
                "traffic_ids": []
            }
            self.fingerprint_collection.insert_one(fingerprint_record)
            return False, fingerprint_record
        
        # Existing user - check if should block
        attempt_count = fingerprint_record.get("attempt_count", 0)
        status = fingerprint_record.get("status", "NEW")
        
        # HARD ASSERTION: Block if user already attempted CPX
        # Note: attempt_count > 1 means this is a repeat attempt
        # Status check ensures we're not blocking legitimate first attempts
        if attempt_count > 1:
            self._log_audit_event("user_blocked_repeat_attempt", {
                "fingerprint_hash": fingerprint_hash,
                "attempt_count": attempt_count,
                "status": status,
                "reason": "User has multiple CPX attempts"
            })
            return True, fingerprint_record
        
        return False, fingerprint_record
    
    def update_fingerprint_status(
        self,
        fingerprint_hash: str,
        status: str,
        traffic_id: str
    ):
        """
        Update fingerprint record after traffic assignment
        
        Args:
            fingerprint_hash: Fingerprint hash
            status: New status
            traffic_id: Associated traffic record ID
        """
        self.fingerprint_collection.update_one(
            {"fingerprint_hash": fingerprint_hash},
            {
                "$set": {
                    "status": status,
                    "last_attempt_at": datetime.utcnow()
                },
                "$inc": {"attempt_count": 1},
                "$push": {"traffic_ids": traffic_id}
            }
        )
    
    def log_pre_screen_data(
        self,
        user_id: str,
        demographic_data: Dict[str, Any]
    ):
        """
        Log demographic data before redirect for CPX matching analysis
        
        Args:
            user_id: User/traffic ID
            demographic_data: Dict with age, gender, country, device, language
        """
        log_entry = {
            "event_type": "pre_screen_data",
            "timestamp": datetime.utcnow(),
            "user_id": user_id,
            **demographic_data
        }
        self.audit_logs_collection.insert_one(log_entry)
    
    def log_redirect_out(
        self,
        user_id: str,
        subid: str,
        url: str,
        params: Dict[str, Any]
    ):
        """
        Snapshot parameters BEFORE redirect to CPX
        
        Args:
            user_id: User/traffic ID
            subid: Tracking subid
            url: Full redirect URL
            params: All parameters being sent
        """
        log_entry = {
            "event_type": "cpx_redirect_out",
            "timestamp": datetime.utcnow(),
            "user_id": user_id,
            "subid": subid,
            "url": url,
            "params": params
        }
        result = self.audit_logs_collection.insert_one(log_entry)
        return str(result.inserted_id)
    
    def log_redirect_in(
        self,
        raw_query: Dict[str, Any],
        headers: Dict[str, str]
    ):
        """
        Snapshot parameters ON RETURN from CPX
        
        Args:
            raw_query: Query parameters from callback
            headers: Request headers
        """
        log_entry = {
            "event_type": "cpx_redirect_in",
            "timestamp": datetime.utcnow(),
            "raw_query": raw_query,
            "headers": headers
        }
        result = self.audit_logs_collection.insert_one(log_entry)
        return str(result.inserted_id)
    
    def verify_parameter_integrity(
        self,
        outgoing_subid: str,
        incoming_subid: str
    ) -> bool:
        """
        Verify that tracking parameters match between outgoing and incoming
        
        Args:
            outgoing_subid: Subid sent in redirect
            incoming_subid: Subid received in callback
            
        Returns:
            True if parameters match, False otherwise
        """
        if outgoing_subid != incoming_subid:
            # INVARIANT VIOLATION
            self._log_audit_event("parameter_integrity_violation", {
                "outgoing_subid": outgoing_subid,
                "incoming_subid": incoming_subid,
                "violation": "subid_mismatch"
            })
            
            # Create alert for kill switch
            self._create_alert(
                "subid_mismatch",
                "CRITICAL",
                f"Parameter integrity violation: {outgoing_subid} != {incoming_subid}"
            )
            return False
        
        return True
    
    def classify_screenout(
        self,
        duration_seconds: float
    ) -> str:
        """
        Classify screen-out based on duration
        
        Args:
            duration_seconds: Time from redirect to callback
            
        Returns:
            Screen-out type: IMMEDIATE_REJECT, SCREENER_FAIL, or QUALITY_REJECT
        """
        if duration_seconds < self.IMMEDIATE_REJECT_THRESHOLD:
            return "IMMEDIATE_REJECT"
        elif duration_seconds < self.SCREENER_FAIL_THRESHOLD:
            return "SCREENER_FAIL"
        else:
            return "QUALITY_REJECT"
    
    def analyze_screenout_patterns(
        self,
        lookback_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Analyze screen-out patterns to identify root causes
        
        Args:
            lookback_hours: Hours to look back for analysis
            
        Returns:
            Analysis report with breakdown by type
        """
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        
        # Get all terminated traffic records
        pipeline = [
            {
                "$match": {
                    "status": "TERMINATED",
                    "createdAt": {"$gte": cutoff}
                }
            },
            {
                "$group": {
                    "_id": "$screenout_type",
                    "count": {"$sum": 1},
                    "avg_duration": {"$avg": "$duration_seconds"}
                }
            }
        ]
        
        results = list(self.traffic_collection.aggregate(pipeline))
        
        # Calculate total and percentages
        total_screenouts = sum(r["count"] for r in results)
        
        analysis = {
            "total_screenouts": total_screenouts,
            "lookback_hours": lookback_hours,
            "by_type": {},
            "recommendations": []
        }
        
        for result in results:
            screenout_type = result["_id"]
            count = result["count"]
            percentage = (count / total_screenouts * 100) if total_screenouts > 0 else 0
            
            analysis["by_type"][screenout_type] = {
                "count": count,
                "percentage": percentage,
                "avg_duration_seconds": result["avg_duration"]
            }
        
        # Generate recommendations based on patterns
        immediate_pct = analysis["by_type"].get("IMMEDIATE_REJECT", {}).get("percentage", 0)
        screener_pct = analysis["by_type"].get("SCREENER_FAIL", {}).get("percentage", 0)
        
        if immediate_pct > 50:
            analysis["recommendations"].append("High immediate reject rate suggests geo/device/quota mismatch")
        if screener_pct > 50:
            analysis["recommendations"].append("High screener fail rate suggests demographic mismatch")
        
        return analysis
    
    def get_screenout_rate(
        self,
        last_n: int = 100
    ) -> float:
        """
        Calculate screen-out rate for last N traffic records
        
        Args:
            last_n: Number of recent records to analyze
            
        Returns:
            Screen-out rate as decimal (0.0 to 1.0)
        """
        records = list(
            self.traffic_collection.find({})
            .sort("createdAt", -1)
            .limit(last_n)
        )
        
        if not records:
            return 0.0
        
        terminated_count = sum(1 for r in records if r.get("status") == "TERMINATED")
        return terminated_count / len(records)
    
    def check_auto_pause_condition(self) -> Tuple[bool, Optional[str]]:
        """
        Check if auto-pause condition is met
        
        Returns:
            Tuple of (should_pause, reason)
        """
        screenout_rate = self.get_screenout_rate(100)
        
        if screenout_rate > self.SCREENOUT_RATE_THRESHOLD:
            reason = f"Screen-out rate {screenout_rate:.1%} exceeds threshold {self.SCREENOUT_RATE_THRESHOLD:.1%}"
            self._create_alert("high_screenout_rate", "CRITICAL", reason)
            return True, reason
        
        return False, None
    
    def analyze_time_of_day_patterns(
        self,
        lookback_days: int = 7
    ) -> Dict[str, Any]:
        """
        Analyze screen-out rates by hour of day to detect inventory issues
        
        Args:
            lookback_days: Days to look back
            
        Returns:
            Analysis by hour of day
        """
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        
        pipeline = [
            {
                "$match": {
                    "createdAt": {"$gte": cutoff}
                }
            },
            {
                "$addFields": {
                    "hour_of_day": {"$hour": "$createdAt"}
                }
            },
            {
                "$group": {
                    "_id": "$hour_of_day",
                    "total": {"$sum": 1},
                    "terminated": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "TERMINATED"]}, 1, 0]
                        }
                    }
                }
            },
            {
                "$sort": {"_id": 1}
            }
        ]
        
        results = list(self.traffic_collection.aggregate(pipeline))
        
        hourly_data = {}
        for result in results:
            hour = result["_id"]
            total = result["total"]
            terminated = result["terminated"]
            screenout_rate = (terminated / total) if total > 0 else 0
            
            hourly_data[hour] = {
                "total": total,
                "terminated": terminated,
                "screenout_rate": screenout_rate
            }
        
        return {
            "lookback_days": lookback_days,
            "hourly_data": hourly_data
        }
    
    def validate_postback(
        self,
        status: str,
        payout: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate postback consistency
        
        Args:
            status: Postback status
            payout: Payout amount
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # ASSERTION: If complete, must have payout
        if status == "complete" and payout <= 0:
            error = "Complete status but payout is zero or negative"
            self._log_audit_event("postback_validation_failed", {
                "status": status,
                "payout": payout,
                "error": error
            })
            return False, error
        
        return True, None
    
    def _log_audit_event(self, event_type: str, data: Dict[str, Any]):
        """Internal method to log audit events"""
        log_entry = {
            "event_type": event_type,
            "timestamp": datetime.utcnow(),
            **data
        }
        self.audit_logs_collection.insert_one(log_entry)
    
    def _create_alert(self, alert_type: str, severity: str, message: str):
        """Create an alert for monitoring"""
        alert = {
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "timestamp": datetime.utcnow(),
            "resolved": False
        }
        self.alerts_collection.insert_one(alert)
