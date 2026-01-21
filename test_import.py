#!/usr/bin/env python3
"""Test import of service module"""
try:
    from leads.service import get_enriched_lead_by_id
    print("Import OK")
    
    # Test the function
    lead = get_enriched_lead_by_id("696e32822cc37ab3836523b5")
    if lead:
        print(f"Lead found: {lead.get('name')}")
        print(f"Emails: {len(lead.get('emails', []))}")
        print(f"Timeline: {len(lead.get('timeline', []))}")
        print(f"Summary: {lead.get('conversation_summary', 'N/A')[:100]}")
    else:
        print("Lead not found")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
