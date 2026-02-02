import requests
from urllib.parse import quote, urlparse, parse_qs
import hashlib

# CPX API credentials
APP_ID = '3476'
EXT_USER_ID = 'PANEL_88921'
SECURE_HASH_KEY = 'Bb8lVFKJlvmUZJkl'
BASE_URL = 'https://live-api.cpx-research.com/api/get-surveys.php'

# Generate secure hash
secure_hash_input = f"{APP_ID}:{EXT_USER_ID}:{SECURE_HASH_KEY}"
secure_hash = hashlib.md5(secure_hash_input.encode()).hexdigest()

# Request parameters
params = {
    "app_id": APP_ID,
    "ext_user_id": EXT_USER_ID,
    "subid_1": "",
    "subid_2": "",
    "output_method": "api",
    "ip_user": quote("127.0.0.1"),
    "user_agent": quote("Mozilla/5.0"),
    "limit": 1,
    "secure_hash": secure_hash,
}

print("Fetching from CPX API...")
try:
    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    # Check surveys
    if 'surveys' in data and len(data['surveys']) > 0:
        survey = data['surveys'][0]
        href = survey.get('href', '')
        print("First survey from CPX:")
        print(f"  survey_id: {survey.get('id')}")
        print(f"  title: {survey.get('survey_title')}")
        print(f"\n  FULL href URL:")
        print(f"  {href}")
        print(f"\n  href length: {len(href)} chars")
        
        # Parse the href to check parameters
        parsed = urlparse(href)
        params_dict = parse_qs(parsed.query)
        print(f"\n  href parameters:")
        for key in sorted(params_dict.keys()):
            value = params_dict[key][0]
            if len(value) > 60:
                print(f"    {key}: {value[:60]}... ({len(value)} chars)")
            else:
                print(f"    {key}: {value}")
    else:
        print("No surveys in response")
        print(f"Response keys: {list(data.keys())}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
