#!/usr/bin/env python3
"""Check CINT inventory by country"""
import os
import httpx
from collections import Counter

# Load env manually
dotenv = {}
for line in open('.env'):
    if '=' in line and not line.startswith('#'):
        k, v = line.strip().split('=', 1)
        dotenv[k] = v

api_key = dotenv.get('CINT_API_KEY')
supplier_code = dotenv.get('CINT_SUPPLIER_CODE', '6777')

headers = {'Authorization': api_key, 'Accept': 'application/json'}
url = f'https://api.samplicio.us/Supply/v1/Surveys/AllOfferwall/{supplier_code}'

with httpx.Client(timeout=30) as client:
    resp = client.get(url, headers=headers)
    surveys = resp.json().get('Surveys', [])
    
print(f'Total surveys on offerwall: {len(surveys)}')

# Count by CountryLanguageID
by_country = Counter([s.get('CountryLanguageID') for s in surveys])

print(f'\nTop 15 countries by survey count:')
for clid, cnt in by_country.most_common(15):
    print(f'  CountryLanguageID={clid}: {cnt}')

# Key countries for our traffic
print(f'\n=== KEY COUNTRIES ===')
country_names = {7: 'India', 8: 'UK', 9: 'US', 5: 'AU/FR', 6: 'CA/ES', 4: 'DE'}
for clid, name in country_names.items():
    print(f'{name} (ID={clid}): {by_country.get(clid, 0)} surveys')
