"""
ACTIVITY FEED
=============

Centralized activity logging and feed system for team collaboration.

Features:
- Log all lead and campaign actions
- User activity timeline
- Team activity feed
- Filtered activity views
- Real-time activity tracking
- Activity analytics

Usage:
    from activity.feed import ActivityFeed
    
    feed = ActivityFeed()
    
    # Log action
    feed.log_action(
        user_id="user_123",
        action="lead_assigned",
        resource="lead",
        resource_id="lead_456",
        details={"assigned_to": "user_789"}
    )
    
    # Get activity
    user_activity = feed.get_user_activity("user_123", limit=50)
    team_activity = feed.get_team_activity("team_abc", limit=100)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Literal
from pymongo import MongoClient, DESCENDING
from pydantic import BaseModel, Field
from bson import ObjectId
import os

logger = logging.getLogger(__name__)

# Action types
ActionType = Literal[
    # Lead actions
    "lead_created",
    "lead_updated",
    "lead_assigned",
    "lead_enriched",
    "lead_contacted",
    "lead_replied",
    "lead_converted",
    "lead_archived",
    
    # Campaign actions
    "campaign_created",
    "campaign_started",
    "campaign_paused",
    "campaign_resumed",
    "campaign_completed",
    "campaign_archived",
    
    # Email actions
    "email_sent",
    "email_opened",
    "email_clicked",
    "email_replied",
    "email_bounced",
    
    # RFQ actions
    "rfq_created",
    "rfq_quoted",
    "rfq_won",
    "rfq_lost",
    
    # Team actions
    "team_member_added",
    "team_member_removed",
    "team_settings_updated",
    
    # Other
    "note_added",
    "file_uploaded",
    "task_created",
    "task_completed"
]

# Resource types
ResourceType = Literal[
    "lead",
    "campaign",
    "email",
    "rfq",
    "team",
    "user",
    "note",
    "file",
    "task"
]


class ActivityEntry(BaseModel):
    """Single activity entry"""
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    
    # Who & What
    user_id: str = Field(..., description="User who performed the action")
    user_name: Optional[str] = None
    action: ActionType
    
    # Resource
    resource: ResourceType
    resource_id: str
    resource_name: Optional[str] = None
    
    # Context
    team_id: Optional[str] = None
    campaign_id: Optional[str] = None
    
    # Details
    details: Dict = Field(default_factory=dict, description="Action-specific details")
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class ActivityFeed:
    """
    Activity logging and feed management
    """
    
    def __init__(self, mongo_uri: Optional[str] = None):
        """
        Initialize activity feed
        
        Args:
            mongo_uri: MongoDB connection string
        """
        if not mongo_uri:
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        
        client = MongoClient(mongo_uri)
        self.db = client['email_automation']
        self.activities = self.db['activities']
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes for efficient querying"""
        try:
            # Primary indexes
            self.activities.create_index([("user_id", 1), ("timestamp", DESCENDING)])
            self.activities.create_index([("team_id", 1), ("timestamp", DESCENDING)])
            self.activities.create_index([("resource", 1), ("resource_id", 1), ("timestamp", DESCENDING)])
            self.activities.create_index([("action", 1), ("timestamp", DESCENDING)])
            self.activities.create_index([("campaign_id", 1), ("timestamp", DESCENDING)])
            
            # Compound indexes
            self.activities.create_index([("team_id", 1), ("action", 1), ("timestamp", DESCENDING)])
            self.activities.create_index([("user_id", 1), ("resource", 1), ("timestamp", DESCENDING)])
            
            logger.info("Activity feed indexes created")
        except Exception as e:
            logger.error(f"Error creating activity feed indexes: {e}")
    
    def log_action(
        self,
        user_id: str,
        action: ActionType,
        resource: ResourceType,
        resource_id: str,
        details: Optional[Dict] = None,
        user_name: Optional[str] = None,
        resource_name: Optional[str] = None,
        team_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """
        Log an activity action
        
        Args:
            user_id: User who performed action
            action: Action type
            resource: Resource type
            resource_id: Resource identifier
            details: Additional details
            user_name: User's display name
            resource_name: Resource display name
            team_id: Team context
            campaign_id: Campaign context
            ip_address: User's IP address
            user_agent: User's browser/client
            
        Returns:
            Activity entry ID
        """
        entry = ActivityEntry(
            user_id=user_id,
            user_name=user_name,
            action=action,
            resource=resource,
            resource_id=resource_id,
            resource_name=resource_name,
            team_id=team_id,
            campaign_id=campaign_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        result = self.activities.insert_one(entry.dict(exclude={"id"}))
        
        logger.info(
            f"Activity logged: {user_id} performed {action} on {resource} {resource_id}"
        )
        
        return str(result.inserted_id)
    
    def get_user_activity(
        self,
        user_id: str,
        limit: int = 100,
        skip: int = 0,
        action_filter: Optional[List[ActionType]] = None,
        resource_filter: Optional[List[ResourceType]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Get activity feed for a specific user
        
        Args:
            user_id: User identifier
            limit: Maximum entries to return
            skip: Number of entries to skip (pagination)
            action_filter: Filter by specific actions
            resource_filter: Filter by specific resources
            start_date: Filter from this date
            end_date: Filter to this date
            
        Returns:
            List of activity entries
        """
        query = {"user_id": user_id}
        
        # Apply filters
        if action_filter:
            query["action"] = {"$in": action_filter}
        
        if resource_filter:
            query["resource"] = {"$in": resource_filter}
        
        if start_date or end_date:
            query["timestamp"] = {}
            if start_date:
                query["timestamp"]["$gte"] = start_date
            if end_date:
                query["timestamp"]["$lte"] = end_date
        
        activities = list(
            self.activities.find(query)
            .sort("timestamp", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for activity in activities:
            activity["_id"] = str(activity["_id"])
        
        return activities
    
    def get_team_activity(
        self,
        team_id: str,
        limit: int = 100,
        skip: int = 0,
        action_filter: Optional[List[ActionType]] = None,
        resource_filter: Optional[List[ResourceType]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Get activity feed for a team
        
        Args:
            team_id: Team identifier
            limit: Maximum entries to return
            skip: Number of entries to skip
            action_filter: Filter by specific actions
            resource_filter: Filter by specific resources
            start_date: Filter from this date
            end_date: Filter to this date
            
        Returns:
            List of activity entries
        """
        query = {"team_id": team_id}
        
        # Apply filters (same as user activity)
        if action_filter:
            query["action"] = {"$in": action_filter}
        
        if resource_filter:
            query["resource"] = {"$in": resource_filter}
        
        if start_date or end_date:
            query["timestamp"] = {}
            if start_date:
                query["timestamp"]["$gte"] = start_date
            if end_date:
                query["timestamp"]["$lte"] = end_date
        
        activities = list(
            self.activities.find(query)
            .sort("timestamp", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for activity in activities:
            activity["_id"] = str(activity["_id"])
        
        return activities
    
    def get_resource_activity(
        self,
        resource: ResourceType,
        resource_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get all activity for a specific resource
        
        Args:
            resource: Resource type
            resource_id: Resource identifier
            limit: Maximum entries to return
            
        Returns:
            List of activity entries
        """
        activities = list(
            self.activities.find({
                "resource": resource,
                "resource_id": resource_id
            })
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for activity in activities:
            activity["_id"] = str(activity["_id"])
        
        return activities
    
    def get_campaign_activity(
        self,
        campaign_id: str,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get all activity related to a campaign
        
        Args:
            campaign_id: Campaign identifier
            limit: Maximum entries to return
            
        Returns:
            List of activity entries
        """
        activities = list(
            self.activities.find({"campaign_id": campaign_id})
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for activity in activities:
            activity["_id"] = str(activity["_id"])
        
        return activities
    
    def get_recent_activity(
        self,
        hours: int = 24,
        limit: int = 100,
        team_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Get recent activity across the system
        
        Args:
            hours: Look back this many hours
            limit: Maximum entries to return
            team_id: Optional team filter
            
        Returns:
            List of activity entries
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query = {"timestamp": {"$gte": cutoff}}
        
        if team_id:
            query["team_id"] = team_id
        
        activities = list(
            self.activities.find(query)
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        
        # Convert ObjectId to string
        for activity in activities:
            activity["_id"] = str(activity["_id"])
        
        return activities
    
    def get_activity_stats(
        self,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        Get activity statistics
        
        Args:
            user_id: Filter by user
            team_id: Filter by team
            start_date: Start of date range
            end_date: End of date range
            
        Returns:
            Dictionary with activity statistics
        """
        query = {}
        
        if user_id:
            query["user_id"] = user_id
        
        if team_id:
            query["team_id"] = team_id
        
        if start_date or end_date:
            query["timestamp"] = {}
            if start_date:
                query["timestamp"]["$gte"] = start_date
            if end_date:
                query["timestamp"]["$lte"] = end_date
        
        # Total count
        total = self.activities.count_documents(query)
        
        # By action type
        action_pipeline = [
            {"$match": query},
            {"$group": {"_id": "$action", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        by_action = {
            item["_id"]: item["count"]
            for item in self.activities.aggregate(action_pipeline)
        }
        
        # By resource type
        resource_pipeline = [
            {"$match": query},
            {"$group": {"_id": "$resource", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        by_resource = {
            item["_id"]: item["count"]
            for item in self.activities.aggregate(resource_pipeline)
        }
        
        # By user (if team filter)
        by_user = {}
        if team_id:
            user_pipeline = [
                {"$match": query},
                {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            by_user = {
                item["_id"]: item["count"]
                for item in self.activities.aggregate(user_pipeline)
            }
        
        return {
            "total": total,
            "by_action": by_action,
            "by_resource": by_resource,
            "by_user": by_user,
            "query": query
        }
    
    def delete_old_activities(self, days: int = 90) -> int:
        """
        Delete activities older than specified days
        
        Args:
            days: Delete activities older than this many days
            
        Returns:
            Number of deleted activities
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = self.activities.delete_many({
            "timestamp": {"$lt": cutoff}
        })
        
        logger.info(f"Deleted {result.deleted_count} activities older than {days} days")
        return result.deleted_count
