from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017')

# Check survey 60426555
s = c.survey_allocation.surveys.find_one({'external_id': '60426555'})
if s:
    print(f"Survey 60426555:")
    print(f"  status: {s.get('status')}")
    print(f"  has_href: {'href' in s and bool(s.get('href'))}")
    if 'href' in s and s.get('href'):
        print(f"  href: {s['href'][:200]}")
        print(f"  has k=: {'k=' in s['href']}")
    else:
        print(f"  href: MISSING")
        # Check if it exists in cpx_research
        cpx_s = c.cpx_research.cpx_surveys.find_one({'_id': '60426555'})
        if cpx_s:
            print(f"\n  ✅ Found in cpx_research.cpx_surveys:")
            print(f"    href: {cpx_s.get('href', 'MISSING')[:200]}")
        else:
            print(f"\n  ❌ NOT found in cpx_research.cpx_surveys either!")
else:
    print("Survey 60426555 NOT FOUND in survey_allocation.surveys")
