#!/usr/bin/env python3
"""Find mailbox email addresses from sent emails"""
from pymongo import MongoClient

db = MongoClient()['torpedo_gmail']

# Get unique from_email addresses that appear in sent emails (our mailboxes)
pipeline = [
    {'$match': {'direction': 'outbound'}},
    {'$group': {'_id': '$from_email', 'mailbox_id': {'$first': '$mailbox_id'}, 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}},
    {'$limit': 10}
]
results = list(db['email_metadata'].aggregate(pipeline))
print('Outbound emails (our mailboxes):')
for r in results:
    print(f"  {r['_id']} -> {r['mailbox_id']} ({r['count']} sent)")

# Also check inbound to find all unique mailbox IDs
print('\n\nAll mailbox emails:')
for mbid in db['email_metadata'].distinct('mailbox_id'):
    # Get the most common to_email for this mailbox (that's likely our email)
    pipeline2 = [
        {'$match': {'mailbox_id': mbid, 'direction': 'inbound'}},
        {'$unwind': '$to_emails'},
        {'$group': {'_id': '$to_emails', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': 3}
    ]
    to_emails = list(db['email_metadata'].aggregate(pipeline2))
    if to_emails:
        print(f"  Mailbox {mbid}: {to_emails[0]['_id']} ({to_emails[0]['count']} emails)")
