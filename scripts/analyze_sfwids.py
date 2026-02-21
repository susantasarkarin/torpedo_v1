#!/usr/bin/env python3
"""Analyze last N SFWIDs - Flow Analysis"""
from pymongo import MongoClient
from datetime import datetime

client = MongoClient('mongodb://localhost:27017/')
db = client['traffic_flow_db']

# Get last 20 traffic records
records = list(db.url_parameters.find().sort('_id', -1).limit(20))

print('=== LAST 20 SFWIDs - FLOW ANALYSIS ===\n')

# Table header
header = "{:<3} {:<26} {:<18} {:<4} {:<6} {:<12} {:<8} {:<36}".format(
    "#", "SFWID", "Status", "CC", "Source", "Survey", "HasRID", "RID")
print(header)
print('=' * 130)

for i, r in enumerate(records, 1):
    sfwid = str(r.get('_id'))[:24]
    status = str(r.get('status', 'UNKNOWN'))[:16]
    country = str(r.get('countryCode', '??'))[:4]
    source = str(r.get('surveySource', 'NONE'))[:6]
    survey = str(r.get('assignedSurveyId', '-'))[:12]
    
    # Check for RID
    rid = r.get('rid') or r.get('respondentId') or r.get('RID')
    has_rid = 'YES' if rid else 'NO'
    rid_str = str(rid)[:36] if rid else '-'
    
    row = "{:<3} {:<26} {:<18} {:<4} {:<6} {:<12} {:<8} {:<36}".format(
        i, sfwid, status, country, source, survey, has_rid, rid_str)
    print(row)

print('\n' + '=' * 130)
print('\n=== DETAILED FLOW CHECK ===\n')

# Check each record for proper flow
issues = []
good = []

for r in records:
    sfwid = str(r.get('_id'))
    status = r.get('status')
    rid = r.get('rid') or r.get('respondentId')
    vendor_id = r.get('vendorId') or r.get('vendor_id')
    survey_source = r.get('surveySource')
    assigned = r.get('assignedSurveyId')
    redirect_url = r.get('redirectUrl')
    cint_candidates = r.get('cintCandidateIds', [])
    
    flow_ok = True
    issue_details = []
    
    # Check 1: Has RID mapping
    if not rid:
        flow_ok = False
        issue_details.append('Missing RID')
    
    # Check 2: Has vendor ID
    if not vendor_id:
        flow_ok = False
        issue_details.append('Missing vendorId')
    
    # Check 3: For non-TERMINATED, should have redirect or assignment
    if status not in ['TERMINATED', 'NEW'] and not (redirect_url or assigned):
        flow_ok = False
        issue_details.append('No redirect/survey assigned')
    
    # Check 4: CINT waterfall should have candidates
    if 'CINT_WATERFALL' in str(status) and not cint_candidates:
        issue_details.append('Waterfall but no candidates stored')
    
    if flow_ok:
        good.append(sfwid[:24])
    else:
        issues.append((sfwid[:24], ', '.join(issue_details)))

print("Records with correct flow: {}/20".format(len(good)))
print("Records with issues: {}/20".format(len(issues)))

if issues:
    print('\nIssues found:')
    for sfwid, issue in issues[:10]:
        print("  {}: {}".format(sfwid, issue))

# Summary stats
print("\n=== STATUS BREAKDOWN ===")
from collections import Counter
statuses = Counter([r.get('status') for r in records])
for s, c in statuses.most_common():
    print("  {}: {}".format(s, c))
