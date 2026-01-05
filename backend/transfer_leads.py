"""
Lead Transfer Script
Export leads from localhost MongoDB and import to VM MongoDB

Usage:
    Export: python transfer_leads.py export
    Import: python transfer_leads.py import --vm-uri "mongodb://your-vm-ip:27017/"
    Count:  python transfer_leads.py count
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId, json_util
from dotenv import load_dotenv

load_dotenv()

# Default URIs
LOCAL_MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
VM_MONGO_URI = os.getenv('VM_MONGO_URI', 'mongodb://35.154.176.88:27017/')  # Update with your VM IP

DATABASE_NAME = 'email_automation'
COLLECTIONS_TO_TRANSFER = [
    'leads_raw',
    'leads_enriched',
    'lead_ai_classification_logs'
]

EXPORT_DIR = 'leads_export'


def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable format"""
    return json.loads(json_util.dumps(doc))


def deserialize_doc(doc):
    """Convert JSON back to MongoDB document format"""
    return json_util.loads(json.dumps(doc))


def get_connection(uri, name="MongoDB"):
    """Create MongoDB connection with timeout"""
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        # Test connection
        client.admin.command('ping')
        print(f"✓ Connected to {name}: {uri[:50]}...")
        return client
    except Exception as e:
        print(f"✗ Failed to connect to {name}: {e}")
        return None


def count_leads(uri=None):
    """Count leads in the specified MongoDB"""
    uri = uri or LOCAL_MONGO_URI
    client = get_connection(uri, "MongoDB")
    if not client:
        return
    
    db = client[DATABASE_NAME]
    print(f"\n{'='*50}")
    print(f"Lead counts in: {uri[:50]}...")
    print(f"{'='*50}")
    
    for collection_name in COLLECTIONS_TO_TRANSFER:
        count = db[collection_name].count_documents({})
        print(f"  {collection_name}: {count:,} documents")
    
    client.close()


def export_leads():
    """Export leads from local MongoDB to JSON files"""
    client = get_connection(LOCAL_MONGO_URI, "Local MongoDB")
    if not client:
        return False
    
    db = client[DATABASE_NAME]
    
    # Create export directory
    os.makedirs(EXPORT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print(f"\n{'='*50}")
    print("Exporting leads from local MongoDB...")
    print(f"{'='*50}")
    
    export_manifest = {
        'exported_at': timestamp,
        'source': LOCAL_MONGO_URI,
        'collections': {}
    }
    
    for collection_name in COLLECTIONS_TO_TRANSFER:
        collection = db[collection_name]
        count = collection.count_documents({})
        print(f"\n  Exporting {collection_name}... ({count:,} documents)")
        
        # Export all documents
        documents = list(collection.find({}))
        serialized = [serialize_doc(doc) for doc in documents]
        
        # Save to file
        filename = f"{EXPORT_DIR}/{collection_name}_{timestamp}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(serialized, f, ensure_ascii=False, indent=2)
        
        export_manifest['collections'][collection_name] = {
            'count': count,
            'file': filename
        }
        print(f"    ✓ Saved to {filename}")
    
    # Save manifest
    manifest_file = f"{EXPORT_DIR}/manifest_{timestamp}.json"
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(export_manifest, f, indent=2)
    
    print(f"\n✓ Export complete! Manifest: {manifest_file}")
    client.close()
    return True


def import_leads(vm_uri=None, manifest_file=None):
    """Import leads to VM MongoDB from JSON files"""
    vm_uri = vm_uri or VM_MONGO_URI
    
    # Find latest manifest if not specified
    if not manifest_file:
        try:
            manifests = [f for f in os.listdir(EXPORT_DIR) if f.startswith('manifest_')]
            if not manifests:
                print("✗ No export manifest found. Run 'export' first.")
                return False
            manifest_file = os.path.join(EXPORT_DIR, sorted(manifests)[-1])
        except FileNotFoundError:
            print("✗ No export directory found. Run 'export' first.")
            return False
    
    # Load manifest
    with open(manifest_file, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    print(f"\n{'='*50}")
    print(f"Importing leads to VM MongoDB...")
    print(f"Manifest: {manifest_file}")
    print(f"{'='*50}")
    
    # Connect to VM
    client = get_connection(vm_uri, "VM MongoDB")
    if not client:
        return False
    
    db = client[DATABASE_NAME]
    
    for collection_name, info in manifest['collections'].items():
        data_file = info['file']
        print(f"\n  Importing {collection_name}...")
        
        # Load data
        with open(data_file, 'r', encoding='utf-8') as f:
            documents = json.load(f)
        
        if not documents:
            print(f"    ⚠ No documents to import")
            continue
        
        # Deserialize documents
        docs_to_insert = [deserialize_doc(doc) for doc in documents]
        
        collection = db[collection_name]
        
        # Option 1: Clear and insert all (clean slate)
        # Option 2: Upsert (merge with existing)
        
        # Using upsert approach to avoid duplicates
        inserted = 0
        updated = 0
        errors = 0
        
        for doc in docs_to_insert:
            try:
                doc_id = doc.get('_id')
                if doc_id:
                    result = collection.replace_one(
                        {'_id': doc_id},
                        doc,
                        upsert=True
                    )
                    if result.upserted_id:
                        inserted += 1
                    elif result.modified_count > 0:
                        updated += 1
                else:
                    collection.insert_one(doc)
                    inserted += 1
            except Exception as e:
                # Try inserting without _id for duplicates
                try:
                    # Check by linkedin_url for leads
                    if 'linkedin_url' in doc and doc['linkedin_url']:
                        existing = collection.find_one({'linkedin_url': doc['linkedin_url']})
                        if existing:
                            updated += 1
                            continue
                    
                    # Remove _id and insert
                    doc_copy = dict(doc)
                    if '_id' in doc_copy:
                        del doc_copy['_id']
                    collection.insert_one(doc_copy)
                    inserted += 1
                except Exception as e2:
                    errors += 1
        
        print(f"    ✓ Inserted: {inserted:,}, Updated: {updated:,}, Errors: {errors}")
    
    print(f"\n✓ Import complete!")
    client.close()
    return True


def main():
    parser = argparse.ArgumentParser(description='Transfer leads between MongoDB instances')
    parser.add_argument('action', choices=['export', 'import', 'count', 'count-vm'],
                       help='Action to perform')
    parser.add_argument('--vm-uri', type=str, default=None,
                       help='VM MongoDB URI (e.g., mongodb://35.154.176.88:27017/)')
    parser.add_argument('--manifest', type=str, default=None,
                       help='Path to export manifest file')
    
    args = parser.parse_args()
    
    if args.action == 'export':
        export_leads()
    elif args.action == 'import':
        import_leads(args.vm_uri, args.manifest)
    elif args.action == 'count':
        count_leads(LOCAL_MONGO_URI)
    elif args.action == 'count-vm':
        vm_uri = args.vm_uri or VM_MONGO_URI
        count_leads(vm_uri)


if __name__ == '__main__':
    main()
