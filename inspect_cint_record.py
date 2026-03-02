import pymongo, os, sys
sys.path.insert(0, '/var/www/campaign_platform/backend')
try:
    from dotenv import load_dotenv
    load_dotenv('/var/www/campaign_platform/backend/.env')
except:
    pass

client = pymongo.MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017'))
traffic_db = client[os.getenv('TRAFFIC_DB_NAME', 'traffic_flow_db')]
main_db = client[os.getenv('MONGODB_DB_NAME', 'campaign_platform')]

from bson import ObjectId

rec = traffic_db.url_parameters.find_one({'_id': ObjectId('699d69b0111fb47a37745e9e')})
print('=== TRAFFIC RECORD KEY FIELDS ===')
print('vendorId:', rec.get('vendorId'))
print('respondentId:', rec.get('respondentId'))
print('status:', rec.get('status'))
print('cint_hashed_pid:', rec.get('cint_hashed_pid'))
print('cint_mid:', rec.get('cint_mid'))
print('cint_survey_id:', rec.get('cint_survey_id'))
print('cint_termination_reason:', rec.get('cint_termination_reason'))
print('cintCallbackUrl:', rec.get('cintCallbackUrl'))
print('currentCintSurveyId:', rec.get('currentCintSurveyId'))
print()

vid = rec.get('vendorId')
print('=== VENDOR LOOKUP ===')
print('Looking for vendor with vid:', vid, '(type:', type(vid).__name__, ')')

vendor = main_db.vendors.find_one({'vid': vid})
if not vendor and str(vid).isdigit():
    vendor = main_db.vendors.find_one({'vid': int(vid)})
if not vendor and isinstance(vid, int):
    vendor = main_db.vendors.find_one({'vid': str(vid)})

if vendor:
    print('Vendor found:', vendor.get('name'))
    print('vendorVariable:', vendor.get('vendorVariable'))
    print('completeRD:', vendor.get('completeRD'))
    print('terminateRD:', vendor.get('terminateRD'))
    print('quotaFullRD:', vendor.get('quotaFullRD'))
else:
    print('VENDOR NOT FOUND in campaign_platform.vendors for vid:', vid)
    print('Searching all dbs for vendor...')
    for db_name in client.list_database_names():
        d = client[db_name]
        colls = d.list_collection_names()
        if 'vendors' in colls:
            v = d.vendors.find_one({'vid': vid})
            if not v and str(vid).isdigit():
                v = d.vendors.find_one({'vid': int(vid)})
            if v:
                n = v.get('name')
                print('Found vendor in db=' + db_name + ' name=' + str(n))
                print('completeRD:', v.get('completeRD'))
                print('terminateRD:', v.get('terminateRD'))

print()
print('=== RECENT CINT CALLBACKS (last 5) ===')
logs = list(traffic_db.url_parameters.find(
    {'cintCallbackUrl': {'$exists': True}},
    {'_id': 1, 'status': 1, 'cintCallbackUrl': 1, 'vendorId': 1, 'updatedAt': 1}
).sort('updatedAt', -1).limit(5))
for l in logs:
    print(str(l.get('_id')), '|', l.get('status'), '|', l.get('vendorId'), '|', l.get('cintCallbackUrl', '')[:100])
