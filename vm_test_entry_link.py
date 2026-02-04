import os
import requests
from dotenv import load_dotenv

load_dotenv('/var/www/campaign_platform/backend/.env')
api_key = os.getenv('CINT_API_KEY')
supplier_code = os.getenv('CINT_SUPPLIER_CODE')
base_url = 'https://api.samplicio.us/'
endpoint = 'Supply/v1/SupplierLinks'

survey_id = 68555204
url = f"{base_url}{endpoint}/Create/{survey_id}/{supplier_code}"
headers = {'Authorization': api_key, 'Content-Type': 'application/json'}

payload = {
    'supplier_link_type_code': 'OWS',
    'tracking_type_code': 'NONE',
    'default_link': 'https://surveyfieldwork.com/survey'
}

print('URL:', url)
resp = requests.post(url, json=payload, headers=headers, timeout=30)
print('Status:', resp.status_code)
print('Body:', resp.text[:500])
