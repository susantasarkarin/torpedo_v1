from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017')
db = client['traffic_flow_db']

# Get the CPX surveys collection to see stored surveys
print('=== CPX SURVEYS for survey 60430947 ===')
survey = db.cpx_surveys.find_one({'cpx_survey_id': '60430947'})
if survey:
    print(f"Found survey 60430947")
    print(f"Keys: {list(survey.keys())}")
else:
    print("Survey 60430947 NOT FOUND in cpx_surveys")

# Find allocations for both respondents
print()
print('=== CPX ALLOCATIONS ===')
alloc_w = db.cpx_allocations.find_one({'traffic_id': '698585c106f61e8d32dd34ab'})
alloc_b = db.cpx_allocations.find_one({'traffic_id': '6985eb3f9848c6ddb9b20695'})

print(f"Working allocation: {alloc_w}")
print()
print(f"Broken allocation: {alloc_b}")

# Check if we're storing entry links somewhere
print()
print('=== CHECKING COLLECTIONS ===')
for coll_name in db.list_collection_names():
    print(f"Collection: {coll_name}")
