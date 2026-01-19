"""
Lead Deduplication - Check for existing leads before inserting
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# Daily lead limit
DAILY_LEAD_LIMIT = 1000


class LeadDeduplicator:
    """
    Handles deduplication of leads against existing leads_raw collection.
    Also manages daily quota tracking.
    """
    
    def __init__(self):
        self._client = None
        self._db = None
    
    def _get_db(self):
        """Get MongoDB database connection."""
        if self._db is None:
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            self._client = MongoClient(mongo_uri)
            self._db = self._client['email_automation']
        return self._db
    
    def check_duplicates(
        self,
        leads: List[Dict[str, Any]],
        check_email: bool = True,
        check_linkedin: bool = True
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Check for duplicates against leads_raw collection.
        
        Args:
            leads: List of lead dicts to check
            check_email: Whether to check email for duplicates
            check_linkedin: Whether to check LinkedIn URL for duplicates
            
        Returns:
            Tuple of (new_leads, duplicate_leads)
        """
        db = self._get_db()
        leads_raw = db['leads_raw']
        
        new_leads = []
        duplicate_leads = []
        
        for lead in leads:
            is_duplicate = False
            
            # Build query for duplicate check
            or_conditions = []
            
            if check_email and lead.get('email'):
                email = lead['email'].lower().strip()
                or_conditions.append({"email": {"$regex": f"^{email}$", "$options": "i"}})
            
            if check_linkedin and lead.get('linkedin_url'):
                linkedin = lead['linkedin_url'].strip()
                # Normalize LinkedIn URL for comparison
                linkedin_normalized = self._normalize_linkedin_url(linkedin)
                or_conditions.append({"linkedin_url": {"$regex": linkedin_normalized, "$options": "i"}})
            
            if or_conditions:
                existing = leads_raw.find_one({"$or": or_conditions})
                if existing:
                    is_duplicate = True
                    lead['duplicate_of'] = str(existing.get('_id'))
            
            if is_duplicate:
                duplicate_leads.append(lead)
            else:
                new_leads.append(lead)
        
        logger.info(f"Deduplication: {len(new_leads)} new, {len(duplicate_leads)} duplicates")
        return new_leads, duplicate_leads
    
    def _normalize_linkedin_url(self, url: str) -> str:
        """Normalize LinkedIn URL for comparison."""
        url = url.lower().strip()
        # Remove trailing slashes
        url = url.rstrip('/')
        # Extract the profile path
        if '/in/' in url:
            # Extract username part
            parts = url.split('/in/')
            if len(parts) > 1:
                username = parts[1].split('/')[0].split('?')[0]
                return f"/in/{username}"
        return url
    
    def get_quota_status(self) -> Dict[str, Any]:
        """
        Get current daily quota status.
        
        Returns:
            Dict with leads_today, limit, remaining, reset_at, is_limit_reached
        """
        db = self._get_db()
        settings = db['scheduler_settings']
        
        # Get or create quota document
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)
        
        quota_doc = settings.find_one({"_id": "agent_quota"})
        
        if quota_doc is None or quota_doc.get('date') != str(today):
            # Create or reset quota for new day
            quota_doc = {
                "_id": "agent_quota",
                "date": str(today),
                "leads_generated": 0,
                "reset_at": tomorrow_start
            }
            settings.update_one(
                {"_id": "agent_quota"},
                {"$set": quota_doc},
                upsert=True
            )
        
        leads_today = quota_doc.get('leads_generated', 0)
        remaining = max(0, DAILY_LEAD_LIMIT - leads_today)
        
        return {
            "leads_today": leads_today,
            "limit": DAILY_LEAD_LIMIT,
            "remaining": remaining,
            "reset_at": tomorrow_start,
            "is_limit_reached": remaining <= 0
        }
    
    def increment_quota(self, count: int = 1) -> bool:
        """
        Increment the daily quota counter.
        
        Args:
            count: Number of leads to add to quota
            
        Returns:
            True if successful, False if limit would be exceeded
        """
        db = self._get_db()
        settings = db['scheduler_settings']
        
        # Check current quota first
        status = self.get_quota_status()
        if status['remaining'] < count:
            logger.warning(f"Daily lead limit would be exceeded: {status['leads_today']} + {count} > {DAILY_LEAD_LIMIT}")
            return False
        
        # Increment counter
        today = datetime.utcnow().date()
        result = settings.update_one(
            {"_id": "agent_quota", "date": str(today)},
            {"$inc": {"leads_generated": count}},
            upsert=True
        )
        
        return result.modified_count > 0 or result.upserted_id is not None
    
    def check_email_exists(self, email: str) -> bool:
        """Check if an email already exists in leads_raw."""
        if not email:
            return False
        
        db = self._get_db()
        leads_raw = db['leads_raw']
        
        exists = leads_raw.find_one(
            {"email": {"$regex": f"^{email.strip()}$", "$options": "i"}}
        )
        return exists is not None
    
    def check_linkedin_exists(self, linkedin_url: str) -> bool:
        """Check if a LinkedIn URL already exists in leads_raw."""
        if not linkedin_url:
            return False
        
        db = self._get_db()
        leads_raw = db['leads_raw']
        
        normalized = self._normalize_linkedin_url(linkedin_url)
        exists = leads_raw.find_one(
            {"linkedin_url": {"$regex": normalized, "$options": "i"}}
        )
        return exists is not None
    
    def get_existing_emails(self, emails: List[str]) -> List[str]:
        """
        Get list of emails that already exist in the database.
        
        Args:
            emails: List of emails to check
            
        Returns:
            List of emails that already exist
        """
        if not emails:
            return []
        
        db = self._get_db()
        leads_raw = db['leads_raw']
        
        # Normalize emails
        normalized_emails = [e.lower().strip() for e in emails if e]
        
        # Query for existing
        existing = leads_raw.find(
            {"email": {"$in": normalized_emails}},
            {"email": 1}
        )
        
        return [doc['email'] for doc in existing]
    
    def get_existing_linkedins(self, linkedin_urls: List[str]) -> List[str]:
        """
        Get list of LinkedIn URLs that already exist in the database.
        
        Args:
            linkedin_urls: List of LinkedIn URLs to check
            
        Returns:
            List of LinkedIn URLs that already exist
        """
        if not linkedin_urls:
            return []
        
        db = self._get_db()
        leads_raw = db['leads_raw']
        
        existing_urls = []
        for url in linkedin_urls:
            if url and self.check_linkedin_exists(url):
                existing_urls.append(url)
        
        return existing_urls
