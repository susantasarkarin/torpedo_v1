"""Create MongoDB indexes for traffic_flow_db.url_parameters to speed up traffic queries"""
import pymongo
import time

c = pymongo.MongoClient('localhost', 27017, serverSelectionTimeoutMS=5000)
db = c['traffic_flow_db']
col = db['url_parameters']

print('Current indexes:')
for idx in col.list_indexes():
    print(f'  {idx["name"]}: {idx["key"]}')

print('\nCreating status index...')
start = time.time()
col.create_index('status', background=True)
print(f'  status index created in {time.time()-start:.2f}s')

print('Creating compound index (status, _id desc) for filtered list queries...')
start = time.time()
col.create_index([('status', 1), ('_id', -1)], background=True)
print(f'  status+_id index created in {time.time()-start:.2f}s')

# Test aggregation speed after indexing
print('\nTesting aggregation after indexing...')
start = time.time()
res = list(col.aggregate([{'$group': {'_id': '$status', 'count': {'$sum': 1}}}], maxTimeMS=15000))
elapsed = time.time() - start
print(f'Results: {res}')
print(f'Time: {elapsed:.2f}s')

print('\nDone. Updated indexes:')
for idx in col.list_indexes():
    print(f'  {idx["name"]}: {idx["key"]}')
