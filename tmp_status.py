import pymongo, datetime
col = pymongo.MongoClient()['email_automation']['leads_raw']
pending = col.count_documents({'classification_status': {'$in': ['Pending','pending']}})
classified = col.count_documents({'classification_status': {'$in': ['Classified','classified']}})
failed = col.count_documents({'classification_status': {'$in': ['Failed','failed']}})
recent = col.count_documents({'classified_at': {'$gte': datetime.datetime.utcnow() - datetime.timedelta(minutes=10)}})
print(f'Pending: {pending}  Classified: {classified}  Failed: {failed}  Recent(10min): {recent}')
