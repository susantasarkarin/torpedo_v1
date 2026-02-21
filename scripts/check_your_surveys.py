#!/usr/bin/env python3
"""Check YOUR surveys on offerwall"""
import os
import httpx

dotenv = {}
for line in open('.env'):
    if '=' in line and not line.startswith('#'):
        k, v = line.strip().split('=', 1)
        dotenv[k] = v

api_key = dotenv.get('CINT_API_KEY')
supplier_code = dotenv.get('CINT_SUPPLIER_CODE', '6777')
headers = {'Authorization': api_key, 'Accept': 'application/json'}

# Fetch offerwall
url = f'https://api.samplicio.us/Supply/v1/Surveys/AllOfferwall/{supplier_code}'
with httpx.Client(timeout=30) as client:
    resp = client.get(url, headers=headers)
    surveys = resp.json().get('Surveys', [])

# Your surveys
your_ids = ['74443076', '74443025', '74443018']

print('=== YOUR SURVEYS ON OFFERWALL ===')
for s in surveys:
    sid = str(s.get('SurveyNumber'))
    if sid in your_ids:
        print(f'\nSurvey {sid}:')
        print(f'  CountryLanguageID: {s.get("CountryLanguageID")}')
        print(f'  IR: {s.get("IncidenceRate")}%')
        print(f'  LOI: {s.get("LOI")} min')
        print(f'  CPI: ${s.get("CPI")}')
        print(f'  Quota Remaining: {s.get("SurveyQuotaRemaining")}')

# Summary
print('\n=== SUMMARY ===')
offerwall_ids = set(str(s.get('SurveyNumber')) for s in surveys)
for sid in your_ids:
    status = 'ON OFFERWALL' if sid in offerwall_ids else 'NOT ON OFFERWALL'
    print(f'{sid}: {status}')

# How many US surveys exist?
us_surveys = [s for s in surveys if s.get('CountryLanguageID') == 9]
print(f'\nTotal US surveys on offerwall: {len(us_surveys)}')

# Sample top-paying US surveys
us_sorted = sorted(us_surveys, key=lambda x: x.get('CPI', 0), reverse=True)
print(f'Top 5 paying US surveys:')
for s in us_sorted[:5]:
    print(f'  {s.get("SurveyNumber")}: CPI=${s.get("CPI")}, IR={s.get("IncidenceRate")}%')
