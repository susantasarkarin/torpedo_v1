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
    ):
        """
        Initialize Traffic Service
        
        Args:
            traffic_collection: MongoDB collection for traffic records
            surveys_collection: MongoDB collection for CPX surveys
        """
        self.traffic_collection = traffic_collection
        self.surveys_collection = surveys_collection
    
    def create_traffic_record(
        self,
        vendor_id: str,
        country_code: str,
        respondent_id: str,
        url: str = None,
        user_agent: str = None,
        params: Dict[str, Any] = None
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
            
        Returns:
            MongoDB ObjectId as string
        """
        try:
            traffic_record = {
                "vendorId": vendor_id,
                "countryCode": country_code,
                "respondentId": respondent_id,
                "status": "NEW",
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
                "url": url,
                "userAgent": user_agent,
                "params": params or {},
                "assignedSurveyId": None,
                "redirectUrl": None,
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
                self.traffic_collection.find({"status": "NEW"})
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
    
    def update_traffic_status(
        self,
        traffic_id: str,
        status: str,
        redirect_url: str = None
    ) -> bool:
        """
        Update traffic record status
        
        Args:
            traffic_id: Traffic record ObjectId
            status: New status (complete, terminated, quotafull, etc.)
            redirect_url: Optional redirect URL to store
            
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
    
    def get_traffic_stats(self) -> Dict[str, Any]:
        """
        Get traffic statistics by status
        
        Returns:
            Dictionary with counts by status
        """
        try:
            pipeline = [
                {
                    "$group": {
                        "_id": "$status",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = list(self.traffic_collection.aggregate(pipeline))
            
            stats = {
                "total": sum(r["count"] for r in results),
                "by_status": {r["_id"]: r["count"] for r in results}
            }
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting traffic stats: {e}")
            return {"total": 0, "by_status": {}}
