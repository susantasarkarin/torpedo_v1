"""
Initialize CRM collections and indexes.
Run with: python -m backend.migrations.001_init_crm_collections
"""
from pymongo import MongoClient, ASCENDING
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

def ensure_indexes(db):
    print("Ensuring indexes for crm_db...")
    db.accounts.create_index([("name", ASCENDING)], unique=False)
    db.accounts.create_index([("account_type", ASCENDING)])
    db.accounts.create_index([("status", ASCENDING)])

    db.contacts.create_index([("email", ASCENDING)], unique=False)
    db.contacts.create_index([("account_id", ASCENDING)])

    db.leads.create_index([("email", ASCENDING)])
    db.leads.create_index([("status", ASCENDING)])

    db.opportunities.create_index([("account_id", ASCENDING)])
    db.opportunities.create_index([("status", ASCENDING)])
    db.opportunities.create_index([("stage", ASCENDING)])

    db.activities.create_index([("contact_id", ASCENDING)])
    db.activities.create_index([("account_id", ASCENDING)])
    db.activities.create_index([("created_at", ASCENDING)])

    db.tasks.create_index([("owner_id", ASCENDING)])
    db.tasks.create_index([("status", ASCENDING)])
    db.tasks.create_index([("due_date", ASCENDING)])

    db.ai_decisions.create_index([("agent_name", ASCENDING)])
    db.ai_decisions.create_index([("status", ASCENDING)])
    db.ai_decisions.create_index([("linked_object_type", ASCENDING), ("linked_object_id", ASCENDING)])

if __name__ == "__main__":
    crm_db = client[os.getenv("CRM_DB_NAME", "crm_db")] 
    ensure_indexes(crm_db)
    print("Indexes ensured.")
