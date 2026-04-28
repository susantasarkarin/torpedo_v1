import pymongo
from collections import Counter

col = pymongo.MongoClient()['email_automation']['leads_raw']
s = Counter(str(d.get('classification_status', 'NONE')) for d in col.find({}, {'classification_status': 1}))
for k,v in s.most_common(10):
    print(v, k)
