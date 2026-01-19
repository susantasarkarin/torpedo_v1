#!/usr/bin/env python3
"""Check email body structure - find conversation threads"""

from database import get_database
import re

db = get_database('torpedo_gmail')

# Find emails with quoted content (conversation threads)
quoted_markers = ['wrote:', '-----Original Message-----', 'From:', 'On ']

# Search for emails with quoted content
sample = db.email_metadata.find_one({
    'body_plain': {'$regex': 'wrote:|-----Original Message-----|On .* wrote'}
})

if sample:
    body = sample.get('body_plain', '')
    print(f"SUBJECT: {sample.get('subject', 'N/A')}")
    print(f"FROM: {sample.get('from_email', 'N/A')}")
    print(f"BODY LENGTH: {len(body)} characters")
    print()
    print("=" * 60)
    print("FULL BODY (first 3000 chars):")
    print("=" * 60)
    print(body[:3000])
else:
    # Try another pattern
    sample = db.email_metadata.find_one({
        'body_plain': {'$regex': '>'}
    })
    if sample:
        body = sample.get('body_plain', '')
        print(f"SUBJECT: {sample.get('subject', 'N/A')}")
        print(f"FROM: {sample.get('from_email', 'N/A')}")
        print(f"BODY LENGTH: {len(body)} characters")
        print()
        print("=" * 60)
        print("FULL BODY (first 3000 chars):")
        print("=" * 60)
        print(body[:3000])
    else:
        print("No conversation threads found")
