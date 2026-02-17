#!/usr/bin/env python3
"""Analyze most recent respondent's CPX and Cint survey participation."""

from pymongo import MongoClient

def main():
    client = MongoClient('mongodb://localhost:27017')
    db = client['campaign_platform']
    
    # Get most recent traffic record
    traffic = db.traffic_records.find_one({}, sort=[('created_at', -1)])
    
    if not traffic:
        print('No traffic records found')
        return
    
    rid = traffic.get('respondent_id', 'N/A')
    print('=' * 60)
    print('MOST RECENT RESPONDENT:', rid)
    print('=' * 60)
    print('Created:', traffic.get('created_at'))
    print('Provider:', traffic.get('provider'))
    print('Survey ID:', traffic.get('survey_id'))
    print('Status:', traffic.get('status'))
    print()
    
    # Find all records for this respondent
    all_records = list(db.traffic_records.find({'respondent_id': rid}).sort('created_at', 1))
    print('Total records for this respondent:', len(all_records))
    print()
    
    # Separate by provider
    cpx_surveys = [r for r in all_records if r.get('provider') == 'CPX']
    cint_surveys = [r for r in all_records if r.get('provider') == 'CINT']
    
    print('=== CPX SURVEYS ===')
    if cpx_surveys:
        for r in cpx_surveys:
            entry_link = r.get('entry_link', 'N/A')
            if entry_link and len(entry_link) > 60:
                entry_link = entry_link[:60] + '...'
            print(f"  Survey: {r.get('survey_id')} | Status: {r.get('status')}")
            print(f"    Entry Link: {entry_link}")
            print(f"    Created: {r.get('created_at')}")
    else:
        print('  (none)')
    
    print()
    print('=== CINT SURVEYS ===')
    if cint_surveys:
        for r in cint_surveys:
            entry_type = r.get('cint_entry_link_type', 'N/A')
            entry_link = r.get('entry_link', 'N/A')
            if entry_link and len(entry_link) > 60:
                entry_link = entry_link[:60] + '...'
            print(f"  Survey: {r.get('survey_id')} | Status: {r.get('status')} | Entry Type: {entry_type}")
            print(f"    Entry Link: {entry_link}")
            print(f"    Created: {r.get('created_at')}")
    else:
        print('  (none)')

if __name__ == '__main__':
    main()
