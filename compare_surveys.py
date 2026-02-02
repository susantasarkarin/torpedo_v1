from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017')

# Check cpx_research.cpx_surveys
cpx_surveys = list(c.cpx_research.cpx_surveys.find({}, {'_id': 1, 'href': 1}).limit(5))
print(f"📋 cpx_research.cpx_surveys: {c.cpx_research.cpx_surveys.count_documents({})} surveys")
for s in cpx_surveys[:3]:
    print(f"  _id: {s['_id']}, has_href: {'href' in s and bool(s.get('href'))}")

# Check campaign_platform.surveys (CPX provider)
alloc_surveys = list(c.campaign_platform.surveys.find({'provider': 'CPX'}, {'external_id': 1, '_id': 1, 'status': 1, 'href': 1}).limit(5))
print(f"\n📋 campaign_platform.surveys (CPX): {c.campaign_platform.surveys.count_documents({'provider': 'CPX'})} surveys")
for s in alloc_surveys[:3]:
    print(f"  _id: {s['_id']}, external_id: {s.get('external_id')}, status: {s.get('status')}, has_href: {'href' in s and bool(s.get('href'))}")
