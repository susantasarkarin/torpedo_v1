from pymongo import MongoClient
db = MongoClient()['email_automation']

sample = db.leads_raw.find_one({'classification_status': 'pending'})
keys = list(sample.keys()) if sample else []
print('Lead fields:', keys)

sources = db.leads_raw.distinct('source')
print('Sources:', sources[:20])

projects = db.leads_raw.distinct('project_id')
print('Project IDs:', str(projects)[:500])

tags = db.leads_raw.distinct('tags')
print('Tags:', str(tags)[:300])

# Check project collection
db2 = MongoClient()['torpedo']
proj_names = list(db2.projects.find({}, {'name':1,'_id':1,'code':1}))
print('Projects:', str(proj_names)[:500])
