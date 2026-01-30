#!/usr/bin/env python3
"""
Bulk Entry Link Generation Script for Cint Surveys

This script generates entry links for all active Cint surveys that don't already have one.
It uses async/await for efficient parallel API calls with rate limiting.

Usage:
    python backend/scripts/bulk_generate_cint_entry_links.py [--dry-run] [--max-concurrent N]

Options:
    --dry-run           Preview which surveys would get links without making API calls
    --max-concurrent N  Maximum concurrent API calls (default: 5)
    --batch-size N      Process N surveys per batch (default: 10)
    --active-only       Only process surveys with is_active=True (default)
    --include-pool      Only process surveys with is_active_in_pool=True
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime
from typing import List, Dict, Any
import csv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from dotenv import load_dotenv

# Import FastAPI app components
from app.services.cint_service import CintService
from app.models.cint import SupplierLinkCreate

# Load environment variables
load_dotenv()

# Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
CINT_API_KEY = os.getenv('CINT_API_KEY')
CINT_SUPPLIER_CODE = os.getenv('CINT_SUPPLIER_CODE')
CINT_BASE_URL = os.getenv('CINT_BASE_URL', 'https://api.samplicio.us')

# Default settings
DEFAULT_MAX_CONCURRENT = 5
DEFAULT_BATCH_SIZE = 10
BATCH_DELAY_SECONDS = 2


class BulkEntryLinkGenerator:
    """Handles bulk entry link generation for Cint surveys"""
    
    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT, 
                 batch_size: int = DEFAULT_BATCH_SIZE, dry_run: bool = False):
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self.dry_run = dry_run
        
        # MongoDB connection
        self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client["cint_research"]
        self.cint_surveys = self.db["cint_surveys"]
        self.cint_entry_links = self.db["cint_entry_links"]
        
        # Initialize Cint service
        self.cint_service = None
        
        # Statistics
        self.stats = {
            "total": 0,
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "already_exists": 0
        }
        
        # Failed surveys
        self.failed_surveys = []
        
    async def initialize_service(self):
        """Initialize the Cint service"""
        self.cint_service = CintService(
            api_key=CINT_API_KEY,
            base_url=CINT_BASE_URL
        )
        print(f"✓ Cint service initialized (API: {CINT_BASE_URL})")
        
    async def close_service(self):
        """Close the Cint service"""
        if self.cint_service:
            await self.cint_service.close()
        self.client.close()
        
    def get_surveys_without_links(self, active_only: bool = True, 
                                   include_pool_only: bool = False) -> List[Dict[str, Any]]:
        """
        Query MongoDB for surveys without entry links
        
        Args:
            active_only: Only get active surveys
            include_pool_only: Only get surveys with is_active_in_pool=True
            
        Returns:
            List of survey documents
        """
        print("\n📊 Querying database for surveys without entry links...")
        
        # Build aggregation pipeline
        match_conditions = {}
        if active_only:
            match_conditions["is_active"] = True
            match_conditions["is_live"] = True
        if include_pool_only:
            match_conditions["is_active_in_pool"] = True
            
        pipeline = [
            {
                "$lookup": {
                    "from": "cint_entry_links",
                    "localField": "survey_id",
                    "foreignField": "survey_id",
                    "as": "entry_link"
                }
            },
            {
                "$match": {
                    "entry_link": {"$eq": []},  # No entry link exists
                    **match_conditions
                }
            },
            {
                "$project": {
                    "survey_id": 1,
                    "survey_name": 1,
                    "payout": 1,
                    "country_language": 1,
                    "length_of_interview": 1,
                    "is_active": 1,
                    "is_active_in_pool": 1,
                    "created_at": 1
                }
            },
            {
                "$sort": {"created_at": -1}  # Newest first
            }
        ]
        
        surveys = list(self.cint_surveys.aggregate(pipeline))
        
        print(f"✓ Found {len(surveys)} surveys without entry links")
        
        # Show summary stats
        total_surveys = self.cint_surveys.count_documents(match_conditions)
        total_links = self.cint_entry_links.count_documents({})
        print(f"  • Total active surveys: {total_surveys}")
        print(f"  • Surveys with entry links: {total_links}")
        print(f"  • Surveys needing entry links: {len(surveys)}")
        
        return surveys
        
    async def create_entry_link(self, survey: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create entry link for a single survey (idempotent)
        
        Args:
            survey: Survey document from MongoDB
            
        Returns:
            Result dictionary with success status
        """
        survey_id = survey["survey_id"]
        
        # Check if entry link already exists (double-check for race conditions)
        existing = self.cint_entry_links.find_one({"survey_id": survey_id})
        if existing:
            self.stats["already_exists"] += 1
            return {
                "survey_id": survey_id,
                "success": True,
                "status": "already_exists",
                "message": "Entry link already exists"
            }
        
        # Create entry link config
        link_config = SupplierLinkCreate(
            SupplierLinkTypeCode="OWS",  # One-Way Survey
            TrackingTypeCode="NONE"       # No tracking
        )
        
        try:
            # Call Cint API to create entry link
            result = await self.cint_service.create_entry_link(
                survey_id=survey_id,
                link_config=link_config
            )
            
            if result.get("success"):
                self.stats["created"] += 1
                return {
                    "survey_id": survey_id,
                    "success": True,
                    "status": "created",
                    "live_link": result.get("data", {}).get("link", {}).get("live_link", "N/A"),
                    "message": "Entry link created successfully"
                }
            else:
                self.stats["failed"] += 1
                error_msg = result.get("message", "Unknown error")
                self.failed_surveys.append({
                    "survey_id": survey_id,
                    "survey_name": survey.get("survey_name", "N/A"),
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                })
                return {
                    "survey_id": survey_id,
                    "success": False,
                    "status": "failed",
                    "error": error_msg
                }
                
        except Exception as e:
            self.stats["failed"] += 1
            error_msg = str(e)
            self.failed_surveys.append({
                "survey_id": survey_id,
                "survey_name": survey.get("survey_name", "N/A"),
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            })
            return {
                "survey_id": survey_id,
                "success": False,
                "status": "exception",
                "error": error_msg
            }
            
    async def process_batch(self, batch: List[Dict[str, Any]], 
                           batch_num: int, total_batches: int) -> List[Dict[str, Any]]:
        """
        Process a batch of surveys with rate limiting
        
        Args:
            batch: List of survey documents
            batch_num: Current batch number
            total_batches: Total number of batches
            
        Returns:
            List of results
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def create_with_limit(survey: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                return await self.create_entry_link(survey)
        
        # Process surveys in parallel (with semaphore limiting concurrency)
        tasks = [create_with_limit(survey) for survey in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successes in this batch
        success_count = sum(
            1 for r in results 
            if isinstance(r, dict) and r.get("success")
        )
        
        print(f"  Batch {batch_num}/{total_batches}: {success_count}/{len(batch)} successful")
        
        return results
        
    async def generate_all_links(self, surveys: List[Dict[str, Any]]):
        """
        Generate entry links for all surveys
        
        Args:
            surveys: List of survey documents
        """
        self.stats["total"] = len(surveys)
        
        if self.dry_run:
            print(f"\n🔍 DRY RUN MODE - Would process {len(surveys)} surveys")
            print(f"  • Max concurrent API calls: {self.max_concurrent}")
            print(f"  • Batch size: {self.batch_size}")
            print(f"  • Delay between batches: {BATCH_DELAY_SECONDS}s")
            print("\nSample surveys to process:")
            for i, survey in enumerate(surveys[:5], 1):
                print(f"  {i}. Survey ID: {survey['survey_id']} - {survey.get('survey_name', 'N/A')}")
            if len(surveys) > 5:
                print(f"  ... and {len(surveys) - 5} more")
            return
            
        print(f"\n🚀 Starting bulk entry link generation...")
        print(f"  • Total surveys: {len(surveys)}")
        print(f"  • Max concurrent: {self.max_concurrent}")
        print(f"  • Batch size: {self.batch_size}")
        print(f"  • Delay between batches: {BATCH_DELAY_SECONDS}s")
        
        start_time = datetime.now()
        
        # Process in batches
        total_batches = (len(surveys) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(surveys), self.batch_size):
            batch = surveys[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            
            print(f"\n📦 Processing batch {batch_num}/{total_batches}...")
            
            await self.process_batch(batch, batch_num, total_batches)
            
            # Delay between batches (except last batch)
            if i + self.batch_size < len(surveys):
                await asyncio.sleep(BATCH_DELAY_SECONDS)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Print summary
        print("\n" + "="*60)
        print("✓ BULK GENERATION COMPLETE")
        print("="*60)
        print(f"Total surveys processed: {self.stats['total']}")
        print(f"✓ Successfully created: {self.stats['created']}")
        print(f"⊙ Already existed: {self.stats['already_exists']}")
        print(f"⊘ Skipped: {self.stats['skipped']}")
        print(f"✗ Failed: {self.stats['failed']}")
        print(f"Duration: {duration:.1f}s ({self.stats['total'] / duration:.1f} surveys/sec)")
        print("="*60)
        
        # Save failed surveys to CSV
        if self.failed_surveys:
            self.save_failed_surveys()
            
    def save_failed_surveys(self):
        """Save failed surveys to CSV file for review"""
        filename = f"failed_entry_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = os.path.join(os.path.dirname(__file__), filename)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['survey_id', 'survey_name', 'error', 'timestamp'])
            writer.writeheader()
            writer.writerows(self.failed_surveys)
        
        print(f"\n⚠️  Failed surveys saved to: {filepath}")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Bulk generate entry links for Cint surveys"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="Preview which surveys would get links without making API calls"
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=DEFAULT_MAX_CONCURRENT,
        help=f"Maximum concurrent API calls (default: {DEFAULT_MAX_CONCURRENT})"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Process N surveys per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--include-pool",
        action="store_true",
        help="Only process surveys with is_active_in_pool=True"
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("CINT BULK ENTRY LINK GENERATOR")
    print("="*60)
    
    # Validate environment variables
    if not CINT_API_KEY:
        print("❌ Error: CINT_API_KEY not found in environment variables")
        sys.exit(1)
    if not CINT_SUPPLIER_CODE:
        print("❌ Error: CINT_SUPPLIER_CODE not found in environment variables")
        sys.exit(1)
    
    print(f"✓ API Key: {CINT_API_KEY[:10]}...")
    print(f"✓ Supplier Code: {CINT_SUPPLIER_CODE}")
    print(f"✓ Base URL: {CINT_BASE_URL}")
    
    # Initialize generator
    generator = BulkEntryLinkGenerator(
        max_concurrent=args.max_concurrent,
        batch_size=args.batch_size,
        dry_run=args.dry_run
    )
    
    try:
        # Initialize service
        await generator.initialize_service()
        
        # Get surveys without links
        surveys = generator.get_surveys_without_links(
            active_only=True,
            include_pool_only=args.include_pool
        )
        
        if not surveys:
            print("\n✓ All active surveys already have entry links!")
            return
        
        # Generate links
        await generator.generate_all_links(surveys)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        await generator.close_service()
        print("\n✓ Cleanup complete")


if __name__ == "__main__":
    asyncio.run(main())
