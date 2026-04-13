"""
Email Pattern Discovery System
Tiered fallback system for discovering email patterns:
1. Database lookup (existing patterns)
2. Website scraping
3. Hunter.io API ($0.034/domain)
4. Pattern guessing (common patterns)
"""

import os
import re
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
from bs4 import BeautifulSoup


class EmailPatternSystem:
    """Discover and cache email patterns for companies"""
    
    COMMON_PATTERNS = [
        "{first}.{last}@{domain}",
        "{first}{last}@{domain}",
        "{f}{last}@{domain}",
        "{first}@{domain}",
        "{first}_{last}@{domain}",
        "{last}.{first}@{domain}",
        "{first}{l}@{domain}"
    ]
    
    def __init__(self, mongo_uri: str = None, database_name: str = "email_automation", hunter_api_key: str = None):
        """Initialize pattern system with MongoDB and Hunter.io"""
        if mongo_uri is None:
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        
        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.settings_db = self.client["torpedo_settings"]
        self.patterns_collection = self.db["email_patterns"]
        
        # Load Hunter.io API key
        if hunter_api_key is None:
            hunter_api_key = self._load_hunter_api_key()
        self.hunter_api_key = hunter_api_key
        
        # Ensure indexes
        self._ensure_indexes()
    
    def _load_hunter_api_key(self) -> Optional[str]:
        """Load Hunter.io API key from database or environment"""
        try:
            settings = self.settings_db["app_settings"].find_one()
            if settings and "hunter_api_key" in settings:
                return settings["hunter_api_key"]
        except:
            pass
        
        return os.getenv("HUNTER_API_KEY")
    
    def _ensure_indexes(self):
        """Create necessary indexes"""
        self.patterns_collection.create_index([("domain", 1)], unique=True)
        self.patterns_collection.create_index([("confidence", -1)])
        self.patterns_collection.create_index([("last_verified", -1)])
        self.patterns_collection.create_index([("source", 1)])
    
    def _extract_domain(self, email_or_website: str) -> str:
        """Extract domain from email or website URL"""
        if not email_or_website:
            return ""
        
        domain = email_or_website.replace("http://", "").replace("https://", "")
        
        if "@" in domain:
            domain = domain.split("@")[1]
        
        domain = domain.split("/")[0].split("?")[0]
        
        if domain.startswith("www."):
            domain = domain[4:]
        
        return domain.lower().strip()
    
    def get_pattern(self, domain: str) -> Optional[Dict]:
        """
        Get email pattern for a domain using tiered fallback
        
        Args:
            domain: Company domain (e.g., "techcorp.com")
            
        Returns:
            {
                "domain": str,
                "pattern": str,
                "confidence": float,
                "source": str,
                "examples": List[str],
                "last_verified": datetime
            }
        """
        domain = self._extract_domain(domain)
        
        if not domain:
            return None
        
        # Tier 1: Database lookup
        pattern = self._lookup_database(domain)
        if pattern:
            return pattern
        
        # Tier 1.5: Analyze known emails from CSV-uploaded leads in leads_enriched
        pattern = self._analyze_patterns_from_known_emails(domain)
        if pattern:
            self._store_pattern(pattern)
            return pattern
        
        # Tier 2: Website scraping
        pattern = self._scrape_website(domain)
        if pattern:
            self._store_pattern(pattern)
            return pattern

        # Tier 2.5: Skrapp.io company email pattern discovery
        skrapp_pattern_str = self.discover_company_email_pattern(domain)
        if skrapp_pattern_str:
            # Pattern already stored by discover_company_email_pattern; return from DB
            stored = self._lookup_database(domain)
            if stored:
                return stored

        # Tier 3: Hunter.io API
        if self.hunter_api_key:
            pattern = self._hunter_lookup(domain)
            if pattern:
                self._store_pattern(pattern)
                return pattern
        
        # Tier 4: Pattern guessing
        pattern = self._guess_pattern(domain)
        if pattern:
            self._store_pattern(pattern)
            return pattern
        
        return None
    
    def _lookup_database(self, domain: str) -> Optional[Dict]:
        """Tier 1: Look up pattern in database"""
        pattern = self.patterns_collection.find_one({"domain": domain})
        
        if pattern:
            # Update last accessed
            self.patterns_collection.update_one(
                {"_id": pattern["_id"]},
                {
                    "$set": {"last_accessed": datetime.now()},
                    "$inc": {"hit_count": 1}
                }
            )
            return pattern
        
        return None
    
    def _analyze_patterns_from_known_emails(self, domain: str) -> Optional[Dict]:
        """
        Tier 1.5: Discover email pattern from CSV-uploaded leads that already have
        verified emails for this domain in leads_enriched.
        
        E.g. if leads_enriched has john.doe@company.com and jane.smith@company.com,
        we can infer the pattern is {first}.{last}@{domain}.
        """
        try:
            enriched_col = self.db["leads_enriched"]
            # Find leads with emails at this domain that have both first_name and last_name
            domain_leads = list(enriched_col.find(
                {
                    "email": {"$regex": f"@{re.escape(domain)}$", "$options": "i"},
                    "first_name": {"$exists": True, "$ne": None, "$ne": ""},
                    "last_name": {"$exists": True, "$ne": None, "$ne": ""},
                },
                {"email": 1, "first_name": 1, "last_name": 1},
            ).limit(20))

            if len(domain_leads) < 1:
                return None

            # Try to reverse-engineer the pattern from known emails
            pattern_votes = {}
            examples = []

            for lead in domain_leads:
                email = (lead.get("email") or "").lower().strip()
                first = (lead.get("first_name") or "").lower().strip()
                last = (lead.get("last_name") or "").lower().strip()
                if not email or not first or not last or "@" not in email:
                    continue

                local_part = email.split("@")[0]
                examples.append(email)

                # Check which pattern this email matches
                if local_part == f"{first}.{last}":
                    pattern_votes.setdefault("{first}.{last}@{domain}", 0)
                    pattern_votes["{first}.{last}@{domain}"] += 1
                elif local_part == f"{first}{last}":
                    pattern_votes.setdefault("{first}{last}@{domain}", 0)
                    pattern_votes["{first}{last}@{domain}"] += 1
                elif local_part == f"{first[0]}{last}":
                    pattern_votes.setdefault("{f}{last}@{domain}", 0)
                    pattern_votes["{f}{last}@{domain}"] += 1
                elif local_part == f"{first}_{last}":
                    pattern_votes.setdefault("{first}_{last}@{domain}", 0)
                    pattern_votes["{first}_{last}@{domain}"] += 1
                elif local_part == f"{last}.{first}":
                    pattern_votes.setdefault("{last}.{first}@{domain}", 0)
                    pattern_votes["{last}.{first}@{domain}"] += 1
                elif local_part == first:
                    pattern_votes.setdefault("{first}@{domain}", 0)
                    pattern_votes["{first}@{domain}"] += 1
                elif local_part == f"{first}{last[0]}":
                    pattern_votes.setdefault("{first}{l}@{domain}", 0)
                    pattern_votes["{first}{l}@{domain}"] += 1

            if not pattern_votes:
                return None

            best_pattern = max(pattern_votes.items(), key=lambda x: x[1])
            total_matched = sum(pattern_votes.values())
            confidence = min(0.95, 0.6 + (best_pattern[1] / max(total_matched, 1)) * 0.3)

            print(f"[EmailPattern] CSV-derived pattern for {domain}: {best_pattern[0]} "
                  f"(confidence={confidence:.2f}, {best_pattern[1]}/{len(domain_leads)} matched)")

            return {
                "domain": domain,
                "pattern": best_pattern[0],
                "confidence": confidence,
                "source": "csv_leads_analysis",
                "examples": examples[:5],
                "discovered_at": datetime.now(),
                "last_verified": datetime.now(),
                "samples_analyzed": len(domain_leads),
            }

        except Exception as e:
            print(f"[EmailPattern] CSV analysis error for {domain}: {e}")
            return None
    
    def _scrape_website(self, domain: str) -> Optional[Dict]:
        """Tier 2: Scrape website for email patterns"""
        try:
            # Try common pages
            urls_to_try = [
                f"https://{domain}/contact",
                f"https://{domain}/about",
                f"https://{domain}/team",
                f"https://{domain}",
            ]
            
            emails_found = []
            
            for url in urls_to_try:
                try:
                    response = requests.get(url, timeout=10, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    
                    if response.status_code == 200:
                        # Extract emails using regex
                        email_pattern = r'\b[A-Za-z0-9._%+-]+@' + re.escape(domain) + r'\b'
                        found = re.findall(email_pattern, response.text, re.IGNORECASE)
                        emails_found.extend(found)
                        
                        # Also try BeautifulSoup for more robust extraction
                        soup = BeautifulSoup(response.text, 'html.parser')
                        mailto_links = soup.find_all('a', href=re.compile(r'^mailto:'))
                        for link in mailto_links:
                            email = link['href'].replace('mailto:', '').split('?')[0]
                            if domain in email.lower():
                                emails_found.append(email)
                
                except:
                    continue
            
            if emails_found:
                # Analyze patterns from found emails
                pattern = self._analyze_email_samples(domain, list(set(emails_found)))
                pattern["source"] = "website_scrape"
                pattern["discovered_at"] = datetime.now()
                return pattern
        
        except Exception as e:
            print(f"Website scraping error for {domain}: {e}")
        
        return None
    
    def _hunter_lookup(self, domain: str) -> Optional[Dict]:
        """Tier 3: Use Hunter.io API to discover pattern"""
        if not self.hunter_api_key:
            return None
        
        try:
            url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={self.hunter_api_key}"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("data") and data["data"].get("pattern"):
                    hunter_pattern = data["data"]["pattern"]
                    emails = data["data"].get("emails", [])
                    
                    # Convert Hunter.io pattern to our format
                    pattern_map = {
                        "{first}": "{first}",
                        "{last}": "{last}",
                        "{f}": "{f}",
                        "{l}": "{l}"
                    }
                    
                    our_pattern = hunter_pattern
                    for hunter_fmt, our_fmt in pattern_map.items():
                        our_pattern = our_pattern.replace(hunter_fmt, our_fmt)
                    
                    examples = [e["value"] for e in emails[:5] if e.get("value")]
                    
                    return {
                        "domain": domain,
                        "pattern": our_pattern,
                        "confidence": 0.9,  # Hunter.io is very reliable
                        "source": "hunter_io",
                        "examples": examples,
                        "discovered_at": datetime.now(),
                        "last_verified": datetime.now(),
                        "hunter_data": {
                            "organization": data["data"].get("organization"),
                            "emails_found": len(emails)
                        }
                    }
        
        except Exception as e:
            print(f"Hunter.io API error for {domain}: {e}")
        
        return None
    
    def _guess_pattern(self, domain: str) -> Optional[Dict]:
        """Tier 4: Make educated guess based on common patterns"""
        # Return most common pattern with low confidence
        return {
            "domain": domain,
            "pattern": "{first}.{last}@{domain}",
            "confidence": 0.3,  # Low confidence for guess
            "source": "guess",
            "examples": [],
            "discovered_at": datetime.now(),
            "last_verified": None,
            "note": "Guessed pattern - verification recommended"
        }
    
    def _analyze_email_samples(self, domain: str, emails: List[str]) -> Dict:
        """Analyze sample emails to determine pattern"""
        if not emails:
            return self._guess_pattern(domain)
        
        # Extract name parts from emails
        patterns_found = {}
        
        for email in emails:
            local_part = email.split("@")[0].lower()
            
            # Skip generic addresses
            if local_part in ["info", "contact", "support", "sales", "admin", "hello", "team"]:
                continue
            
            # Detect pattern
            if "." in local_part:
                if len(local_part.split(".")) == 2:
                    patterns_found["{first}.{last}@{domain}"] = patterns_found.get("{first}.{last}@{domain}", 0) + 1
            elif "_" in local_part:
                patterns_found["{first}_{last}@{domain}"] = patterns_found.get("{first}_{last}@{domain}", 0) + 1
            elif len(local_part) > 1:
                # Could be firstlast or first
                patterns_found["{first}{last}@{domain}"] = patterns_found.get("{first}{last}@{domain}", 0) + 1
        
        if not patterns_found:
            return self._guess_pattern(domain)
        
        # Get most common pattern
        most_common = max(patterns_found.items(), key=lambda x: x[1])
        
        confidence = min(0.9, 0.5 + (most_common[1] / len(emails)) * 0.4)
        
        return {
            "domain": domain,
            "pattern": most_common[0],
            "confidence": confidence,
            "source": "analysis",
            "examples": emails[:5],
            "discovered_at": datetime.now(),
            "last_verified": datetime.now(),
            "samples_analyzed": len(emails)
        }
    
    def _store_pattern(self, pattern_data: Dict) -> str:
        """Store discovered pattern in database"""
        pattern_data["created_at"] = datetime.now()
        pattern_data["last_accessed"] = datetime.now()
        pattern_data["hit_count"] = 0
        
        result = self.patterns_collection.update_one(
            {"domain": pattern_data["domain"]},
            {"$set": pattern_data},
            upsert=True
        )
        
        if result.upserted_id:
            return str(result.upserted_id)
        else:
            existing = self.patterns_collection.find_one({"domain": pattern_data["domain"]})
            return str(existing["_id"]) if existing else None
    
    def build_email(self, first_name: str, last_name: str, domain: str) -> Tuple[str, float]:
        """
        Build email address using discovered pattern
        
        Args:
            first_name: Person's first name
            last_name: Person's last name
            domain: Company domain
            
        Returns:
            (email_address, confidence)
        """
        pattern_data = self.get_pattern(domain)
        
        if not pattern_data:
            # Fallback to most common pattern
            pattern = "{first}.{last}@{domain}"
            confidence = 0.2
        else:
            pattern = pattern_data["pattern"]
            confidence = pattern_data["confidence"]
        
        # Build email from pattern
        email = pattern.format(
            first=first_name.lower(),
            last=last_name.lower(),
            f=first_name[0].lower() if first_name else "",
            l=last_name[0].lower() if last_name else "",
            domain=domain.lower()
        )
        
        return email, confidence
    
    def analyze_mail_pool(self, limit: int = None) -> Dict:
        """
        One-time analysis of existing mail_pool to extract patterns
        
        Args:
            limit: Max emails to analyze (None = all)
            
        Returns:
            Statistics about discovered patterns
        """
        mail_pool = self.db["mail_pool"]
        
        query = {}
        cursor = mail_pool.find(query)
        if limit:
            cursor = cursor.limit(limit)
        
        # Group emails by domain
        emails_by_domain = {}
        
        for email_doc in cursor:
            sender_email = email_doc.get("sender", {}).get("email")
            if not sender_email or "@" not in sender_email:
                continue
            
            domain = self._extract_domain(sender_email)
            if not domain:
                continue
            
            if domain not in emails_by_domain:
                emails_by_domain[domain] = []
            
            emails_by_domain[domain].append(sender_email)
        
        # Analyze each domain
        patterns_discovered = 0
        patterns_updated = 0
        
        for domain, emails in emails_by_domain.items():
            # Skip if already in database
            existing = self._lookup_database(domain)
            if existing and existing["source"] != "guess":
                continue
            
            # Analyze pattern
            pattern = self._analyze_email_samples(domain, emails)
            
            if pattern["confidence"] > 0.5:  # Only store if reasonably confident
                self._store_pattern(pattern)
                
                if existing:
                    patterns_updated += 1
                else:
                    patterns_discovered += 1
        
        return {
            "domains_analyzed": len(emails_by_domain),
            "patterns_discovered": patterns_discovered,
            "patterns_updated": patterns_updated,
            "total_emails_analyzed": sum(len(emails) for emails in emails_by_domain.values())
        }
    
    def verify_pattern(self, domain: str, sample_email: str) -> bool:
        """
        Verify if a pattern is correct using a known email
        
        Args:
            domain: Domain to verify
            sample_email: Known valid email to test pattern against
            
        Returns:
            True if pattern matches
        """
        pattern_data = self.get_pattern(domain)
        if not pattern_data:
            return False
        
        # Extract name from email
        local_part = sample_email.split("@")[0].lower()
        
        # This is a simplified verification - in production, you'd need more sophisticated matching
        pattern = pattern_data["pattern"]
        
        # Check if email follows the pattern structure
        if "{first}.{last}" in pattern and "." in local_part:
            return True
        if "{first}_{last}" in pattern and "_" in local_part:
            return True
        if "{first}{last}" in pattern and "." not in local_part and "_" not in local_part:
            return True
        
        return False
    
    # ================================================================
    # SKRAPP.IO COMPANY EMAIL PATTERN DISCOVERY (3 Accounts)
    # ================================================================

    def _load_skrapp_keys(self) -> List[str]:
        """Load up to 3 Skrapp API keys from settings DB or environment."""
        keys = []
        try:
            cfg = self.settings_db["app_settings"].find_one({"_id": "app_config"}) or {}
            for i in range(1, 4):
                k = cfg.get(f"skrapp_api_key_{i}") or os.getenv(f"SKRAPP_API_KEY_{i}", "")
                if k:
                    keys.append(k)
        except Exception:
            pass
        # Also check legacy single key
        if not keys:
            single = os.getenv("SKRAPP_API_KEY", "")
            if single:
                keys.append(single)
        return keys

    def get_skrapp_account_with_capacity(self) -> Optional[Dict]:
        """
        Return the Skrapp account dict with the most remaining searches this month,
        or None if all accounts are exhausted or no keys are configured.
        Returns: {"account_index": int (1-based), "key": str, "remaining": int}
        """
        keys = self._load_skrapp_keys()
        if not keys:
            return None

        month = datetime.utcnow().strftime("%Y-%m")
        skrapp_usage = self.db["skrapp_usage"]
        best = None

        for i, key in enumerate(keys, start=1):
            usage_doc = skrapp_usage.find_one({"account_id": str(i), "month": month}) or {}
            used = usage_doc.get("searches_used", 0)
            limit = usage_doc.get("searches_limit", 150)
            remaining = limit - used
            if remaining > 0:
                if best is None or remaining > best["remaining"]:
                    best = {"account_index": i, "key": key, "remaining": remaining}

        return best

    def increment_skrapp_usage(self, account_index: int):
        """Increment the monthly search counter for a Skrapp account."""
        month = datetime.utcnow().strftime("%Y-%m")
        self.db["skrapp_usage"].update_one(
            {"account_id": str(account_index), "month": month},
            {
                "$inc": {"searches_used": 1},
                "$setOnInsert": {"searches_limit": 150, "account_id": str(account_index), "month": month},
            },
            upsert=True,
        )

    def _extract_pattern_from_email(self, email: str, domain: str) -> Optional[str]:
        """
        Extract a pattern string from a discovered email address.
        e.g. "alice.jones@acme.com" → "{first}.{last}@{domain}"
        """
        if not email or "@" not in email:
            return None
        local = email.split("@")[0].lower()
        # Try to match common patterns
        if "." in local and len(local.split(".")) == 2:
            return "{first}.{last}@{domain}"
        if "_" in local and len(local.split("_")) == 2:
            return "{first}_{last}@{domain}"
        if len(local) > 1 and local[1:].isalpha():
            # Looks like initial+last (e.g. "ajones")
            return "{f}{last}@{domain}"
        if local.isalpha():
            return "{first}@{domain}"
        return "{first}.{last}@{domain}"  # safest default

    def discover_company_email_pattern(
        self,
        domain: str,
        sample_first: str = "test",
        sample_last: str = "user",
    ) -> Optional[str]:
        """
        Tier 2.5: Call Skrapp.io to discover a company email pattern.
        PURPOSE: Company-wide pattern discovery, NOT individual email lookup.

        - Skips if domain already has a pattern with confidence >= 0.8.
        - Rotates across up to 3 Skrapp accounts via monthly usage counter.
        - Stores discovered pattern in email_patterns collection.
        - Returns the pattern string (e.g. "{first}.{last}@{domain}") or None.
        """
        domain = self._extract_domain(domain)
        if not domain:
            return None

        # Skip if we already have a high-confidence pattern
        existing = self._lookup_database(domain)
        if existing and existing.get("confidence", 0) >= 0.8:
            return existing.get("pattern")

        account = self.get_skrapp_account_with_capacity()
        if not account:
            return None  # All accounts exhausted or no keys configured

        try:
            import requests as _requests
            resp = _requests.post(
                "https://app.skrapp.io/api/v2/email-finder",
                json={"domain": domain, "firstName": sample_first, "lastName": sample_last},
                headers={"Authorization": f"Bearer {account['key']}"},
                timeout=15,
            )
            self.increment_skrapp_usage(account["account_index"])

            if resp.status_code == 200:
                data = resp.json()
                found_email = (data.get("email") or "").lower().strip()
                if found_email and domain in found_email:
                    # Use Skrapp-returned pattern if available, otherwise extract from email
                    skrapp_pattern = data.get("pattern", "")
                    if skrapp_pattern:
                        # Skrapp returns patterns like "{first}.{last}" — append domain
                        if "@" not in skrapp_pattern:
                            pattern_str = f"{skrapp_pattern}@{{domain}}"
                        else:
                            pattern_str = skrapp_pattern
                    else:
                        pattern_str = self._extract_pattern_from_email(found_email, domain)

                    if pattern_str:
                        pattern_doc = {
                            "domain": domain,
                            "pattern": pattern_str,
                            "confidence": 0.9,
                            "source": "skrapp",
                            "examples": [found_email],
                            "discovered_at": datetime.now(),
                            "last_verified": datetime.now(),
                            "skrapp_account": account["account_index"],
                        }
                        self._store_pattern(pattern_doc)
                        print(f"[Skrapp] Pattern discovered for {domain}: {pattern_str}")
                        return pattern_str

        except Exception as e:
            print(f"[Skrapp] API error for {domain}: {e}")

        return None

    def apply_pattern_to_domain_leads(self, domain: str, pattern_str: str) -> int:
        """
        Apply a discovered email pattern to all existing leads in leads_enriched
        from the same company domain that currently have no email.
        Returns count of leads updated.
        """
        if not domain or not pattern_str:
            return 0

        enriched = self.db["leads_enriched"]
        leads_without_email = list(enriched.find(
            {
                "company_domain": domain,
                "$or": [{"email": None}, {"email": ""}, {"email": {"$exists": False}}],
                "first_name": {"$exists": True, "$ne": None, "$ne": ""},
            },
            {"_id": 1, "first_name": 1, "last_name": 1},
        ))

        updated = 0
        for lead in leads_without_email:
            first = (lead.get("first_name") or "").lower().strip()
            last = (lead.get("last_name") or "").lower().strip()
            if not first:
                continue
            try:
                derived_email = pattern_str.format(
                    first=first,
                    last=last,
                    f=first[0] if first else "",
                    l=last[0] if last else "",
                    domain=domain,
                )
                enriched.update_one(
                    {"_id": lead["_id"]},
                    {"$set": {
                        "email": derived_email,
                        "email_source": "pattern_derived",
                        "updated_at": datetime.utcnow(),
                    }},
                )
                # Also update leads_raw
                self.db["leads_raw"].update_one(
                    {"enriched_lead_id": str(lead["_id"])},
                    {"$set": {"email": derived_email, "email_source": "pattern_derived", "updated_at": datetime.utcnow()}},
                )
                updated += 1
            except (KeyError, IndexError):
                continue

        if updated:
            print(f"[Skrapp] Derived emails for {updated} leads from domain {domain} using pattern {pattern_str}")
        return updated

    def get_skrapp_usage_stats(self) -> List[Dict]:
        """Return monthly Skrapp usage stats for all 3 accounts."""
        month = datetime.utcnow().strftime("%Y-%m")
        keys = self._load_skrapp_keys()
        stats = []
        for i in range(1, 4):
            doc = self.db["skrapp_usage"].find_one({"account_id": str(i), "month": month}) or {}
            stats.append({
                "account": i,
                "month": month,
                "searches_used": doc.get("searches_used", 0),
                "searches_limit": doc.get("searches_limit", 150),
                "remaining": doc.get("searches_limit", 150) - doc.get("searches_used", 0),
                "key_configured": i <= len(keys),
            })
        return stats

    def get_stats(self) -> Dict:
        total_patterns = self.patterns_collection.count_documents({})
        
        by_source = list(self.patterns_collection.aggregate([
            {"$group": {"_id": "$source", "count": {"$sum": 1}}}
        ]))
        
        high_confidence = self.patterns_collection.count_documents({"confidence": {"$gte": 0.8}})
        
        return {
            "total_patterns": total_patterns,
            "high_confidence_patterns": high_confidence,
            "by_source": {item["_id"]: item["count"] for item in by_source},
            "hunter_api_configured": bool(self.hunter_api_key)
        }


# Singleton instance
_pattern_system_instance = None

def get_pattern_system() -> EmailPatternSystem:
    """Get or create the singleton EmailPatternSystem instance"""
    global _pattern_system_instance
    if _pattern_system_instance is None:
        _pattern_system_instance = EmailPatternSystem()
    return _pattern_system_instance


if __name__ == "__main__":
    # Test the pattern system
    print("=== Email Pattern System Test ===\n")
    
    try:
        system = EmailPatternSystem()
        
        # Test pattern lookup
        print("1. Testing get_pattern():")
        test_domains = ["google.com", "microsoft.com", "techcorp.com"]
        
        for domain in test_domains:
            pattern = system.get_pattern(domain)
            if pattern:
                print(f"   {domain}: {pattern['pattern']} (confidence: {pattern['confidence']}, source: {pattern['source']})")
        print()
        
        # Test email building
        print("2. Testing build_email():")
        email, confidence = system.build_email("John", "Smith", "google.com")
        print(f"   Built: {email} (confidence: {confidence})\n")
        
        # Test mail_pool analysis
        print("3. Testing analyze_mail_pool():")
        stats = system.analyze_mail_pool(limit=100)
        print(f"   Domains analyzed: {stats['domains_analyzed']}")
        print(f"   Patterns discovered: {stats['patterns_discovered']}")
        print(f"   Patterns updated: {stats['patterns_updated']}\n")
        
        # Get system stats
        print("4. System Statistics:")
        stats = system.get_stats()
        print(f"   Total patterns: {stats['total_patterns']}")
        print(f"   High confidence: {stats['high_confidence_patterns']}")
        print(f"   By source: {stats['by_source']}")
        print(f"   Hunter.io configured: {stats['hunter_api_configured']}\n")
        
        print("✅ All tests completed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
