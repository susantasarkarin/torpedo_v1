#!/usr/bin/env python3
"""Test the lead detail API"""
import json
import sys

try:
    data = json.load(sys.stdin)
    lead = data.get("lead", {})
    
    print("Email count:", lead.get("email_count", 0))
    print("Emails:", len(lead.get("emails", [])))
    print("Timeline:", len(lead.get("timeline", [])))
    summary = lead.get("conversation_summary", "N/A")
    print("Summary:", summary[:150] if summary else "N/A")
    
    # Print first 2 emails
    emails = lead.get("emails", [])[:2]
    for i, e in enumerate(emails):
        print(f"\nEmail {i+1}:")
        print(f"  Subject: {e.get('subject')}")
        print(f"  From: {e.get('from')}")
        print(f"  Date: {e.get('date')}")
        print(f"  Direction: {e.get('direction')}")
    
    # Print first 3 timeline events
    timeline = lead.get("timeline", [])[:3]
    for i, t in enumerate(timeline):
        print(f"\nTimeline {i+1}:")
        print(f"  Type: {t.get('type')}")
        print(f"  Title: {t.get('title')}")
        print(f"  Date: {t.get('date')}")
except Exception as e:
    print(f"Error: {e}")
