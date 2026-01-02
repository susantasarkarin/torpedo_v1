"""
ALIAS RESOLVER
==============

Maps incoming emails to aliases based on email headers.

Resolution Logic:
1. Check To, Cc, Delivered-To headers
2. Match against known aliases for the mailbox
3. Return the most specific match

Header Priority:
1. Delivered-To (most reliable for actual delivery)
2. To (primary recipient)
3. Cc (carbon copy)

This allows a single mailbox (e.g., sales@company.com) to receive
emails addressed to multiple aliases (e.g., john@company.com, 
support@company.com) and correctly attribute them.
"""

import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from email.utils import parseaddr
from pymongo import MongoClient

from .models import AliasDocument, EmailAddress

logger = logging.getLogger(__name__)


class AliasResolver:
    """
    Resolves email addresses to aliases.
    
    Design:
    - Caches alias lookups per mailbox for performance
    - Handles various email address formats
    - Supports wildcard matching for catch-all aliases
    """
    
    def __init__(self, db: MongoClient, collection_name: str = "aliases"):
        """
        Initialize resolver.
        
        Args:
            db: MongoDB database instance
            collection_name: Name of aliases collection
        """
        self.collection = db[collection_name]
        self._cache: Dict[str, List[str]] = {}
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create required indexes"""
        try:
            self.collection.create_index("alias_email", unique=True)
            self.collection.create_index("mailbox_id")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def _normalize_email(self, email: str) -> str:
        """
        Normalize email address for comparison.
        
        - Lowercase
        - Remove plus addressing (user+tag@domain -> user@domain)
        - Strip whitespace
        """
        if not email:
            return ""
        
        email = email.lower().strip()
        
        # Parse email address
        _, parsed_email = parseaddr(email)
        if parsed_email:
            email = parsed_email
        
        # Handle plus addressing
        if "+" in email and "@" in email:
            local, domain = email.split("@", 1)
            local = local.split("+")[0]
            email = f"{local}@{domain}"
        
        return email
    
    def _get_aliases_for_mailbox(self, mailbox_id: str) -> List[str]:
        """
        Get all aliases for a mailbox (cached).
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            List of normalized alias emails
        """
        if mailbox_id in self._cache:
            return self._cache[mailbox_id]
        
        aliases = self.collection.find(
            {"mailbox_id": mailbox_id, "is_active": True},
            {"alias_email": 1}
        )
        
        alias_list = [
            self._normalize_email(a["alias_email"]) 
            for a in aliases
        ]
        
        self._cache[mailbox_id] = alias_list
        return alias_list
    
    def clear_cache(self, mailbox_id: Optional[str] = None):
        """
        Clear alias cache.
        
        Args:
            mailbox_id: Specific mailbox to clear, or None for all
        """
        if mailbox_id:
            self._cache.pop(mailbox_id, None)
        else:
            self._cache.clear()
    
    def resolve(
        self,
        mailbox_id: str,
        mailbox_email: str,
        to_addresses: List[EmailAddress],
        cc_addresses: List[EmailAddress],
        delivered_to: Optional[str] = None,
        raw_headers: Optional[Dict[str, str]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve which alias (if any) received this email.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            mailbox_email: Primary email of the mailbox
            to_addresses: List of To addresses
            cc_addresses: List of Cc addresses
            delivered_to: Delivered-To header value
            raw_headers: Raw email headers for fallback
            
        Returns:
            Tuple of (alias_id, matched_email) or (None, None)
        """
        aliases = self._get_aliases_for_mailbox(mailbox_id)
        
        if not aliases:
            # No aliases configured, no match needed
            return None, None
        
        # Build list of candidate addresses in priority order
        candidates = []
        
        # 1. Delivered-To (highest priority)
        if delivered_to:
            candidates.append(self._normalize_email(delivered_to))
        
        # 2. Check raw headers for additional Delivered-To
        if raw_headers:
            for key in ["Delivered-To", "X-Delivered-To", "X-Original-To"]:
                if key in raw_headers:
                    candidates.append(self._normalize_email(raw_headers[key]))
        
        # 3. To addresses
        for addr in to_addresses:
            candidates.append(self._normalize_email(addr.email))
        
        # 4. Cc addresses (lowest priority)
        for addr in cc_addresses:
            candidates.append(self._normalize_email(addr.email))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                unique_candidates.append(c)
        
        # Normalize mailbox email for comparison
        normalized_mailbox = self._normalize_email(mailbox_email)
        
        # Check each candidate against aliases
        for candidate in unique_candidates:
            # Skip if it's the mailbox's primary email
            if candidate == normalized_mailbox:
                continue
            
            # Check if candidate matches any alias
            if candidate in aliases:
                # Found a match - get the alias document
                alias_doc = self.collection.find_one({
                    "mailbox_id": mailbox_id,
                    "alias_email": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}
                })
                
                if alias_doc:
                    logger.debug(f"Resolved alias: {candidate} -> {alias_doc['_id']}")
                    return str(alias_doc["_id"]), candidate
        
        # No alias match found
        return None, None
    
    def add_alias(
        self,
        mailbox_id: str,
        alias_email: str,
        display_name: str = ""
    ) -> Optional[str]:
        """
        Add a new alias.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            alias_email: Alias email address
            display_name: Display name for alias
            
        Returns:
            Alias ID if created, None if duplicate
        """
        from datetime import datetime
        
        normalized = self._normalize_email(alias_email)
        
        doc = {
            "mailbox_id": mailbox_id,
            "alias_email": normalized,
            "display_name": display_name,
            "is_active": True,
            "created_at": datetime.utcnow(),
        }
        
        try:
            result = self.collection.insert_one(doc)
            self.clear_cache(mailbox_id)
            logger.info(f"Added alias {alias_email} to mailbox {mailbox_id}")
            return str(result.inserted_id)
        except Exception as e:
            if "duplicate key" in str(e).lower():
                logger.warning(f"Alias {alias_email} already exists")
                return None
            raise
    
    def remove_alias(self, alias_id: str) -> bool:
        """
        Remove (deactivate) an alias.
        
        Args:
            alias_id: Alias ObjectId string
            
        Returns:
            True if removed
        """
        from bson import ObjectId
        
        result = self.collection.update_one(
            {"_id": ObjectId(alias_id)},
            {"$set": {"is_active": False}}
        )
        
        if result.modified_count > 0:
            # Clear entire cache since we don't know the mailbox_id
            self.clear_cache()
            logger.info(f"Removed alias {alias_id}")
            return True
        
        return False
    
    def get_aliases_for_mailbox(self, mailbox_id: str) -> List[Dict[str, Any]]:
        """
        Get all aliases for a mailbox.
        
        Args:
            mailbox_id: Mailbox ObjectId string
            
        Returns:
            List of alias documents
        """
        aliases = list(self.collection.find(
            {"mailbox_id": mailbox_id, "is_active": True}
        ))
        
        for alias in aliases:
            alias["_id"] = str(alias["_id"])
        
        return aliases
    
    def get_alias_by_email(self, alias_email: str) -> Optional[Dict[str, Any]]:
        """
        Look up alias by email address.
        
        Args:
            alias_email: Email address to look up
            
        Returns:
            Alias document or None
        """
        normalized = self._normalize_email(alias_email)
        alias = self.collection.find_one({
            "alias_email": {"$regex": f"^{re.escape(normalized)}$", "$options": "i"},
            "is_active": True
        })
        
        if alias:
            alias["_id"] = str(alias["_id"])
        
        return alias


