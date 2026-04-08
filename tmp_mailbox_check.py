from pymongo import MongoClient
c = MongoClient("mongodb://localhost:27017/")

db = c["torpedo_gmail"]
print("torpedo_gmail collections:", db.list_collection_names())

wm = list(db["workspace_mailboxes"].find({}))
print(f"workspace_mailboxes: {len(wm)}")
for m in wm:
    print({k: m.get(k) for k in ("email", "status", "business", "display_name", "provider") if k in m})
    auth_keys = [k for k in m.keys() if k not in ("_id",)]
    print("  all keys:", auth_keys)

ia = list(db["imap_accounts"].find({}))
print(f"imap_accounts: {len(ia)}")
for a in ia:
    print({k: a.get(k) for k in a.keys() if k != "_id"})

gc = list(db["gmail_config"].find({}))
print(f"gmail_config: {len(gc)}")
for g in gc:
    print({k: g.get(k) for k in g.keys() if k != "_id"})

