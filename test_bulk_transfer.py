#!/usr/bin/env python3
"""
Comprehensive test suite for Issue #1: Bulk Transfer to Vendor List
Tests executed against production server at 139.59.32.72:8000
"""

import requests
import json
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import time

# Configuration
PROD_SERVER = "http://139.59.32.72:8000"
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "email_automation"

# Test results tracking
results = {}

def get_mongo_client():
    """Connect to MongoDB"""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()  # Check connection
        return client
    except Exception as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        return None

def get_valid_lead_ids(count=10):
    """Get valid lead IDs from MongoDB leads_enriched collection"""
    try:
        client = get_mongo_client()
        if not client:
            return []
        
        db = client[DB_NAME]
        leads_collection = db["leads_enriched"]
        
        # Get leads that are NOT already transferred AND have email addresses
        leads = list(leads_collection.find(
            {"transferred_to_vendor_leads": {"$ne": True}, "email": {"$ne": None}},
            {"_id": 1}
        ).limit(count))
        
        lead_ids = [str(lead["_id"]) for lead in leads]
        print(f"✅ Retrieved {len(lead_ids)} valid lead IDs from MongoDB (with email)")
        return lead_ids
    except Exception as e:
        print(f"❌ Failed to get lead IDs: {e}")
        return []

def test_1_single_lead_transfer():
    """TEST 1: Single Lead Transfer"""
    print("\n" + "="*60)
    print("TEST 1: Single Lead Transfer")
    print("="*60)
    
    try:
        # Get a valid lead ID
        lead_ids = get_valid_lead_ids(1)
        if not lead_ids:
            results["TEST_1_SINGLE_TRANSFER"] = "FAIL | No valid lead IDs available"
            return
        
        lead_id = lead_ids[0]
        print(f"Using lead ID: {lead_id}")
        
        # Execute transfer
        payload = {
            "lead_id": lead_id,
            "source_collection": "leads_enriched"
        }
        
        response = requests.post(
            f"{PROD_SERVER}/vendor-leads/transfer-from-ai-database",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                results["TEST_1_SINGLE_TRANSFER"] = f"PASS | Status: {response.status_code}, Lead transferred successfully"
            else:
                results["TEST_1_SINGLE_TRANSFER"] = f"FAIL | Status: {response.status_code}, Success flag not true"
        else:
            error_msg = response.json().get("detail", response.text) if response.text else "Unknown error"
            results["TEST_1_SINGLE_TRANSFER"] = f"FAIL | Status: {response.status_code}, Error: {error_msg}"
    
    except Exception as e:
        results["TEST_1_SINGLE_TRANSFER"] = f"FAIL | Exception: {str(e)}"

def test_2_bulk_transfer_10_leads():
    """TEST 2: Bulk Transfer with 10 Leads"""
    print("\n" + "="*60)
    print("TEST 2: Bulk Transfer with 10 Leads")
    print("="*60)
    
    try:
        # Get 10 valid lead IDs
        lead_ids = get_valid_lead_ids(10)
        if len(lead_ids) < 1:
            results["TEST_2_BULK_10_LEADS"] = "FAIL | Less than 1 valid lead ID available"
            return
        
        print(f"Using {len(lead_ids)} lead IDs")
        
        # Execute bulk transfer
        payload = {
            "lead_ids": lead_ids,
            "source_collection": "leads_enriched"
        }
        
        response = requests.post(
            f"{PROD_SERVER}/vendor-leads/bulk-transfer-from-ai-database",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            transferred = data.get("transferred", 0)
            skipped = data.get("skipped", 0)
            total = data.get("total", 0)
            
            if transferred >= 1:
                results["TEST_2_BULK_10_LEADS"] = f"PASS | Transferred: {transferred}, Skipped: {skipped}, Total: {total}"
            else:
                results["TEST_2_BULK_10_LEADS"] = f"FAIL | No leads transferred. Skipped: {skipped}, Errors: {data.get('errors', [])[:3]}"
        else:
            error_msg = response.json().get("detail", response.text) if response.text else "Unknown error"
            results["TEST_2_BULK_10_LEADS"] = f"FAIL | Status: {response.status_code}, Error: {error_msg}"
    
    except Exception as e:
        results["TEST_2_BULK_10_LEADS"] = f"FAIL | Exception: {str(e)}"

def test_3_duplicate_email_prevention():
    """TEST 3: Duplicate Email Prevention"""
    print("\n" + "="*60)
    print("TEST 3: Duplicate Email Prevention")
    print("="*60)
    
    try:
        # Get a fresh valid lead ID (not yet transferred)
        lead_ids = get_valid_lead_ids(1)
        if not lead_ids:
            results["TEST_3_DUPLICATE_PREVENTION"] = "FAIL | No valid lead IDs available"
            return
        
        lead_id = lead_ids[0]
        print(f"Using fresh lead ID: {lead_id}")
        
        # First transfer
        payload = {
            "lead_id": lead_id,
            "source_collection": "leads_enriched"
        }
        
        response1 = requests.post(
            f"{PROD_SERVER}/vendor-leads/transfer-from-ai-database",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"First transfer - Status Code: {response1.status_code}")
        
        if response1.status_code != 200:
            results["TEST_3_DUPLICATE_PREVENTION"] = f"FAIL | First transfer failed: {response1.status_code}"
            return
        
        # Second transfer (should fail because already transferred)
        time.sleep(1)  # Small delay
        response2 = requests.post(
            f"{PROD_SERVER}/vendor-leads/transfer-from-ai-database",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"Second transfer - Status Code: {response2.status_code}")
        print(f"Response: {response2.text[:500]}")
        
        # Second transfer should fail (400 or similar)
        if response2.status_code >= 400:
            error_msg = response2.json().get("detail", "Already transferred")
            results["TEST_3_DUPLICATE_PREVENTION"] = f"PASS | Duplicate prevention working - Error: {error_msg}"
        else:
            results["TEST_3_DUPLICATE_PREVENTION"] = f"FAIL | Second transfer succeeded when it should fail (Status: {response2.status_code})"
    
    except Exception as e:
        results["TEST_3_DUPLICATE_PREVENTION"] = f"FAIL | Exception: {str(e)}"

def test_4_field_mapping_verification():
    """TEST 4: Field Mapping Verification"""
    print("\n" + "="*60)
    print("TEST 4: Field Mapping Verification")
    print("="*60)
    
    required_fields = ["email", "name", "company", "phone", "linkedin_url", "title", "industry"]
    
    try:
        # Get latest vendor_leads
        client = get_mongo_client()
        if not client:
            results["TEST_4_FIELD_MAPPING"] = "FAIL | Cannot connect to MongoDB"
            return
        
        db = client["email_automation"]
        vendor_leads_collection = db["vendor_leads"]
        
        # Get recently transferred leads (from last test)
        recent_leads = list(vendor_leads_collection.find(
            {"transferred_from_ai_database": True}
        ).sort("created_at", -1).limit(10))
        
        if not recent_leads:
            results["TEST_4_FIELD_MAPPING"] = "FAIL | No transferred leads found in vendor_leads collection"
            return
        
        print(f"Found {len(recent_leads)} recently transferred leads")
        
        # Check fields in all recent leads
        missing_fields_list = []
        fields_present = []
        
        for sample_lead in recent_leads[:3]:  # Check first 3
            missing_fields = []
            
            for field in required_fields:
                if field not in sample_lead or not sample_lead[field]:
                    missing_fields.append(field)
                else:
                    if field not in fields_present:
                        fields_present.append(field)
            
            if missing_fields:
                missing_fields_list.extend(missing_fields)
        
        # Check if all required fields are present in at least some leads
        all_fields_present = all(field in fields_present for field in required_fields)
        
        if all_fields_present:
            results["TEST_4_FIELD_MAPPING"] = f"PASS | All required fields present in vendor leads"
        else:
            missing = set(missing_fields_list)
            results["TEST_4_FIELD_MAPPING"] = f"FAIL | Missing fields: {', '.join(missing)}"
    
    except Exception as e:
        results["TEST_4_FIELD_MAPPING"] = f"FAIL | Exception: {str(e)}"

def test_5_transfer_flag_tracking():
    """TEST 5: Transfer Flag Tracking"""
    print("\n" + "="*60)
    print("TEST 5: Transfer Flag Tracking")
    print("="*60)
    
    try:
        client = get_mongo_client()
        if not client:
            results["TEST_5_TRANSFER_FLAGS"] = "FAIL | Cannot connect to MongoDB"
            return
        
        db = client["email_automation"]
        leads_collection = db["leads_enriched"]
        
        # Find a recently transferred lead
        transferred_lead = leads_collection.find_one(
            {"transferred_to_vendor_leads": True},
            sort=[("transferred_at", -1)]
        )
        
        if not transferred_lead:
            results["TEST_5_TRANSFER_FLAGS"] = "FAIL | No transferred leads found in source collection"
            return
        
        print(f"Found transferred lead: {transferred_lead.get('name')}")
        print(f"Transferred flag: {transferred_lead.get('transferred_to_vendor_leads')}")
        print(f"Transferred at: {transferred_lead.get('transferred_at')}")
        print(f"Vendor lead ID: {transferred_lead.get('vendor_lead_id')}")
        
        # Check flags and timestamp
        has_flag = transferred_lead.get("transferred_to_vendor_leads") == True
        has_timestamp = "transferred_at" in transferred_lead and transferred_lead["transferred_at"] is not None
        has_vendor_id = "vendor_lead_id" in transferred_lead and transferred_lead["vendor_lead_id"]
        
        if has_flag and has_timestamp and has_vendor_id:
            results["TEST_5_TRANSFER_FLAGS"] = f"PASS | All tracking flags present. Transferred at: {transferred_lead.get('transferred_at')}"
        else:
            missing = []
            if not has_flag:
                missing.append("transferred_to_vendor_leads flag")
            if not has_timestamp:
                missing.append("transferred_at timestamp")
            if not has_vendor_id:
                missing.append("vendor_lead_id")
            results["TEST_5_TRANSFER_FLAGS"] = f"FAIL | Missing: {', '.join(missing)}"
    
    except Exception as e:
        results["TEST_5_TRANSFER_FLAGS"] = f"FAIL | Exception: {str(e)}"

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("BULK TRANSFER TESTING - ISSUE #1")
    print("Production Server: 139.59.32.72:8000")
    print("="*60)
    
    # Execute all tests
    test_1_single_lead_transfer()
    test_2_bulk_transfer_10_leads()
    test_3_duplicate_email_prevention()
    test_4_field_mapping_verification()
    test_5_transfer_flag_tracking()
    
    # Print results table
    print("\n" + "="*60)
    print("TEST RESULTS SUMMARY")
    print("="*60)
    
    result_order = [
        "TEST_1_SINGLE_TRANSFER",
        "TEST_2_BULK_10_LEADS",
        "TEST_3_DUPLICATE_PREVENTION",
        "TEST_4_FIELD_MAPPING",
        "TEST_5_TRANSFER_FLAGS"
    ]
    
    for test_name in result_order:
        if test_name in results:
            print(f"{test_name} | {results[test_name]}")
        else:
            print(f"{test_name} | FAIL | Test not executed")

if __name__ == "__main__":
    main()