def extract_email_addresses(header_value: str) -> List[EmailAddress]:
    """
    Extract email addresses from a header value.
    
    Handles formats like:
    - "John Doe <john@example.com>"
    - "john@example.com"
    - "John Doe <john@example.com>, Jane <jane@example.com>"
    
    Args:
        header_value: Raw header value
        
    Returns:
        List of EmailAddress objects
    """
    if not header_value:
        return []
    
    addresses = []
    
    # Split by comma, handling quoted strings
    parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', header_value)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        name, email = parseaddr(part)
        if email:
            addresses.append(EmailAddress(
                email=email.lower(),
                name=name.strip('"\'') if name else ""
            ))
    
    return addresses


def determine_direction(
    mailbox_email: str,
    from_address: EmailAddress,
    aliases: List[str]
) -> str:
    """
    Determine if email is inbound or outbound.
    
    Args:
        mailbox_email: Primary mailbox email
        from_address: From address
        aliases: List of alias emails
        
    Returns:
        "inbound" or "outbound"
    """
    from_email = from_address.email.lower()
    mailbox_lower = mailbox_email.lower()
    aliases_lower = [a.lower() for a in aliases]
    
    # If from address matches mailbox or any alias, it's outbound
    if from_email == mailbox_lower:
        return "outbound"
    
    if from_email in aliases_lower:
        return "outbound"
    
    return "inbound"
