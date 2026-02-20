#!/usr/bin/env python3
"""Check survey 71866995 details to diagnose 403 error"""
import requests
import json

headers = {
    'Authorization': 'C61C48A6-8154-4F9F-B616-8DFB66F452A7',
    'Content-Type': 'application/json'
}
base = 'https://api.samplicio.us'

# Check survey 71866995 details
print("=== Survey 71866995 Details ===")
r = requests.get(f'{base}/Supply/v1/Surveys/BySurveyNumber/71866995/6777', headers=headers)
print(f'Status: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    survey = data.get('Survey', {})
    for k in ['SurveyName', 'SurveyStatusCode', 'CountryLanguageID', 'IsActive', 
               'BidIncidence', 'BidLengthOfInterview', 'SurveyStillLive', 'Conversion', 'CPI', 'EPC']:
        print(f'  {k}: {survey.get(k)}')
else:
    print(f'  Survey NOT FOUND (404) - survey has been CLOSED/REMOVED')
    print(f'  Response: {r.text[:200]}')
print()

# Check SupplierLink for this survey
print("=== SupplierLink for 71866995 ===")
r2 = requests.get(f'{base}/Supply/v1/SupplierLinks/BySurveyNumber/71866995/6777', headers=headers)
print(f'Status: {r2.status_code}')
if r2.status_code == 200:
    data2 = r2.json()
    link = data2.get('SupplierLink', {})
    for k in ['SupplierLinkTypeCode', 'TrackingTypeCode', 'LiveLink', 'TestLink', 'CPI']:
        print(f'  {k}: {link.get(k)}')
else:
    print(f'  SupplierLink NOT FOUND')
print()

# Check if this survey is still in the offerwall
print("=== Survey in Offerwall? ===")
r5 = requests.get(f'{base}/Supply/v1/Surveys/AllOfferwall/6777', headers=headers)
if r5.status_code == 200:
    data5 = r5.json()
    surveys = data5.get('Surveys', [])
    found = [s for s in surveys if s.get('SurveyNumber') == 71866995]
    print(f'  Total offerwall surveys: {len(surveys)}')
    if found:
        print(f'  Survey 71866995 FOUND in offerwall')
        s = found[0]
        for k in ['SurveyName', 'SurveyStatusCode', 'CountryLanguageID', 'BidIncidence', 'Conversion', 'CPI', 'EPC']:
            print(f'    {k}: {s.get(k)}')
    else:
        print(f'  Survey 71866995 NOT IN offerwall (confirmed closed)')
print()

# Check Indian surveys from offerwall
print("=== Indian Surveys (CountryLanguageID=7) from Offerwall ===")
if r5.status_code == 200:
    indian_surveys = [s for s in surveys if s.get('CountryLanguageID') == 7]
    print(f'  Total Indian surveys: {len(indian_surveys)}')
    for s in indian_surveys[:10]:
        print(f'  - Survey {s.get("SurveyNumber")}: CPI=${s.get("CPI")}, Incidence={s.get("BidIncidence")}%, LOI={s.get("BidLengthOfInterview")}min, Conversion={s.get("Conversion")}%')
print()

# Quick test: create a supplier link for a LIVE survey from offerwall
if r5.status_code == 200 and indian_surveys:
    test_survey = indian_surveys[0]
    sn = test_survey['SurveyNumber']
    print(f"=== Test Create SupplierLink for LIVE Survey {sn} ===")
    payload = {
        "SupplierLinkTypeCode": "OWS",
        "TrackingTypeCode": "NONE",
        "DefaultLink": "https://torpedo.cogentixresearch.com/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]&reason=default_link",
        "SuccessLink": "https://torpedo.cogentixresearch.com/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]",
        "FailureLink": "https://torpedo.cogentixresearch.com/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]",
        "OverQuotaLink": "https://torpedo.cogentixresearch.com/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]",
        "QualityTerminationLink": "https://torpedo.cogentixresearch.com/cint-response?status=quality_terminate&pid=[%PID%]&mid=[%MID%]"
    }
    r6 = requests.post(f'{base}/Supply/v1/SupplierLinks/Create/{sn}/6777', headers=headers, json=payload)
    print(f'  Status: {r6.status_code}')
    if r6.status_code in (200, 409):
        try:
            data6 = r6.json()
            link = data6.get('SupplierLink', {})
            print(f'  LiveLink: {link.get("LiveLink")}')
            print(f'  TestLink: {link.get("TestLink")}')
            print(f'  CPI: {link.get("CPI")}')
        except:
            print(f'  Response: {r6.text[:300]}')
        
        # Now verify this survey is accessible via BySurveyNumber
        r7 = requests.get(f'{base}/Supply/v1/Surveys/BySurveyNumber/{sn}/6777', headers=headers)
        print(f'  Survey API status: {r7.status_code}')
        if r7.status_code == 200:
            d7 = r7.json().get('Survey', {})
            print(f'  SurveyStatusCode: {d7.get("SurveyStatusCode")}')
            print(f'  IsActive: {d7.get("IsActive")}')
    elif r6.status_code == 404:
        print(f'  FAILED - survey may have closed')
    else:
        try:
            print(f'  Response: {r6.text[:300]}')
        except:
            pass
