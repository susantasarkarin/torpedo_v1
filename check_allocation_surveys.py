from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017')

# Check survey_allocation.surveys for CPX surveys
cpx_surveys = list(c.survey_allocation.surveys.find(
    {'provider': 'CPX'},
    {'external_id': 1, 'status': 1, 'href': 1, 'entry_url': 1}
).limit(5))

print(f"📋 survey_allocation.surveys (CPX): {c.survey_allocation.surveys.count_documents({'provider': 'CPX'})} surveys")
print(f"📋 Active CPX surveys: {c.survey_allocation.surveys.count_documents({'provider': 'CPX', 'status': 'active'})}")

print("\nSample surveys:")
for s in cpx_surveys:
    has_href = 'href' in s and bool(s.get('href'))
    has_k = has_href and 'k=' in s.get('href', '')
    print(f"  external_id: {s.get('external_id')}, status: {s.get('status')}, has_href: {has_href}, has_k: {has_k}")
    if has_href:
        print(f"    href preview: {s['href'][:120]}...")
