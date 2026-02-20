#!/usr/bin/env python3
"""Update a CINT SupplierLink's callback URLs"""
import httpx
import os
import sys
import json

CINT_API_BASE = "https://api.samplicio.us"
api_key = os.getenv("CINT_API_KEY", "C61C48A6-8154-4F9F-B616-8DFB66F452A7")
supplier_code = os.getenv("CINT_SUPPLIER_CODE", "6777")
callback_base = "https://torpedo.cogentixresearch.com"

survey_id = sys.argv[1] if len(sys.argv) > 1 else "74002651"

headers = {
    "Authorization": api_key,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

payload = {
    "SupplierLinkTypeCode": "OWS",
    "TrackingTypeCode": "NONE",
    "DefaultLink": f"{callback_base}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]&reason=default_link",
    "SuccessLink": f"{callback_base}/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]",
    "FailureLink": f"{callback_base}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]",
    "OverQuotaLink": f"{callback_base}/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]",
    "QualityTerminationLink": f"{callback_base}/cint-response?status=quality_terminate&pid=[%PID%]&mid=[%MID%]",
}

print(f"Updating SupplierLink for survey {survey_id}...")
print(f"Payload: {json.dumps(payload, indent=2)}")

url = f"{CINT_API_BASE}/Supply/v1/SupplierLinks/Update/{survey_id}/{supplier_code}"
print(f"URL: {url}")

with httpx.Client(timeout=15.0) as client:
    resp = client.put(url, json=payload, headers=headers)
    print(f"\nResponse status: {resp.status_code}")
    print(f"Response body: {json.dumps(resp.json(), indent=2)}")
    
    # Verify by GET
    print(f"\nVerifying with GET...")
    get_url = f"{CINT_API_BASE}/Supply/v1/SupplierLinks/BySurveyNumber/{survey_id}/{supplier_code}"
    get_resp = client.get(get_url, headers=headers)
    if get_resp.status_code == 200:
        sl = get_resp.json().get("SupplierLink", {})
        print(f"DefaultLink: {sl.get('DefaultLink')}")
        print(f"FailureLink: {sl.get('FailureLink')}")
        print(f"SuccessLink: {sl.get('SuccessLink')}")
    else:
        print(f"GET failed: {get_resp.status_code}")
