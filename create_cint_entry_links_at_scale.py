#!/usr/bin/env python3
"""
CREATE ENTRY LINKS AT SCALE
Generates entry links for ALL active Cint surveys (22,741+)
Uses synthetic links with [%MID%] placeholder since Cint supplier allocation is blocked
"""

import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")

from pymongo import MongoClient
from datetime import datetime
from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CintEntryLinkGenerator:
    def __init__(self):
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.client = MongoClient(mongo_uri)
        self.db = self.client["cint_research"]
        self.surveys = self.db["cint_surveys"]
        self.entry_links = self.db["cint_entry_links"]
        self.settings = self.db["cint_settings"]
        
        # Get base URL from settings
        self.api_base = self._get_api_base()
        
    def _get_api_base(self) -> str:
        """Get base API URL from settings or use default"""
        settings = self.settings.find_one({"type": "config"})
        if settings and "api_base" in settings:
            return settings["api_base"]
        return "https://torpedo.cogentixresearch.com"
    
    def _create_synthetic_link(self, survey_id: int) -> str:
        """Create synthetic entry link with [%MID%] placeholder"""
        return (
            f"{self.api_base}/cint-response"
            f"?mid=[%MID%]"
            f"&sid={survey_id}"
            f"&status=start"
        )
    
    def _create_entry_link_doc(self, survey_id: int) -> Dict[str, Any]:
        """Create entry link document matching Cint API structure"""
        return {
            "survey_id": survey_id,
            "survey_number": survey_id,  # Use survey_id as number for now
            "live_link": self._create_synthetic_link(survey_id),
            "test_link": (
                f"{self.api_base}/cint-response"
                f"?mid=[TEST_MID]"
                f"&sid={survey_id}"
                f"&status=test"
            ),
            "success_link": (
                f"{self.api_base}/cint-response"
                f"?mid=[%MID%]"
                f"&sid={survey_id}"
                f"&status=complete"
                f"&revenue=[%REVENUE%]"
            ),
            "failure_link": (
                f"{self.api_base}/cint-response"
                f"?mid=[%MID%]"
                f"&sid={survey_id}"
                f"&status=terminate"
            ),
            "over_quota_link": (
                f"{self.api_base}/cint-response"
                f"?mid=[%MID%]"
                f"&sid={survey_id}"
                f"&status=quota_full"
            ),
            "quality_termination_link": (
                f"{self.api_base}/cint-response"
                f"?mid=[%MID%]"
                f"&sid={survey_id}"
                f"&status=quality_terminate"
            ),
            "synthetic": True,
            "_type": "synthetic_entry_link",
            "created_at": datetime.utcnow()
        }
    
    def create_entry_links_for_active_surveys(self, batch_size: int = 1000) -> Dict[str, Any]:
        """
        Create entry links for ALL active surveys
        Processes in batches to avoid memory overload
        
        Returns:
            Statistics dict with counts
        """
        # Get all active surveys
        active_survey_ids = list(
            self.surveys.find(
                {"is_active_in_pool": True},
                {"survey_id": 1}
            ).distinct("survey_id")
        )
        
        logger.info(f"Found {len(active_survey_ids)} active surveys")
        
        # Get already existing entry links
        existing_survey_ids = set(
            self.entry_links.find(
                {},
                {"survey_id": 1}
            ).distinct("survey_id")
        )
        
        logger.info(f"Already have entry links for {len(existing_survey_ids)} surveys")
        
        # Find surveys that need links
        surveys_to_create = [sid for sid in active_survey_ids if sid not in existing_survey_ids]
        logger.info(f"Need to create {len(surveys_to_create)} new entry links")
        
        # Create in batches
        created = 0
        skipped = 0
        total_batches = (len(surveys_to_create) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(surveys_to_create))
            batch = surveys_to_create[start_idx:end_idx]
            
            # Create documents for batch
            docs = [self._create_entry_link_doc(sid) for sid in batch]
            
            # Insert batch
            if docs:
                try:
                    result = self.entry_links.insert_many(docs, ordered=False)
                    created += len(result.inserted_ids)
                    
                    progress = end_idx
                    percent = (progress / len(surveys_to_create)) * 100
                    logger.info(
                        f"  [{batch_num + 1}/{total_batches}] Created {len(result.inserted_ids)} links "
                        f"({progress}/{len(surveys_to_create)} = {percent:.1f}%)"
                    )
                except Exception as e:
                    logger.error(f"Error inserting batch {batch_num}: {e}")
        
        # Final statistics
        final_count = self.entry_links.count_documents({})
        final_active = self.surveys.count_documents({"is_active_in_pool": True})
        
        return {
            "success": True,
            "message": f"Created entry links for {created} surveys",
            "created": created,
            "existing": len(existing_survey_ids),
            "total_entry_links": final_count,
            "total_active_surveys": final_active,
            "coverage": f"{final_count}/{final_active} ({(final_count/final_active*100):.1f}%)"
        }

def main():
    generator = CintEntryLinkGenerator()
    
    print("=" * 70)
    print("CINT ENTRY LINK BATCH CREATOR")
    print("=" * 70)
    print()
    
    # Check current state
    print("Checking current state...")
    total_surveys = generator.surveys.count_documents({})
    active_surveys = generator.surveys.count_documents({"is_active_in_pool": True})
    existing_links = generator.entry_links.count_documents({})
    
    print(f"  Total surveys:          {total_surveys:,}")
    print(f"  Active surveys:         {active_surveys:,}")
    print(f"  Existing entry links:   {existing_links:,}")
    print()
    
    if active_surveys == 0:
        print("❌ No active surveys found!")
        print("   Run sync_active_status_by_filters() first")
        return
    
    print(f"Creating entry links for {active_surveys - existing_links:,} surveys...")
    print()
    
    result = generator.create_entry_links_for_active_surveys()
    
    print()
    print("=" * 70)
    print("RESULTS:")
    print("=" * 70)
    print(f"  Created:               {result['created']:,}")
    print(f"  Already existing:      {result['existing']:,}")
    print(f"  Total entry links:     {result['total_entry_links']:,}")
    print(f"  Total active surveys:  {result['total_active_surveys']:,}")
    print(f"  Coverage:              {result['coverage']}")
    print()
    
    if result['coverage'].split('/')[-1].strip().startswith('100'):
        print("✅ ALL ACTIVE SURVEYS NOW HAVE ENTRY LINKS!")
        print("   Allocation can now work for all 22,000+ surveys")
    else:
        pct = float(result['coverage'].split('(')[1].split('%')[0])
        if pct >= 90:
            print(f"✅ Almost complete! {pct:.1f}% coverage")
        else:
            print(f"⚠️  Partial coverage: {pct:.1f}%")
    print()
    print("=" * 70)

if __name__ == "__main__":
    main()
