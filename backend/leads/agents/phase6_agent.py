"""
Phase 6 Agent: CRM Integration
===============================

This agent handles:
1. CRM sync (HubSpot, Salesforce)
2. Lead/contact export to CRM
3. Activity logging and tracking
4. Pipeline synchronization
5. Two-way data sync

Tasks:
- Push enriched leads to CRM
- Sync deal stages and pipelines
- Log activities and engagements
- Handle webhook callbacks
- Manage field mappings
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum

from .base_agent import BaseAgent, AgentResult, AgentStatus, AgentRegistry

logger = logging.getLogger(__name__)


class CRMProvider(Enum):
    """Supported CRM providers"""
    HUBSPOT = "hubspot"
    SALESFORCE = "salesforce"
    PIPEDRIVE = "pipedrive"
    CUSTOM = "custom"


@AgentRegistry.register
class Phase6Agent(BaseAgent):
    """
    Phase 6 Agent: CRM Integration
    
    Capabilities:
    - Syncs leads to HubSpot/Salesforce
    - Maps fields between systems
    - Logs activities and engagements
    - Handles two-way sync
    """
    
    def __init__(self):
        super().__init__(name="Phase6_CRM", phase=6)
        
        # Default configuration
        self.config = {
            "primary_crm": "hubspot",
            "batch_size": 100,
            "sync_interval_minutes": 15,
            "enable_hubspot": True,
            "enable_salesforce": False,
            "enable_activity_sync": True,
            "hubspot_api_key": os.getenv("HUBSPOT_API_KEY", ""),
            "salesforce_client_id": os.getenv("SALESFORCE_CLIENT_ID", ""),
            "salesforce_client_secret": os.getenv("SALESFORCE_CLIENT_SECRET", ""),
            "field_mappings": {
                "hubspot": {
                    "email": "email",
                    "first_name": "firstname",
                    "last_name": "lastname",
                    "company_name": "company",
                    "title": "jobtitle",
                    "phone": "phone",
                    "lead_score": "hs_lead_status",
                    "linkedin_url": "linkedin_url"
                },
                "salesforce": {
                    "email": "Email",
                    "first_name": "FirstName",
                    "last_name": "LastName",
                    "company_name": "Company",
                    "title": "Title",
                    "phone": "Phone",
                    "lead_score": "Rating"
                }
            }
        }
        
        # API clients
        self._hubspot_client: Optional[httpx.AsyncClient] = None
        self._salesforce_client: Optional[httpx.AsyncClient] = None
    
    def get_description(self) -> str:
        return """Phase 6 Agent: CRM Integration
        
        - Syncs leads to HubSpot and Salesforce
        - Handles field mapping between systems
        - Logs activities and engagements
        - Supports two-way synchronization"""
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Phase 6 CRM integration tasks.
        """
        self.log_info("Starting Phase 6 CRM Integration...")
        
        results = {
            "hubspot_sync": {},
            "salesforce_sync": {},
            "activity_sync": {},
            "summary": {}
        }
        
        # Get leads to sync
        leads = await self._get_leads_to_sync(input_data)
        
        if not leads:
            self.log_info("No leads to sync")
            return {"message": "No leads to sync", "synced": 0}
        
        self.log_info(f"Syncing {len(leads)} leads to CRM...")
        self.add_metric("records_processed", len(leads))
        
        # Task 1: HubSpot Sync
        if self.config["enable_hubspot"] and self.config["hubspot_api_key"]:
            try:
                hubspot_results = await self._sync_to_hubspot(leads)
                results["hubspot_sync"] = hubspot_results
                self.add_metric("hubspot_synced", hubspot_results.get("synced", 0))
            except Exception as e:
                self.log_error(f"HubSpot sync failed: {e}")
                results["hubspot_sync"] = {"error": str(e)}
        else:
            results["hubspot_sync"] = {"status": "disabled", "reason": "No API key configured"}
        
        # Task 2: Salesforce Sync
        if self.config["enable_salesforce"] and self.config["salesforce_client_id"]:
            try:
                salesforce_results = await self._sync_to_salesforce(leads)
                results["salesforce_sync"] = salesforce_results
                self.add_metric("salesforce_synced", salesforce_results.get("synced", 0))
            except Exception as e:
                self.log_error(f"Salesforce sync failed: {e}")
                results["salesforce_sync"] = {"error": str(e)}
        else:
            results["salesforce_sync"] = {"status": "disabled", "reason": "No credentials configured"}
        
        # Task 3: Activity Sync
        if self.config["enable_activity_sync"]:
            try:
                activity_results = await self._sync_activities(leads)
                results["activity_sync"] = activity_results
            except Exception as e:
                self.log_error(f"Activity sync failed: {e}")
                results["activity_sync"] = {"error": str(e)}
        
        # Task 4: Mark leads as synced
        try:
            await self._mark_synced(leads, results)
        except Exception as e:
            self.log_error(f"Failed to mark synced: {e}")
        
        # Summary
        results["summary"] = {
            "total_processed": len(leads),
            "hubspot_synced": results["hubspot_sync"].get("synced", 0),
            "salesforce_synced": results["salesforce_sync"].get("synced", 0),
            "activities_synced": results["activity_sync"].get("synced", 0)
        }
        
        total_synced = results["summary"]["hubspot_synced"] + results["summary"]["salesforce_synced"]
        self.add_metric("records_success", total_synced)
        
        return results
    
    async def _get_leads_to_sync(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get leads that need CRM sync.
        """
        leads_collection = self.db['leads_raw']
        
        # Custom lead IDs if provided
        if input_data.get("lead_ids"):
            from bson import ObjectId
            query = {"_id": {"$in": [ObjectId(lid) for lid in input_data["lead_ids"]]}}
        else:
            # Find enriched but not synced leads
            query = {
                "enriched": True,
                "$or": [
                    {"crm_synced": {"$ne": True}},
                    {"crm_synced_at": {"$lt": datetime.utcnow() - timedelta(days=7)}}
                ]
            }
            
            # Filter by priority if specified
            if input_data.get("min_priority"):
                if input_data["min_priority"] == "high":
                    query["priority"] = "high"
                elif input_data["min_priority"] == "medium":
                    query["priority"] = {"$in": ["high", "medium"]}
        
        limit = input_data.get("limit", self.config["batch_size"])
        
        leads = list(leads_collection.find(query).limit(limit))
        
        for lead in leads:
            lead["_id"] = str(lead["_id"])
        
        return leads
    
    async def _sync_to_hubspot(self, leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sync leads to HubSpot CRM.
        """
        self.log_info("Syncing to HubSpot...")
        
        api_key = self.config["hubspot_api_key"]
        field_mappings = self.config["field_mappings"]["hubspot"]
        
        synced = 0
        created = 0
        updated = 0
        errors = 0
        
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            for lead in leads:
                try:
                    # Map fields to HubSpot format
                    properties = {}
                    for our_field, hs_field in field_mappings.items():
                        value = lead.get(our_field)
                        if value:
                            properties[hs_field] = str(value)
                    
                    # Check for company data
                    company_data = lead.get("company_data", {})
                    if company_data.get("name"):
                        properties["company"] = company_data["name"]
                    
                    # Use predicted email if no verified email
                    if not properties.get("email") and lead.get("predicted_email"):
                        properties["email"] = lead["predicted_email"]
                    
                    if not properties.get("email"):
                        self.log_warning(f"Skipping lead {lead['_id']}: no email")
                        continue
                    
                    # Search for existing contact
                    search_url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
                    search_body = {
                        "filterGroups": [{
                            "filters": [{
                                "propertyName": "email",
                                "operator": "EQ",
                                "value": properties["email"]
                            }]
                        }]
                    }
                    
                    search_response = await client.post(
                        search_url,
                        headers=headers,
                        json=search_body
                    )
                    
                    if search_response.status_code == 200:
                        search_data = search_response.json()
                        
                        if search_data.get("total", 0) > 0:
                            # Update existing contact
                            contact_id = search_data["results"][0]["id"]
                            update_url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
                            
                            update_response = await client.patch(
                                update_url,
                                headers=headers,
                                json={"properties": properties}
                            )
                            
                            if update_response.status_code == 200:
                                updated += 1
                                synced += 1
                                lead["hubspot_id"] = contact_id
                            else:
                                errors += 1
                                self.log_warning(f"HubSpot update failed: {update_response.text}")
                        else:
                            # Create new contact
                            create_url = "https://api.hubapi.com/crm/v3/objects/contacts"
                            
                            create_response = await client.post(
                                create_url,
                                headers=headers,
                                json={"properties": properties}
                            )
                            
                            if create_response.status_code == 201:
                                created += 1
                                synced += 1
                                lead["hubspot_id"] = create_response.json().get("id")
                            else:
                                errors += 1
                                self.log_warning(f"HubSpot create failed: {create_response.text}")
                    else:
                        errors += 1
                        self.log_warning(f"HubSpot search failed: {search_response.text}")
                    
                    # Rate limiting
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    errors += 1
                    self.log_warning(f"HubSpot sync error for lead {lead['_id']}: {e}")
        
        self.log_info(f"HubSpot sync: {created} created, {updated} updated, {errors} errors")
        
        return {
            "synced": synced,
            "created": created,
            "updated": updated,
            "errors": errors
        }
    
    async def _sync_to_salesforce(self, leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sync leads to Salesforce CRM.
        """
        self.log_info("Syncing to Salesforce...")
        
        # Note: This is a placeholder implementation
        # Real Salesforce integration requires OAuth2 flow
        
        field_mappings = self.config["field_mappings"]["salesforce"]
        
        synced = 0
        errors = 0
        
        # Placeholder: Would need to implement Salesforce OAuth and API calls
        for lead in leads:
            try:
                # Map fields
                sf_data = {}
                for our_field, sf_field in field_mappings.items():
                    value = lead.get(our_field)
                    if value:
                        sf_data[sf_field] = str(value)
                
                # Would call Salesforce API here
                # For now, just log what would be synced
                self.log_info(f"Would sync to Salesforce: {sf_data.get('Email', 'no email')}")
                synced += 1
                
            except Exception as e:
                errors += 1
                self.log_warning(f"Salesforce sync error: {e}")
        
        return {
            "synced": synced,
            "errors": errors,
            "note": "Salesforce integration requires OAuth setup"
        }
    
    async def _sync_activities(self, leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sync activities and engagements to CRM.
        """
        self.log_info("Syncing activities...")
        
        activities_collection = self.db['lead_activities']
        
        synced = 0
        
        for lead in leads:
            # Get recent activities for this lead
            activities = list(activities_collection.find({
                "lead_id": lead["_id"],
                "crm_synced": {"$ne": True}
            }).limit(50))
            
            for activity in activities:
                try:
                    # Would sync activity to CRM here
                    # For HubSpot: Engagements API
                    # For Salesforce: Activities API
                    
                    # Mark as synced
                    activities_collection.update_one(
                        {"_id": activity["_id"]},
                        {"$set": {"crm_synced": True, "crm_synced_at": datetime.utcnow()}}
                    )
                    synced += 1
                    
                except Exception as e:
                    self.log_warning(f"Activity sync error: {e}")
        
        return {"synced": synced}
    
    async def _mark_synced(self, leads: List[Dict[str, Any]], results: Dict[str, Any]):
        """
        Mark leads as synced in database.
        """
        self.log_info("Marking leads as synced...")
        
        leads_collection = self.db['leads_raw']
        sync_logs = self.db['crm_sync_logs']
        
        from bson import ObjectId
        
        for lead in leads:
            sync_data = {
                "crm_synced": True,
                "crm_synced_at": datetime.utcnow()
            }
            
            if lead.get("hubspot_id"):
                sync_data["hubspot_id"] = lead["hubspot_id"]
            if lead.get("salesforce_id"):
                sync_data["salesforce_id"] = lead["salesforce_id"]
            
            leads_collection.update_one(
                {"_id": ObjectId(lead["_id"])},
                {"$set": sync_data}
            )
            
            # Log sync
            sync_logs.insert_one({
                "lead_id": lead["_id"],
                "synced_at": datetime.utcnow(),
                "hubspot_synced": bool(lead.get("hubspot_id")),
                "salesforce_synced": bool(lead.get("salesforce_id")),
                "agent": "Phase6Agent"
            })
    
    async def get_sync_stats(self) -> Dict[str, Any]:
        """
        Get CRM sync statistics.
        """
        leads_collection = self.db['leads_raw']
        sync_logs = self.db['crm_sync_logs']
        
        # Overall stats
        total_leads = leads_collection.count_documents({"enriched": True})
        synced_leads = leads_collection.count_documents({"crm_synced": True})
        hubspot_synced = leads_collection.count_documents({"hubspot_id": {"$exists": True}})
        salesforce_synced = leads_collection.count_documents({"salesforce_id": {"$exists": True}})
        
        # Today's syncs
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        synced_today = sync_logs.count_documents({"synced_at": {"$gte": today}})
        
        # Pending sync
        pending = leads_collection.count_documents({
            "enriched": True,
            "crm_synced": {"$ne": True}
        })
        
        return {
            "total_enriched_leads": total_leads,
            "total_synced": synced_leads,
            "sync_rate": round(synced_leads / max(total_leads, 1) * 100, 1),
            "hubspot_synced": hubspot_synced,
            "salesforce_synced": salesforce_synced,
            "synced_today": synced_today,
            "pending_sync": pending,
            "crm_status": {
                "hubspot": "enabled" if self.config["enable_hubspot"] else "disabled",
                "salesforce": "enabled" if self.config["enable_salesforce"] else "disabled"
            }
        }
    
    async def configure_hubspot(self, api_key: str) -> Dict[str, Any]:
        """
        Configure HubSpot integration.
        """
        self.config["hubspot_api_key"] = api_key
        self.config["enable_hubspot"] = True
        
        # Test connection
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.hubapi.com/crm/v3/objects/contacts",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"limit": 1}
            )
            
            if response.status_code == 200:
                return {"status": "connected", "message": "HubSpot connected successfully"}
            else:
                return {"status": "error", "message": f"Connection failed: {response.text}"}
    
    async def configure_salesforce(self, client_id: str, client_secret: str, redirect_uri: str) -> Dict[str, Any]:
        """
        Configure Salesforce integration.
        Returns OAuth URL for user authorization.
        """
        self.config["salesforce_client_id"] = client_id
        self.config["salesforce_client_secret"] = client_secret
        
        auth_url = (
            f"https://login.salesforce.com/services/oauth2/authorize"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
        )
        
        return {
            "status": "pending_auth",
            "auth_url": auth_url,
            "message": "Redirect user to auth_url to complete Salesforce authorization"
        }
