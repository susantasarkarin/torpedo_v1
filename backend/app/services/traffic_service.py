"""
Traffic Service
Handles traffic record creation, batch processing, and survey assignment
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from bson import ObjectId


class TrafficService:
    """Service to manage traffic records and survey assignments"""
    
    def __init__(
        self,
        traffic_collection: Any,
        surveys_collection: Any,
        async_traffic_collection: Optional[Any] = None,
        async_surveys_collection: Optional[Any] = None
    ):
        """
        Initialize Traffic Service
        
        Args:
            traffic_collection: MongoDB collection for traffic records (Sync)
            surveys_collection: MongoDB collection for CPX surveys (Sync)
            async_traffic_collection: Motor collection for traffic records (Async)
            async_surveys_collection: Motor collection for CPX surveys (Async)
        """
        self.traffic_collection = traffic_collection
        self.surveys_collection = surveys_collection
        self.async_traffic_collection = async_traffic_collection
        self.async_surveys_collection = async_surveys_collection
    
    async def async_create_traffic_record(
        self,
        vendor_id: str,
        country_code: str,
        respondent_id: str,
        url: str = None,
        user_agent: str = None,
        params: Dict[str, Any] = None,
        client_ip: str = None,
        ip_source: str = None,
        device_fingerprint: str = None,
        fingerprint_source: str = None,
        fingerprint_components: Dict[str, Any] = None,
        email: str = None,
        profiling_data: Dict[str, Any] = None
    ) -> str:
        """Create a new traffic record (Asynchronous)"""
        try:
            traffic_record = {
                "vendorId": vendor_id,
                "countryCode": country_code,
                "respondentId": respondent_id,
                "status": "INCOMPLETE",
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
                "url": url,
                "userAgent": user_agent,
                "params": params or {},
                "clientIp": client_ip,
                "ipSource": ip_source,
                "deviceFingerprint": device_fingerprint,
                "fingerprintSource": fingerprint_source,
                "fingerprintComponents": fingerprint_components or {},
                "email": email,
                "profilingData": profiling_data or {},
                "assignedSurveyId": None,
                "redirectUrl": None,
                "outUrl": None,
            }
            
            # Use async collection if available, fallback to sync in thread
            if self.async_traffic_collection is not None:
                result = await self.async_traffic_collection.insert_one(traffic_record)
            else:
                import asyncio
                result = await asyncio.to_thread(self.traffic_collection.insert_one, traffic_record)
                
            object_id = str(result.inserted_id)
            print(f"✅ Created traffic record (ASYNC): {object_id}")
            return object_id
            
        except Exception as e:
            print(f"❌ Error creating traffic record (ASYNC): {e}")
            raise
    
    def create_traffic_record(
        self,
        vendor_id: str,
        country_code: str,
        respondent_id: str,
        url: str = None,
        user_agent: str = None,
        params: Dict[str, Any] = None,
        client_ip: str = None,
        ip_source: str = None,
        device_fingerprint: str = None,
        fingerprint_source: str = None,
        fingerprint_components: Dict[str, Any] = None,
        email: str = None,
        profiling_data: Dict[str, Any] = None
    ) -> str:
        """
        Create a new traffic record
        
        Args:
            vendor_id: Vendor ID (vid parameter)
            country_code: Country code (cc parameter)
            respondent_id: Respondent ID (rid parameter)
            url: Full URL that was accessed
            user_agent: Browser user agent
            params: All URL parameters
            client_ip: Client IP address for CPX targeting
            ip_source: Source of the IP (e.g., 'CF-Connecting-IP', 'X-Forwarded-For')
            device_fingerprint: Device fingerprint hash
            fingerprint_source: Source of the fingerprint (e.g., 'client', 'server')
            fingerprint_components: Components used to generate the fingerprint
            email: User's email address (mandatory)
            profiling_data: Optional user profiling payload (age/gender/etc)
            
        Returns:
            MongoDB ObjectId as string
        """
        try:
            traffic_record = {
                "vendorId": vendor_id,
                "countryCode": country_code,
                "respondentId": respondent_id,
                "status": "INCOMPLETE",
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
                "url": url,
                "userAgent": user_agent,
                "params": params or {},
                "clientIp": client_ip,
                "ipSource": ip_source,
                "deviceFingerprint": device_fingerprint,
                "fingerprintSource": fingerprint_source,
                "fingerprintComponents": fingerprint_components or {},
                "email": email,
                "profilingData": profiling_data or {},
                "assignedSurveyId": None,
                "redirectUrl": None,
                "outUrl": None,
            }
            
            result = self.traffic_collection.insert_one(traffic_record)
            object_id = str(result.inserted_id)
            
            print(f"✅ Created traffic record: {object_id} (vid={vendor_id}, cc={country_code}, rid={respondent_id})")
            return object_id
            
        except Exception as e:
            print(f"❌ Error creating traffic record: {e}")
            raise
    
    def get_new_traffic_batch(self, batch_size: int = 100) -> List[Dict[str, Any]]:
        """
        Get a batch of NEW traffic records
        
        Args:
            batch_size: Number of records to fetch (default: 100)
            
        Returns:
            List of traffic record dictionaries
        """
        try:
            records = list(
                self.traffic_collection.find({"status": "INCOMPLETE"})
                .limit(batch_size)
            )
            
            # Convert ObjectId to string for JSON serialization
            for record in records:
                record["_id"] = str(record["_id"])
            
            print(f"📋 Retrieved {len(records)} NEW traffic records")
            return records
            
        except Exception as e:
            print(f"❌ Error fetching traffic batch: {e}")
            return []
    
    async def async_assign_survey_to_traffic(
        self,
        traffic_id: str,
        survey_id: str,
        redirect_url: str
    ) -> bool:
        """Assign a survey to a traffic record (Asynchronous)"""
        try:
            update_fields = {
                "status": "INCOMPLETE",
                "assignedSurveyId": survey_id,
                "redirectUrl": redirect_url,
                "assignedAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
            }
            
            if self.async_traffic_collection is not None:
                result = await self.async_traffic_collection.update_one(
                    {"_id": ObjectId(traffic_id)},
                    {"$set": update_fields}
                )
            else:
                import asyncio
                result = await asyncio.to_thread(
                    self.traffic_collection.update_one,
                    {"_id": ObjectId(traffic_id)},
                    {"$set": update_fields}
                )
            
            return result.modified_count > 0
                
        except Exception as e:
            print(f"❌ Error assigning survey (ASYNC): {e}")
            return False

    def assign_survey_to_traffic(
        self,
        traffic_id: str,
        survey_id: str,
        redirect_url: str
    ) -> bool:
        """
        Assign a survey to a traffic record and update status to INCOMPLETE
        
        Args:
            traffic_id: Traffic record ObjectId
            survey_id: Survey ID being assigned
            redirect_url: Generated redirect URL
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.traffic_collection.update_one(
                {"_id": ObjectId(traffic_id)},
                {
                    "$set": {
                        "status": "INCOMPLETE",
                        "assignedSurveyId": survey_id,
                        "redirectUrl": redirect_url,
                        "assignedAt": datetime.utcnow(),
                        "updatedAt": datetime.utcnow(),
                    }
                }
            )
            
            if result.modified_count > 0:
                print(f"✅ Assigned survey {survey_id} to traffic {traffic_id}")
                return True
            else:
                print(f"⚠️ Traffic record {traffic_id} not found or already assigned")
                return False
                
        except Exception as e:
            print(f"❌ Error assigning survey to traffic: {e}")
            return False
    
    def batch_assign_surveys(
        self,
        survey_id: str,
        survey_url: str,
        client_id: str,
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """
        Assign a survey to a batch of NEW traffic records
        
        Args:
            survey_id: Survey ID to assign
            survey_url: Base survey URL
            client_id: Client ID for the survey
            batch_size: Number of records to process (default: 100)
            
        Returns:
            Dictionary with assignment statistics
        """
        try:
            # Get batch of NEW traffic records
            traffic_batch = self.get_new_traffic_batch(batch_size)
            
            if not traffic_batch:
                return {
                    "success": True,
                    "survey_id": survey_id,
                    "total_records": 0,
                    "assigned": 0,
                    "failed": 0,
                    "message": "No NEW traffic records available"
                }
            
            assigned_count = 0
            failed_count = 0
            redirect_urls = []
            
            for traffic in traffic_batch:
                try:
                    traffic_id = traffic["_id"]
                    country_code = traffic.get("countryCode", "")
                    respondent_id = traffic.get("respondentId", "")
                    
                    # Build redirect URL with traffic ObjectId embedded
                    # Format: https://survey.com/start?clientId=<clientId>-<trafficObjectId>&cc=<cc>&rid=<rid>
                    redirect_url = f"{survey_url}?clientId={client_id}-{traffic_id}&cc={country_code}&rid={respondent_id}"
                    
                    # Assign survey and update status
                    if self.assign_survey_to_traffic(traffic_id, survey_id, redirect_url):
                        assigned_count += 1
                        redirect_urls.append({
                            "traffic_id": traffic_id,
                            "redirect_url": redirect_url
                        })
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    print(f"❌ Error processing traffic record {traffic.get('_id')}: {e}")
                    failed_count += 1
            
            result = {
                "success": True,
                "survey_id": survey_id,
                "total_records": len(traffic_batch),
                "assigned": assigned_count,
                "failed": failed_count,
                "redirect_urls": redirect_urls[:10],  # Return first 10 for verification
                "message": f"Assigned {assigned_count} traffic records to survey {survey_id}"
            }
            
            print(f"✅ Batch assignment complete: {assigned_count} assigned, {failed_count} failed")
            return result
            
        except Exception as e:
            print(f"❌ Error in batch assignment: {e}")
            return {
                "success": False,
                "survey_id": survey_id,
                "total_records": 0,
                "assigned": 0,
                "failed": 0,
                "error": str(e)
            }
    
    def batch_assign_surveys_with_entry_links(
        self,
        survey_id: str,
        cpx_service: Any,
        client_id: str,
        batch_size: int = 100,
        href: str = ""
    ) -> Dict[str, Any]:
        """
        Assign a survey to a batch of NEW traffic records with dynamically generated entry links.
        Each respondent gets a unique entry_link with their respondent_id as ext_user_id.
        
        Args:
            survey_id: Survey ID to assign
            cpx_service: CPX service instance for generating entry links
            client_id: Client ID for the survey
            batch_size: Number of records to process (default: 100)
            href: The CPX click-tracking URL (click.cpx-research.com) to use for entry links
            
        Returns:
            Dictionary with assignment statistics
        """
        try:
            # Get batch of NEW traffic records
            traffic_batch = self.get_new_traffic_batch(batch_size)
            
            if not traffic_batch:
                return {
                    "success": True,
                    "survey_id": survey_id,
                    "total_records": 0,
                    "assigned": 0,
                    "failed": 0,
                    "message": "No NEW traffic records available"
                }
            
            assigned_count = 0
            failed_count = 0
            redirect_urls = []
            
            for traffic in traffic_batch:
                try:
                    traffic_id = traffic["_id"]
                    country_code = traffic.get("countryCode", "")
                    respondent_id = traffic.get("respondentId", "")
                    
                    # Generate unique entry link using CPX click-tracking URL (click.cpx-research.com)
                    # Use traffic_id (SFWID) as subid_1 so we can look up the record on postback callback
                    entry_link = cpx_service.generate_entry_link(
                        survey_id=survey_id,
                        respondent_id=traffic_id,  # Use SFWID as subid_1 for callback tracking
                        href=href  # Pass CPX click-tracking URL
                    )
                    
                    if not entry_link:
                        print(f"⚠️ No href available for survey {survey_id}, skipping traffic {traffic_id}")
                        failed_count += 1
                        continue
                    
                    # Use CPX entry link verbatim (no additional params)
                    redirect_url = entry_link
                    
                    # Assign survey and update status
                    if self.assign_survey_to_traffic(traffic_id, survey_id, redirect_url):
                        assigned_count += 1
                        redirect_urls.append({
                            "traffic_id": traffic_id,
                            "respondent_id": respondent_id,
                            "redirect_url": redirect_url
                        })
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    print(f"❌ Error processing traffic record {traffic.get('_id')}: {e}")
                    failed_count += 1
            
            result = {
                "success": True,
                "survey_id": survey_id,
                "total_records": len(traffic_batch),
                "assigned": assigned_count,
                "failed": failed_count,
                "redirect_urls": redirect_urls[:10],  # Return first 10 for verification
                "message": f"Assigned {assigned_count} traffic records to survey {survey_id} with unique entry links"
            }
            
            print(f"✅ Batch assignment with entry links complete: {assigned_count} assigned, {failed_count} failed")
            return result
            
        except Exception as e:
            print(f"❌ Error in batch assignment with entry links: {e}")
            return {
                "success": False,
                "survey_id": survey_id,
                "total_records": 0,
                "assigned": 0,
                "failed": 0,
                "error": str(e)
            }
    
    def update_traffic_status(
        self,
        traffic_id: str,
        status: str,
        redirect_url: str = None,
        out_url: str = None
    ) -> bool:
        """
        Update traffic record status
        
        Args:
            traffic_id: Traffic record ObjectId
            status: New status (complete, terminated, quotafull, etc.)
            redirect_url: Optional redirect URL to store (callback URL from survey)
            out_url: Optional out URL (vendor redirect URL where respondent is sent post-survey)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            update_data = {
                "status": status.upper(),
                "updatedAt": datetime.utcnow(),
            }
            
            if redirect_url:
                update_data["redirectUrl"] = redirect_url
            
            if out_url:
                update_data["outUrl"] = out_url
            
            if status.upper() == "COMPLETE":
                update_data["completedAt"] = datetime.utcnow()
            
            result = self.traffic_collection.update_one(
                {"_id": ObjectId(traffic_id)},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                print(f"✅ Updated traffic {traffic_id} status to {status}")
                return True
            else:
                print(f"⚠️ Traffic record {traffic_id} not found")
                return False
                
        except Exception as e:
            print(f"❌ Error updating traffic status: {e}")
            return False
    
    def _normalize_status(self, status: str) -> str:
        """
        Normalize raw status values to display categories:
        - Complete
        - Incomplete
        - Quota Full
        - Terminate
        - Other (merged from other statuses)
        """
        if not status:
            return "Incomplete"
        
        status_lower = str(status).lower()
        
        # Map to display categories
        if "complete" in status_lower and "incomplete" not in status_lower:
            return "Complete"
        elif "quota" in status_lower or "quotafull" in status_lower or "overquota" in status_lower:
            return "Quota Full"
        elif "terminate" in status_lower or "screenout" in status_lower or "term" in status_lower or status_lower == "out":
            return "Terminate"
        elif "incomplete" in status_lower:
            return "Incomplete"
        else:
            # For everything else, default to Incomplete
            return "Incomplete"

    def _is_complete_status(self, status: Any) -> bool:
        """Check whether a raw status value represents a complete."""
        status_lower = str(status or "").lower()
        return "complete" in status_lower and "incomplete" not in status_lower

    def _normalize_survey_source(self, source: Any) -> str:
        """Normalize survey source to CPX/CINT/UNKNOWN buckets."""
        source_upper = str(source or "").strip().upper()
        if source_upper == "CPX":
            return "CPX"
        if source_upper.startswith("CINT"):
            return "CINT"
        return "UNKNOWN"

    def _safe_parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse mixed datetime values safely (datetime, iso string, unix ts)."""
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
            return value

        if isinstance(value, (int, float)):
            ts = float(value)
            # milliseconds epoch support
            if ts > 1e12:
                ts /= 1000.0
            try:
                return datetime.utcfromtimestamp(ts)
            except Exception:
                return None

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None

            candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                return parsed
            except Exception:
                pass

            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y, %I:%M:%S %p", "%m/%d/%Y %I:%M:%S %p"):
                try:
                    return datetime.strptime(raw, fmt)
                except Exception:
                    continue

        return None

    def get_dashboard_traffic_stats(
        self,
        days: int = 7,
        survey_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build dashboard-friendly traffic stats:
        - by_status + total
        - daily clicks/incomplete/complete/terminate/quota_full for N days
        - completes split by survey source (CPX vs CINT)
        - daily IR% split by survey source (CPX vs CINT), where IR = complete/entrants
        - top country click distribution
        """
        try:
            window_days = max(1, min(int(days or 7), 30))
            now_utc = datetime.utcnow()
            start_day = (now_utc - timedelta(days=window_days - 1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            query: Dict[str, Any] = {}
            if survey_id:
                query["assignedSurveyId"] = survey_id

            # PERF: Filter by date window at DB level to avoid scanning entire collection
            query["createdAt"] = {"$gte": start_day}

            # Initialize day buckets in ascending order
            day_keys: List[str] = []
            day_buckets: Dict[str, Dict[str, Any]] = {}
            for offset in range(window_days):
                day = start_day + timedelta(days=offset)
                key = day.strftime("%Y-%m-%d")
                day_keys.append(key)
                day_buckets[key] = {
                    "date": key,
                    "clicks": 0,
                    "complete": 0,
                    "incomplete": 0,
                    "terminate": 0,
                    "quota_full": 0,
                    "cpx_entrants": 0,
                    "cpx_complete": 0,
                    "cint_entrants": 0,
                    "cint_complete": 0,
                    "outs": 0,
                    "active_users": set(),
                }

            by_status = {"Complete": 0, "Incomplete": 0, "Quota Full": 0, "Terminate": 0}
            total = 0
            completes_by_source = {"CPX": 0, "CINT": 0, "UNKNOWN": 0}
            entrants_by_source = {"CPX": 0, "CINT": 0}
            country_clicks: Dict[str, int] = {}
            active_users_total = set()

            by_status_api_true  = {"Complete": 0, "Incomplete": 0, "Quota Full": 0, "Terminate": 0}
            by_status_api_false = {"Complete": 0, "Incomplete": 0, "Quota Full": 0, "Terminate": 0}
            total_api_true = 0
            total_api_false = 0

            # =========================================================================
            # PERF: Python loop with projection + date filter (createdAt >= start_day)
            # Scans ~31K records (7-day window) vs 194K+ (full collection)
            # =========================================================================
            projection = {
                "status": 1,
                "createdAt": 1,
                "respondentId": 1,
                "countryCode": 1,
                "surveySource": 1,
                "params.api": 1,
            }

            # Pre-build status/source lookup dicts for fast normalization
            _status_map = {}
            _source_map = {}

            for record in self.traffic_collection.find(query, projection):
                raw_status = record.get("status", "")
                # Inline status normalization (avoid method call overhead)
                ls = raw_status.lower().strip() if raw_status else ""
                if ls not in _status_map:
                    _status_map[ls] = self._normalize_status(raw_status)
                normalized_status = _status_map[ls]

                raw_source = record.get("surveySource") or ""
                if raw_source not in _source_map:
                    _source_map[raw_source] = self._normalize_survey_source(raw_source)
                source_bucket = _source_map[raw_source]

                # API flag check
                params_doc = record.get("params") or {}
                api_val = params_doc.get("api", "")
                is_api_true = str(api_val).strip().lower() != "false" if api_val else True

                by_status[normalized_status] = by_status.get(normalized_status, 0) + 1
                if is_api_true:
                    by_status_api_true[normalized_status] = by_status_api_true.get(normalized_status, 0) + 1
                    total_api_true += 1
                else:
                    by_status_api_false[normalized_status] = by_status_api_false.get(normalized_status, 0) + 1
                    total_api_false += 1
                total += 1

                # Use createdAt directly (already a datetime from MongoDB)
                created_dt = record.get("createdAt")
                if created_dt and isinstance(created_dt, datetime):
                    day_key = created_dt.strftime("%Y-%m-%d")
                    if day_key in day_buckets:
                        bucket = day_buckets[day_key]
                        bucket["clicks"] += 1

                        user_key = record.get("respondentId") or str(record.get("_id"))
                        if user_key:
                            bucket["active_users"].add(str(user_key))
                            active_users_total.add(str(user_key))

                        cc = str(record.get("countryCode") or "").strip().upper() or "NA"
                        country_clicks[cc] = country_clicks.get(cc, 0) + 1

                        if source_bucket == "CPX":
                            bucket["cpx_entrants"] += 1
                            entrants_by_source["CPX"] += 1
                        elif source_bucket == "CINT":
                            bucket["cint_entrants"] += 1
                            entrants_by_source["CINT"] += 1

                        if normalized_status == "Complete":
                            bucket["complete"] += 1
                            if source_bucket == "CPX":
                                bucket["cpx_complete"] += 1
                            elif source_bucket == "CINT":
                                bucket["cint_complete"] += 1
                        elif normalized_status == "Incomplete":
                            bucket["incomplete"] += 1
                        elif normalized_status == "Terminate":
                            bucket["terminate"] += 1
                        elif normalized_status == "Quota Full":
                            bucket["quota_full"] += 1

                if self._is_complete_status(raw_status):
                    if source_bucket == "CPX":
                        completes_by_source["CPX"] += 1
                    elif source_bucket == "CINT":
                        completes_by_source["CINT"] += 1
                    else:
                        completes_by_source["UNKNOWN"] += 1

            daily = []
            for key in day_keys:
                bucket = day_buckets[key]
                clicks = int(bucket["clicks"])
                complete = int(bucket["complete"])
                incomplete = int(bucket["incomplete"])
                terminate = int(bucket["terminate"])
                quota_full = int(bucket["quota_full"])
                cpx_entrants = int(bucket["cpx_entrants"])
                cpx_complete = int(bucket["cpx_complete"])
                cint_entrants = int(bucket["cint_entrants"])
                cint_complete = int(bucket["cint_complete"])
                ir_cpx = round((cpx_complete / cpx_entrants) * 100, 2) if cpx_entrants > 0 else 0.0
                ir_cint = round((cint_complete / cint_entrants) * 100, 2) if cint_entrants > 0 else 0.0
                daily.append({
                    "date": key,
                    "clicks": clicks,
                    "complete": complete,
                    "incomplete": incomplete,
                    "terminate": terminate,
                    "quota_full": quota_full,
                    "cpx_entrants": cpx_entrants,
                    "cpx_complete": cpx_complete,
                    "cint_entrants": cint_entrants,
                    "cint_complete": cint_complete,
                    "ir_cpx": ir_cpx,
                    "ir_cint": ir_cint,
                    # Backward-compatible aliases used by current UI cards.
                    "completes": complete,
                    "outs": max(0, clicks - complete),
                    "active_users": len(bucket["active_users"]),
                })

            top_countries = [
                {"code": code, "clicks": clicks}
                for code, clicks in sorted(country_clicks.items(), key=lambda item: item[1], reverse=True)[:12]
            ]

            ir_by_source = {
                "CPX": round((completes_by_source["CPX"] / entrants_by_source["CPX"]) * 100, 2)
                if entrants_by_source["CPX"] > 0 else 0.0,
                "CINT": round((completes_by_source["CINT"] / entrants_by_source["CINT"]) * 100, 2)
                if entrants_by_source["CINT"] > 0 else 0.0,
            }

            return {
                "total": total,
                "by_status": by_status,
                "by_status_api_true": by_status_api_true,
                "by_status_api_false": by_status_api_false,
                "total_api_true": total_api_true,
                "total_api_false": total_api_false,
                "daily": daily,
                "active_users_total": len(active_users_total),
                "completes_by_source": completes_by_source,
                "ir_by_source": ir_by_source,
                "country_clicks": top_countries,
                "generated_at": now_utc.isoformat(),
            }
        except Exception as e:
            print(f"❌ Error building dashboard traffic stats: {e}")
            _empty_status = {"Complete": 0, "Incomplete": 0, "Quota Full": 0, "Terminate": 0}
            return {
                "total": 0,
                "by_status": dict(_empty_status),
                "by_status_api_true": dict(_empty_status),
                "by_status_api_false": dict(_empty_status),
                "total_api_true": 0,
                "total_api_false": 0,
                "daily": [],
                "active_users_total": 0,
                "completes_by_source": {"CPX": 0, "CINT": 0, "UNKNOWN": 0},
                "ir_by_source": {"CPX": 0.0, "CINT": 0.0},
                "country_clicks": [],
                "generated_at": datetime.utcnow().isoformat(),
            }

    def get_project_traffic_stats(self, pid: str) -> Dict[str, Any]:
        """
        Get traffic stats for a project by its survey number (PID).
        Filters: params.api = "false" AND params.pid = pid
        Returns completes, total_started, terminates, quota_full, median_loi, incidence_rate.
        """
        import statistics as _stats
        try:
            projection = {"status": 1, "createdAt": 1, "completedAt": 1, "params": 1}
            total = 0
            completes = 0
            terminates = 0
            quota_full = 0
            loi_values = []

            for record in self.traffic_collection.find(
                {"params.api": "false", "params.pid": str(pid)},
                projection,
            ):
                raw_status = record.get("status", "")
                normalized = self._normalize_status(raw_status)
                total += 1
                if normalized == "Complete":
                    completes += 1
                    created = self._safe_parse_datetime(record.get("createdAt"))
                    completed_ = self._safe_parse_datetime(record.get("completedAt"))
                    if created and completed_:
                        secs = (completed_ - created).total_seconds()
                        if secs > 0:
                            loi_values.append(secs / 60.0)
                elif normalized == "Terminate":
                    terminates += 1
                elif normalized == "Quota Full":
                    quota_full += 1

            median_loi = round(_stats.median(loi_values), 1) if loi_values else None
            ir = round(completes / (completes + terminates) * 100, 1) if (completes + terminates) > 0 else 0.0
            return {
                "total_started": total,
                "completes": completes,
                "terminates": terminates,
                "quota_full": quota_full,
                "median_loi": median_loi,
                "incidence_rate": ir,
            }
        except Exception as e:
            print(f"❌ Error getting project traffic stats for pid={pid}: {e}")
            return {
                "total_started": 0,
                "completes": 0,
                "terminates": 0,
                "quota_full": 0,
                "median_loi": None,
                "incidence_rate": 0.0,
            }

    def get_traffic_stats(self, survey_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get traffic statistics by consolidated status (Complete, Incomplete, Quota Full)
        Optionally filtered by survey_id
        
        Args:
            survey_id: Optional survey ID to filter stats
            
        Returns:
            Dictionary with counts by consolidated status
        """
        try:
            # Build match stage for filtering
            match_stage = {}
            if survey_id:
                match_stage["assignedSurveyId"] = survey_id
            
            pipeline = []
            
            # Add match stage if filtering
            if match_stage:
                pipeline.append({"$match": match_stage})
            
            # Group by status
            pipeline.append({
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }
            })
            
            results = list(self.traffic_collection.aggregate(pipeline, maxTimeMS=8000))
            
            # Consolidate statuses
            by_status = {}
            total = 0

            for r in results:
                raw_status = r["_id"]
                count = r["count"]
                normalized_status = self._normalize_status(raw_status)
                
                by_status[normalized_status] = by_status.get(normalized_status, 0) + count
                total += count
            
            # Ensure all categories are present (even if 0)
            display_statuses = ["Complete", "Incomplete", "Quota Full", "Terminate"]
            for status in display_statuses:
                if status not in by_status:
                    by_status[status] = 0
            
            stats = {
                "total": total,
                "by_status": by_status
            }
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting traffic stats: {e}")
            return {"total": 0, "by_status": {"Complete": 0, "Incomplete": 0, "Quota Full": 0}}
    
    def get_all_surveys_traffic_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Get aggregated traffic statistics (clicks and completes) for all surveys.
        
        Returns:
            Dictionary mapping survey_id -> {"clicks": int, "completes": int}
        """
        try:
            # Aggregate by survey_id and status
            pipeline = [
                {
                    "$match": {
                        "assignedSurveyId": {"$exists": True, "$ne": None}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "survey_id": "$assignedSurveyId",
                            "status": "$status"
                        },
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = list(self.traffic_collection.aggregate(pipeline, maxTimeMS=10000))
            
            # Build stats dictionary
            stats_by_survey = {}
            for r in results:
                survey_id = r["_id"]["survey_id"]
                status = r["_id"]["status"]
                count = r["count"]
                
                if survey_id not in stats_by_survey:
                    stats_by_survey[survey_id] = {"clicks": 0, "completes": 0}
                
                # Count all records as clicks (any status means they clicked)
                stats_by_survey[survey_id]["clicks"] += count
                
                # Only count COMPLETE status as completes
                if status == "COMPLETE":
                    stats_by_survey[survey_id]["completes"] += count
            
            return stats_by_survey
            
        except Exception as e:
            print(f"❌ Error getting all surveys traffic stats: {e}")
            return {}
    
    def list_traffic_records(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        search: Optional[str] = None,
        survey_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List traffic records with pagination and optional filters
        
        Args:
            page: Page number (1-indexed)
            page_size: Records per page
            status: Filter by normalized status (Complete, Incomplete, Quota Full)
            search: Search in vendorId, respondentId, or countryCode
            survey_id: Filter by assigned survey ID
            
        Returns:
            Dictionary with records and pagination info
        """
        def _serialize_datetime(value):
            """Safely serialize datetime or string to ISO format"""
            if value is None:
                return None
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, str):
                return value  # Already a string, return as-is
            return str(value)
        
        def _normalize_status_for_filter(normalized_status: str) -> List[str]:
            """Convert normalized display status back to raw database statuses for filtering"""
            if not normalized_status:
                return []
            
            status_lower = normalized_status.lower()
            
            if "complete" in status_lower and "incomplete" not in status_lower:
                # Complete - match anything with "complete" but not "incomplete"
                return ["complete", "COMPLETE"]
            elif "quota" in status_lower:
                # Quota Full - match quota-related statuses
                return ["quotafull", "QUOTAFULL", "QUOTA_FULL", "quota_full", "overquota", "OVERQUOTA"]
            elif "incomplete" in status_lower:
                # Incomplete - match incomplete and merged statuses
                return ["incomplete", "INCOMPLETE", 
                       "CPX_TERMINATED_CINT_FALLBACK",
                       "CPX_FALLBACK", "fallback", "FALLBACK"]
            elif "terminate" in status_lower:
                # Terminate - match all termination statuses
                return ["terminated", "TERMINATED", "screenout", "SCREENOUT", "out", "OUT", 
                       "quality_terminate", "QUALITY_TERM", "TERMINATE", "terminate"]
            
            return []
        
        try:
            # Build query
            query = {}
            
            if status:
                # Convert normalized status to raw database status values
                raw_statuses = _normalize_status_for_filter(status)
                if raw_statuses:
                    query["status"] = {"$in": raw_statuses}
            
            if survey_id:
                query["assignedSurveyId"] = survey_id
            
            if search:
                # Search across multiple fields
                query["$or"] = [
                    {"vendorId": {"$regex": search, "$options": "i"}},
                    {"respondentId": {"$regex": search, "$options": "i"}},
                    {"countryCode": {"$regex": search, "$options": "i"}},
                    {"assignedSurveyId": {"$regex": search, "$options": "i"}},
                ]
            
            # Use $facet aggregation to get count + records in one round-trip with maxTimeMS
            MAX_TIME_MS = 10000
            skip = (page - 1) * page_size

            pipeline = [{"$match": query}]
            pipeline.append({
                "$facet": {
                    "total": [{"$count": "count"}],
                    "records": [
                        {"$sort": {"_id": -1}},
                        {"$skip": skip},
                        {"$limit": page_size},
                    ]
                }
            })
            facet_result = list(self.traffic_collection.aggregate(pipeline, maxTimeMS=MAX_TIME_MS))

            if facet_result:
                total_count = (facet_result[0].get("total") or [{}])[0].get("count", 0)
                records = facet_result[0].get("records", [])
            else:
                total_count = 0
                records = []

            total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
            
            # Serialize for JSON response - handle both old and new schema
            serialized_records = []
            for record in records:
                # Get createdAt, falling back to timestamp for old records
                created_at = record.get("createdAt") or record.get("timestamp")
                raw_status = record.get("status", "")
                
                serialized = {
                    "_id": str(record.get("_id", "")),
                    "vendorId": record.get("vendorId", ""),
                    "countryCode": record.get("countryCode", ""),
                    "respondentId": record.get("respondentId", ""),
                    "status": self._normalize_status(raw_status),
                    "assignedSurveyId": record.get("assignedSurveyId"),
                    "redirectUrl": record.get("redirectUrl"),
                    "outUrl": record.get("outUrl"),
                    "cpxCallbackUrl": record.get("cpxCallbackUrl"),
                    # Cint-specific fields
                    "surveySource": record.get("surveySource"),
                    "currentCintLink": record.get("currentCintLink"),
                    "currentCintSurveyId": record.get("currentCintSurveyId"),
                    "cintCallbackUrl": record.get("cintCallbackUrl"),
                    "cint_hashed_pid": record.get("cint_hashed_pid"),
                    "cint_mid": record.get("cint_mid"),
                    "cint_revenue": record.get("cint_revenue"),
                    "cint_profiling_params": record.get("cint_profiling_params", {}),
                    "profilingData": record.get("profilingData", {}),
                    # Timestamps
                    "createdAt": _serialize_datetime(created_at),
                    "updatedAt": _serialize_datetime(record.get("updatedAt")),
                    "assignedAt": _serialize_datetime(record.get("assignedAt")),
                    "completedAt": _serialize_datetime(record.get("completedAt")),
                    "params": record.get("params", {}),
                }
                serialized_records.append(serialized)
            
            return {
                "records": serialized_records,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total_count,
                    "total_pages": total_pages,
                }
            }
            
        except Exception as e:
            print(f"❌ Error listing traffic records: {e}")
            return {
                "records": [],
                "pagination": {"page": page, "page_size": page_size, "total": 0, "total_pages": 0}
            }
