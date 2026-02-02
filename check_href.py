import pymongo
from urllib.parse import parse_qs, urlparse

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['cpx_research']
coll = db['cpx_surveys']

# Find surveys with href
survey = coll.find_one({'href': {'$exists': True, '$ne': ''}})
if survey:
    print("Sample survey from MongoDB:")
    print(f"  survey_id: {survey.get('survey_id')}")
    href = survey.get('href', '')
    print(f"  href length: {len(href)}")
    print(f"\n  FULL href:")
    print(f"  {href}")
    
    # Check if it has ext_user_id in the URL
    if 'ext_user_id' in href:
        print("\n✓ ext_user_id IS in href")
    else:
        print("\n✗ ext_user_id NOT in href")
        
    # Check all parameters in href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    print(f"\nParameters in href:")
    for key in sorted(params.keys()):
        print(f"  {key}: present")
else:
    print("No survey found with href")
