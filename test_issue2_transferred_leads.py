#!/usr/bin/env python3
"""
Test Script for Issue #2: Transferred Leads Visibility
Run this on production server at 139.59.32.72
"""

from pymongo import MongoClient
from datetime import datetime
import json

def test_1_query_transferred_leads():
    """TEST 1: Query Transferred Leads in MongoDB"""
    try:
        client = MongoClient('mongodb://localhost:27017/')
        db = client['email_automation']
        
        # Count transferred leads
        count = db.vendor_leads.count_documents({'transferred_from_ai_database': True})
        
        if count > 0:
            return f"PASS | Count: {count}"
        else:
            return f"FAIL | Count is 0"
    except Exception as e:
        return f"FAIL | Error: {str(e)}"

def test_2_verify_fields():
    """TEST 2: Verify All Fields Present"""
    required_fields = [
        'email', 'name', 'company', 'title', 'phone', 
        'linkedin_url', 'transferred_from_ai_database', 'transferred_at'
    ]
    
    try:
        client = MongoClient('mongodb://localhost:27017/')
        db = client['email_automation']
        
        # Get a sample of transferred leads
        leads = list(db.vendor_leads.find({'transferred_from_ai_database': True}).limit(10))
        
        if not leads:
            return "FAIL | No transferred leads found"
        
        # Check which fields are present across all leads
        missing_fields = []
        for field in required_fields:
            found = False
            for lead in leads:
                if field in lead and lead[field] is not None:
                    found = True
                    break
            if not found:
                missing_fields.append(field)
        
        if not missing_fields:
            return "PASS | All required fields present"
        else:
            return f"FAIL | Missing fields: {', '.join(missing_fields)}"
    except Exception as e:
        return f"FAIL | Error: {str(e)}"

def test_3_bidirectional_refs():
    """TEST 3: Bidirectional Reference"""
    try:
        client = MongoClient('mongodb://localhost:27017/')
        email_db = client['email_automation']
        ai_db = client['ai_database']
        
        # Find a transferred vendor lead with source_lead_id
        vendor_lead = email_db.vendor_leads.find_one({
            'transferred_from_ai_database': True,
            'source_lead_id': {'$exists': True}
        })
        
        if not vendor_lead:
            return "FAIL | No vendor lead with source_lead_id found"
        
        source_lead_id = vendor_lead.get('source_lead_id')
        vendor_lead_id = str(vendor_lead.get('_id'))
        
        # Check if source lead exists and has vendor_lead_id
        from bson import ObjectId
        try:
            source_id_obj = ObjectId(source_lead_id)
        except:
            source_id_obj = source_lead_id
            
        source_lead = ai_db.leads_enriched.find_one({'_id': source_id_obj})
        
        if not source_lead:
            return f"FAIL | Source lead {source_lead_id} not found in leads_enriched"
        
        # Check if source lead has vendor_lead_id pointing back
        if 'vendor_lead_id' in source_lead:
            if str(source_lead['vendor_lead_id']) == vendor_lead_id:
                return f"PASS | Bidirectional link confirmed (IDs: {source_lead_id} <-> {vendor_lead_id})"
            else:
                return f"FAIL | vendor_lead_id mismatch: expected {vendor_lead_id}, got {source_lead['vendor_lead_id']}"
        else:
            return "FAIL | Source lead missing vendor_lead_id field"
            
    except Exception as e:
        return f"FAIL | Error: {str(e)}"

def test_4_ui_visibility():
    """TEST 4: UI Visibility Check"""
    return "NOTE_REQUIRES_MANUAL_CHECK | Please navigate to http://139.59.32.72:3000 -> AI Database -> Vendor List and verify transferred leads are visible"

def test_5_sales_linkage():
    """TEST 5: Sales Collection Linkage"""
    try:
        client = MongoClient('mongodb://localhost:27017/')
        sales_db = client['sales']
        
        # Check if transferred leads are linked to sales.leads
        lead = sales_db.leads.find_one({'enrichment_source': 'vendor_leads'})
        
        if lead:
            return f"PASS | Found lead in sales.leads with enrichment_source='vendor_leads'"
        else:
            # Also check for alternative linking methods
            count = sales_db.leads.count_documents({})
            return f"FAIL | No leads found with enrichment_source='vendor_leads' (Total leads in sales: {count})"
    except Exception as e:
        return f"FAIL | Error: {str(e)}"

def main():
    """Run all tests and output results"""
    print("=" * 80)
    print("ISSUE #2: TRANSFERRED LEADS VISIBILITY - TEST RESULTS")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80)
    print()
    
    tests = [
        ("TEST_1_QUERY_TRANSFERRED", test_1_query_transferred_leads),
        ("TEST_2_FIELDS_PRESENT", test_2_verify_fields),
        ("TEST_3_BIDIRECTIONAL_REFS", test_3_bidirectional_refs),
        ("TEST_4_UI_VISIBILITY", test_4_ui_visibility),
        ("TEST_5_SALES_LINKAGE", test_5_sales_linkage),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"Running {test_name}...")
        result = test_func()
        results.append(f"{test_name} | {result}")
        print(f"  Result: {result}")
        print()
    
    print("=" * 80)
    print("FINAL RESULTS (Copy this):")
    print("=" * 80)
    for result in results:
        print(result)
    
    # Save to file
    with open('issue2_test_results.txt', 'w') as f:
        f.write("ISSUE #2: TRANSFERRED LEADS VISIBILITY - TEST RESULTS\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write("=" * 80 + "\n\n")
        for result in results:
            f.write(result + "\n")
    
    print("\nResults saved to: issue2_test_results.txt")

if __name__ == "__main__":
    main()
