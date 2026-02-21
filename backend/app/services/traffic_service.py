"""
Traffic Service
Handles traffic record creation, batch processing, and survey assignment
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
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
        email: str = None
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
        email: str = None
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
    
    def get_traffic_stats(self, survey_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get traffic statistics by status, optionally filtered by survey_id
        
        Args:
            survey_id: Optional survey ID to filter stats
            
        Returns:
            Dictionary with counts by status
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
            
            results = list(self.traffic_collection.aggregate(pipeline))
            
            stats = {
                "total": sum(r["count"] for r in results),
                "by_status": {r["_id"]: r["count"] for r in results}
            }
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting traffic stats: {e}")
            return {"total": 0, "by_status": {}}
    
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
            
            results = list(self.traffic_collection.aggregate(pipeline))
            
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
            status: Filter by status (NEW, INCOMPLETE, COMPLETE, etc.)
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
        
        try:
            # Build query
            query = {}
            
            if status:
                # Handle both uppercase and lowercase status values in the database
                status_upper = status.upper()
                status_lower = status.lower()
                query["status"] = {"$in": [status_upper, status_lower, status]}
            
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
            
            # Get total count
            total_count = self.traffic_collection.count_documents(query)
            
            # Calculate pagination
            skip = (page - 1) * page_size
            total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
            
            # Fetch records - sort by createdAt if exists, fall back to _id for old records
            records = list(
                self.traffic_collection.find(query)
                .sort([("createdAt", -1), ("timestamp", -1), ("_id", -1)])
                .skip(skip)
                .limit(page_size)
            )
            
            # Serialize for JSON response - handle both old and new schema
            serialized_records = []
            for record in records:
                # Get createdAt, falling back to timestamp for old records
                created_at = record.get("createdAt") or record.get("timestamp")
                
                serialized = {
                    "_id": str(record.get("_id", "")),
                    "vendorId": record.get("vendorId", ""),
                    "countryCode": record.get("countryCode", ""),
                    "respondentId": record.get("respondentId", ""),
                    "status": record.get("status", "").upper() if record.get("status") else "",
                    "assignedSurveyId": record.get("assignedSurveyId"),
                    "redirectUrl": record.get("redirectUrl"),
                    "outUrl": record.get("outUrl"),
                    "cpxCallbackUrl": record.get("cpxCallbackUrl"),
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
