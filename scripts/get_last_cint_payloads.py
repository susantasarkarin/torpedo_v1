#!/usr/bin/env python3
"""
Get Last N Cint Respondent Payloads

This script connects to MongoDB and retrieves the last N respondent payloads
that were sent to Cint. It reconstructs the full payload data including:
- survey_id
- supplier_code  
- respondent_id
- secure_hash (if available)
- return_url
- timestamp
- allocation details

Usage:
    python scripts/get_last_cint_payloads.py
    python scripts/get_last_cint_payloads.py --limit 20
    python scripts/get_last_cint_payloads.py --json output.json
    
Or on VM via SSH:
    ssh user@vm "cd /path/to/campaign_platform && python scripts/get_last_cint_payloads.py"
"""

import os
import sys
from pymongo import MongoClient
from datetime import datetime
from typing import List, Dict, Any
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def get_mongo_uri() -> str:
    """Get MongoDB URI from environment or use default"""
    return os.getenv('MONGO_URI', 'mongodb://localhost:27017/')

def format_timestamp(dt) -> str:
    """Format datetime to readable string"""
    if isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    return str(dt)

def get_last_cint_payloads(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Retrieve last N respondent payloads sent to Cint
    
    Args:
        limit: Number of records to retrieve (default: 10)
        
    Returns:
        List of payload dictionaries with full details
    """
    mongo_uri = get_mongo_uri()
    client = MongoClient(mongo_uri)
    
    # Access survey_allocation database
    survey_db = client['survey_allocation']
    allocation_log = survey_db['allocation_log']
    surveys_collection = survey_db['surveys']
    respondents_collection = survey_db['respondents']
    
    # Access cint_research database for additional Cint-specific data
    cint_db = client['cint_research']
    cint_surveys = cint_db['cint_surveys']
    
    payloads = []
    
    try:
        # Use aggregation pipeline to efficiently filter for CINT allocations
        # This joins with surveys collection and filters in the database
        pipeline = [
            # Sort by timestamp descending (most recent first)
            {'$sort': {'timestamp': -1}},
            
            # Join with surveys collection to get provider info
            {'$lookup': {
                'from': 'surveys',
                'localField': 'survey_id',
                'foreignField': '_id',
                'as': 'survey'
            }},
            
            # Unwind the survey array
            {'$unwind': {'path': '$survey', 'preserveNullAndEmptyArrays': False}},
            
            # Filter for CINT provider only
            {'$match': {'survey.provider': 'CINT'}},
            
            # Limit to requested number of results
            {'$limit': limit}
        ]
        
        cint_logs = list(allocation_log.aggregate(pipeline))
        
        # Build detailed payload information for each log
        for log in cint_logs:
            survey_id = log.get('survey_id')
            respondent_id = log.get('rid') or log.get('respondent_id')
            
            # Get survey details from the joined data
            survey = log.get('survey')
            external_survey_id = survey.get('external_id') if survey else None
            survey_name = survey.get('name') if survey else None
            
            # Get respondent details
            respondent = respondents_collection.find_one({'rid': respondent_id})
            
            # Try to get Cint survey details
            cint_survey = None
            if external_survey_id:
                cint_survey = cint_surveys.find_one({'survey_id': int(external_survey_id)})
            
            # Reconstruct the payload that was sent to Cint
            # Based on backend/routers/traffic.py lines 821-827
            payload = {
                'survey_id': str(external_survey_id) if external_survey_id else str(survey_id),
                'supplier_code': os.getenv('CINT_SUPPLIER_CODE', '6777'),
                'respondent_id': respondent_id,
                'secure_hash': '[HMAC-SHA256 hash - not stored]',
                'return_url': os.getenv('CINT_CALLBACK_URL', 'https://torpedo.cogentixresearch.com/api/cint/status'),
            }
            
            # Additional metadata
            metadata = {
                'timestamp': format_timestamp(log.get('timestamp')),
                'allocation_id': str(log.get('allocation_id', '')),
                'vid': log.get('vid'),
                'cc': log.get('cc'),
                'ip_address': log.get('ip_address'),
                'user_agent': log.get('user_agent'),
                'survey_name': survey_name,
                'survey_status': survey.get('status') if survey else None,
            }
            
            # Combine payload and metadata
            full_record = {
                'payload_sent_to_cint': payload,
                'metadata': metadata,
            }
            
            # Add Cint survey details if available
            if cint_survey:
                full_record['cint_survey_details'] = {
                    'survey_name': cint_survey.get('survey_name'),
                    'country_language': cint_survey.get('country_language'),
                    'loi': cint_survey.get('bid_length_of_interview'),
                    'cpi': cint_survey.get('revenue_per_interview', {}).get('value') if cint_survey.get('revenue_per_interview') else None,
                    'conversion': cint_survey.get('conversion'),
                }
            
            payloads.append(full_record)
        
        return payloads
        
    except Exception as e:
        print(f"Error retrieving payloads: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        client.close()

def print_payloads(payloads: List[Dict[str, Any]]):
    """Pretty print the payloads"""
    if not payloads:
        print("No Cint payloads found.")
        return
    
    print("=" * 80)
    print(f"LAST {len(payloads)} RESPONDENT PAYLOADS SENT TO CINT")
    print("=" * 80)
    print()
    
    for i, record in enumerate(payloads, 1):
        print(f"[{i}] Timestamp: {record['metadata']['timestamp']}")
        print("-" * 80)
        
        print("\nPayload sent to Cint API:")
        print("  POST https://api.samplicio.us/supply/v1/entrylinks")
        payload = record['payload_sent_to_cint']
        for key, value in payload.items():
            print(f"    {key}: {value}")
        
        print("\nMetadata:")
        metadata = record['metadata']
        for key, value in metadata.items():
            if key != 'timestamp':  # Already shown above
                print(f"    {key}: {value}")
        
        if 'cint_survey_details' in record:
            print("\nCint Survey Details:")
            details = record['cint_survey_details']
            for key, value in details.items():
                print(f"    {key}: {value}")
        
        print("\n" + "=" * 80)
        print()

def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Retrieve last N respondent payloads sent to Cint',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get last 10 payloads (default)
  python scripts/get_last_cint_payloads.py
  
  # Get last 20 payloads
  python scripts/get_last_cint_payloads.py --limit 20
  
  # Get payloads and save to JSON file
  python scripts/get_last_cint_payloads.py --json output.json
  
  # Run on VM via SSH
  ssh user@vm "cd /path/to/campaign_platform && python scripts/get_last_cint_payloads.py"
        """
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Number of payloads to retrieve (default: 10)'
    )
    
    parser.add_argument(
        '--json',
        type=str,
        help='Save output to JSON file instead of printing'
    )
    
    args = parser.parse_args()
    
    print(f"Connecting to MongoDB...")
    print(f"Retrieving last {args.limit} Cint respondent payloads...\n")
    
    payloads = get_last_cint_payloads(limit=args.limit)
    
    if args.json:
        # Save to JSON file
        with open(args.json, 'w') as f:
            json.dump(payloads, f, indent=2, default=str)
        print(f"Payloads saved to {args.json}")
    else:
        # Print to console
        print_payloads(payloads)
    
    print(f"\nTotal payloads retrieved: {len(payloads)}")

if __name__ == '__main__':
    main()
