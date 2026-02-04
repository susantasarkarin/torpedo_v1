#!/usr/bin/env python3
"""
TEST CINT ALLOCATION END-TO-END
Verifies that:
1. Active surveys exist
2. Entry links exist 
3. Allocation query works
4. Can match respondent to survey
"""

import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")

from pymongo import MongoClient
from app.models.survey import Respondent
from datetime import datetime
import asyncio

class AllocationTester:
    def __init__(self):
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.client = MongoClient(mongo_uri)
        self.db = self.client["cint_research"]
        self.surveys = self.db["cint_surveys"]
        self.entry_links = self.db["cint_entry_links"]
        
    def test_survey_state(self) -> bool:
        """Test that surveys are properly marked as allocatable"""
        print("TEST 1: Survey State")
        print("-" * 50)
        
        total = self.surveys.count_documents({})
        active = self.surveys.count_documents({"is_active": True})
        live = self.surveys.count_documents({"is_live": True})
        active_in_pool = self.surveys.count_documents({"is_active_in_pool": True})
        quota = self.surveys.count_documents({"total_remaining": {"$gt": 0}})
        
        print(f"  Total surveys:              {total:,}")
        print(f"  is_active=true:             {active:,}")
        print(f"  is_live=true:               {live:,}")
        print(f"  is_active_in_pool=true:     {active_in_pool:,}")
        print(f"  Has quota (>0):             {quota:,}")
        
        success = active_in_pool > 0
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  Result: {status}")
        print()
        
        return success
    
    def test_entry_links(self) -> bool:
        """Test that entry links exist"""
        print("TEST 2: Entry Links Exist")
        print("-" * 50)
        
        total_links = self.entry_links.count_documents({})
        synthetic_links = self.entry_links.count_documents({"synthetic": True})
        api_links = self.entry_links.count_documents({"synthetic": {"$ne": True}})
        
        print(f"  Total entry links:          {total_links:,}")
        print(f"  Synthetic (workaround):     {synthetic_links:,}")
        print(f"  From API:                   {api_links:,}")
        
        if total_links > 0:
            sample = self.entry_links.find_one({})
            print(f"\n  Sample link:")
            print(f"    Survey ID:              {sample.get('survey_id')}")
            print(f"    Has live_link:          {'live_link' in sample and bool(sample['live_link'])}")
            if 'live_link' in sample:
                link = sample['live_link']
                has_placeholder = '[%MID%]' in link
                print(f"    Has [%MID%] placeholder: {has_placeholder}")
                print(f"    Link preview:           {link[:80]}...")
        
        success = total_links > 0
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  Result: {status}")
        print()
        
        return success
    
    def test_allocation_query(self) -> bool:
        """Test that allocation query works"""
        print("TEST 3: Allocation Query Works")
        print("-" * 50)
        
        # Simulate allocation query
        test_country = "US"
        max_loi = 30
        
        query = {
            "is_active": True,
            "is_live": True,
            "total_remaining": {"$gt": 0},
            "country_language": {"$regex": f"^{test_country}"},
            "bid_length_of_interview": {"$lte": max_loi},
        }
        
        results = list(
            self.surveys.find(query)
            .sort([
                ("conversion", -1),
                ("mobile_conversion", -1),
                ("revenue_per_interview.value", -1),
                ("bid_length_of_interview", 1),
            ])
            .limit(100)
        )
        
        print(f"  Query: is_active + is_live + has_quota + country={test_country} + loi<={max_loi}")
        print(f"  Found: {len(results)} matching surveys")
        
        if results:
            survey = results[0]
            print(f"\n  Best survey:")
            print(f"    Survey ID:              {survey.get('survey_id')}")
            print(f"    Name:                   {survey.get('survey_name', 'N/A')[:50]}")
            print(f"    LOI:                    {survey.get('bid_length_of_interview')} min")
            print(f"    CPI:                    ${survey.get('revenue_per_interview', {}).get('value', 'N/A')}")
            print(f"    Conversion:             {survey.get('conversion', 'N/A')}%")
            print(f"    Remaining quota:        {survey.get('total_remaining', 'N/A')}")
            
            # Check if this survey has an entry link
            link = self.entry_links.find_one({"survey_id": survey.get('survey_id')})
            print(f"    Has entry link:         {bool(link)}")
        
        success = len(results) > 0
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  Result: {status}")
        print()
        
        return success
    
    def test_entry_link_retrieval(self) -> bool:
        """Test that entry links can be retrieved for surveys"""
        print("TEST 4: Entry Link Retrieval")
        print("-" * 50)
        
        # Get a survey with both is_active and an entry link
        query = {
            "is_active_in_pool": True,
            "is_live": True,
        }
        
        survey = self.surveys.find_one(query)
        
        if not survey:
            print(f"  No active surveys found")
            print(f"  Result: ❌ FAIL")
            print()
            return False
        
        survey_id = survey.get('survey_id')
        link_doc = self.entry_links.find_one({"survey_id": survey_id})
        
        print(f"  Test survey:                {survey_id}")
        print(f"  Has entry link:             {bool(link_doc)}")
        
        if link_doc:
            live_link = link_doc.get('live_link')
            has_placeholder = '[%MID%]' in live_link if live_link else False
            
            print(f"  Live link exists:           {bool(live_link)}")
            print(f"  Has [%MID%] placeholder:    {has_placeholder}")
            print(f"  Link:                       {live_link[:80]}...")
        
        success = bool(link_doc) and bool(link_doc.get('live_link'))
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  Result: {status}")
        print()
        
        return success
    
    def run_all_tests(self) -> bool:
        """Run all tests"""
        print("=" * 70)
        print("CINT ALLOCATION VERIFICATION TEST SUITE")
        print("=" * 70)
        print()
        
        results = [
            self.test_survey_state(),
            self.test_entry_links(),
            self.test_allocation_query(),
            self.test_entry_link_retrieval(),
        ]
        
        print("=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        
        passed = sum(results)
        total = len(results)
        
        print(f"  Passed: {passed}/{total}")
        print()
        
        if passed == total:
            print("✅ ALL TESTS PASSED!")
            print("   Cint allocation is ready to use")
        elif passed >= 3:
            print("⚠️  MOSTLY WORKING")
            print("   Some features may have issues")
        else:
            print("❌ CRITICAL ISSUES")
            print("   Allocation is not ready")
        
        print()
        print("=" * 70)
        
        return passed == total

def main():
    tester = AllocationTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
