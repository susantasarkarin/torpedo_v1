from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017')
surveys = list(c.campaign_platform.surveys.find(
    {'provider':'CPX','status':'active'},
    {'external_id':1,'href':1,'entry_url':1}
).limit(5))

print(f"Found {len(surveys)} active CPX surveys in allocation DB")
for s in surveys:
    has_href = 'href' in s and s['href']
    href_preview = s.get('href', '')[:100] if has_href else 'MISSING'
    print(f"  ID: {s.get('external_id')}, has_href: {has_href}")
    if has_href:
        print(f"    href: {href_preview}")
