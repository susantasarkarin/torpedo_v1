#!/usr/bin/env python3
"""Find cint collections in MongoDB"""
from pymongo import MongoClient

c = MongoClient()

print("=== ALL DATABASES AND CINT COLLECTIONS ===")
for db_name in c.list_database_names():
    cols = c[db_name].list_collection_names()
    cint_cols = [col for col in cols if "cint" in col.lower()]
    if cint_cols:
        print(f"{db_name}: {cint_cols}")
        for col in cint_cols:
            count = c[db_name][col].count_documents({})
            print(f"  - {col}: {count} documents")

print("\n=== CHECKING COMMON DATABASES ===")
for db_name in ['campaign_platform', 'campaign_db', 'torpedo', 'cint_db', 'surveys']:
    if db_name in c.list_database_names():
        cols = c[db_name].list_collection_names()
        print(f"\n{db_name}:")
        for col in cols:
            count = c[db_name][col].count_documents({})
            print(f"  - {col}: {count}")
