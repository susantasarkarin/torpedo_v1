#!/usr/bin/env python3
"""
RECLASSIFY GMAIL LEADS WITH MISSING FIELDS
==========================================

This script finds Gmail leads that are marked as "classified" but have blank
enrichment fields (seniority_level, department, persona, etc.) and reclassifies
them using the AI classifier to populate all fields.

Run this script to fix existing Gmail leads that were classified before the
canonical_ingestion.py update.

Usage:
    python scripts/reclassify_gmail_leads.py [--limit N] [--dry-run]

Options:
    --limit N    Only process N leads (default: all)
    --dry-run    Show what would be done without making changes
"""

import os
import sys
import argparse
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']
leads_raw = db['leads_raw']
leads_enriched = db['leads_enriched']

# Gmail sources
GMAIL_SOURCES = ["gmail", "gmail_workspace", "email_sync", "email_import", 
                 "email_classification", "gmail_api", "gmail_archive"]


def find_gmail_leads_with_missing_fields():
    """Find Gmail leads that are 'classified' but have no enrichment fields."""
    query = {
        'source': {'$in': GMAIL_SOURCES},
        '$or': [
            {'classification_status': 'classified'},
            {'classification': {'$in': ['client', 'vendor', 'unknown']}}
        ],
        # Missing any of the key enrichment fields
        '$and': [
            {'$or': [
                {'seniority_level': {'$exists': False}},
                {'seniority_level': None},
                {'seniority_level': ''}
            ]},
            {'$or': [
                {'department': {'$exists': False}},
                {'department': None},
                {'department': ''}
            ]},
            {'$or': [
                {'persona': {'$exists': False}},
                {'persona': None},
                {'persona': ''}
            ]}
        ]
    }
    
    return list(leads_raw.find(query))


def reclassify_lead(lead_doc, dry_run=False):
    """Reclassify a single lead with the AI classifier."""
    from leads.canonical_ingestion import classify_lead_ai, sync_to_enriched
    
    lead_id = str(lead_doc['_id'])
    email = lead_doc.get('email', 'unknown')
    
    print(f"  Processing: {email} (ID: {lead_id})")
    
    if dry_run:
        print(f"    [DRY-RUN] Would reclassify lead")
        return True
    
    try:
        # Call AI classification
        classification, confidence, full_result = classify_lead_ai(lead_doc)
        
        if not full_result:
            print(f"    ⚠ Classification failed (no result)")
            return False
        
        # Prepare update
        update_fields = {
            'classification': classification,
            'classification_confidence': confidence,
            'classification_status': 'classified',
            'seniority_level': full_result.get('seniority_level'),
            'department': full_result.get('department'),
            'persona': full_result.get('persona'),
            'buying_role': full_result.get('buying_role'),
            'gender': full_result.get('gender'),
            'company_size': full_result.get('company_size'),
            'region': full_result.get('region'),
            'confidence_score': full_result.get('confidence_score', confidence),
            'classified_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
        }
        
        # Add name fields if missing
        if full_result.get('first_name') and not lead_doc.get('first_name'):
            update_fields['first_name'] = full_result['first_name']
        if full_result.get('last_name') and not lead_doc.get('last_name'):
            update_fields['last_name'] = full_result['last_name']
        if full_result.get('inferred_location') and not lead_doc.get('location'):
            update_fields['location'] = full_result['inferred_location']
        
        # Add company fields
        if full_result.get('company_name'):
            update_fields['company'] = full_result['company_name']
            update_fields['company_name'] = full_result['company_name']
        if full_result.get('company_domain') and not lead_doc.get('company_domain'):
            update_fields['company_domain'] = full_result['company_domain']
        if full_result.get('company_website'):
            update_fields['company_website'] = full_result['company_website']
        if full_result.get('company_employee_count'):
            update_fields['company_employee_count'] = full_result['company_employee_count']
        if full_result.get('company_employee_count_range'):
            update_fields['company_employee_count_range'] = full_result['company_employee_count_range']
        if full_result.get('company_founded'):
            update_fields['company_founded'] = full_result['company_founded']
        if full_result.get('company_industry'):
            update_fields['company_industry'] = full_result['company_industry']
        if full_result.get('company_type'):
            update_fields['company_type'] = full_result['company_type']
        if full_result.get('company_headquarters'):
            update_fields['company_headquarters'] = full_result['company_headquarters']
        if full_result.get('company_revenue_range'):
            update_fields['company_revenue_range'] = full_result['company_revenue_range']
        if full_result.get('company_linkedin_url'):
            update_fields['company_linkedin_url'] = full_result['company_linkedin_url']
        
        # Update leads_raw
        leads_raw.update_one(
            {'_id': lead_doc['_id']},
            {'$set': update_fields}
        )
        
        # Merge with existing lead data for sync
        merged = {**lead_doc, **update_fields}
        
        # Sync to leads_enriched
        enriched_id = sync_to_enriched(merged, lead_id)
        if enriched_id:
            leads_raw.update_one(
                {'_id': lead_doc['_id']},
                {'$set': {'enriched_lead_id': enriched_id}}
            )
            print(f"    ✓ Reclassified: {classification} ({confidence:.2f}) -> enriched_id: {enriched_id}")
        else:
            print(f"    ✓ Reclassified: {classification} ({confidence:.2f}) [sync to enriched failed]")
        
        return True
        
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Reclassify Gmail leads with missing fields')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of leads to process')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()
    
    print("=" * 60)
    print("RECLASSIFY GMAIL LEADS WITH MISSING FIELDS")
    print("=" * 60)
    
    # Find leads to reclassify
    print("\nFinding Gmail leads with missing classification fields...")
    leads = find_gmail_leads_with_missing_fields()
    
    if args.limit:
        leads = leads[:args.limit]
    
    print(f"Found {len(leads)} leads to reclassify")
    
    if not leads:
        print("No leads need reclassification. Done!")
        return
    
    if args.dry_run:
        print("\n[DRY-RUN MODE - No changes will be made]")
    
    # Process leads
    print(f"\nProcessing {len(leads)} leads...")
    success = 0
    failed = 0
    
    for i, lead in enumerate(leads, 1):
        print(f"\n[{i}/{len(leads)}]")
        if reclassify_lead(lead, dry_run=args.dry_run):
            success += 1
        else:
            failed += 1
        
        # Rate limiting - pause every 10 leads
        if i % 10 == 0 and i < len(leads):
            import time
            print(f"  (Pausing 2s for rate limiting...)")
            time.sleep(2)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total processed: {len(leads)}")
    print(f"  Success: {success}")
    print(f"  Failed: {failed}")
    
    if args.dry_run:
        print("\n[DRY-RUN] No changes were made. Run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
