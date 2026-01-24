#!/usr/bin/env python3
"""
System Status Check - Checks CPX/CINT survey inventory and Gmail sync status
Run this script to verify that all background services are working correctly.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

# Connection string - using production MongoDB
# Change this to match your production connection if different
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

def format_time_ago(dt):
    """Format datetime as 'X hours/minutes ago'"""
    if not dt:
        return "Never"
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    diff = now - dt
    
    if diff.total_seconds() < 60:
        return f"{int(diff.total_seconds())} seconds ago"
    elif diff.total_seconds() < 3600:
        return f"{int(diff.total_seconds() / 60)} minutes ago"
    elif diff.total_seconds() < 86400:
        return f"{diff.total_seconds() / 3600:.1f} hours ago"
    else:
        return f"{diff.days} days ago"

def check_cpx_surveys(client):
    """Check CPX survey inventory status"""
    print("\n" + "=" * 60)
    print("1. CPX SURVEY INVENTORY STATUS")
    print("=" * 60)
    
    try:
        # Try different possible database names
        for db_name in ["cpx_research", "cpx_db", "email_automation"]:
            db = client[db_name]
            
            # Try different collection names
            for coll_name in ["cpx_surveys", "surveys", "cpx_inventory"]:
                coll = db[coll_name]
                count = coll.count_documents({})
                if count > 0:
                    print(f"\n✓ Found {count} CPX surveys in {db_name}.{coll_name}")
                    
                    # Check for recently updated surveys
                    now = datetime.now(timezone.utc)
                    last_24h = now - timedelta(hours=24)
                    last_1h = now - timedelta(hours=1)
                    
                    # Find the most recently updated survey
                    for date_field in ["last_updated", "updated_at", "synced_at", "created_at", "_id"]:
                        try:
                            recent = coll.find_one(
                                {date_field: {"$exists": True}},
                                sort=[(date_field, -1)]
                            )
                            if recent:
                                last_update = recent.get(date_field)
                                if hasattr(last_update, 'generation_time'):
                                    # It's an ObjectId
                                    last_update = last_update.generation_time
                                if last_update:
                                    print(f"  • Last update: {format_time_ago(last_update)}")
                                    
                                    # Count recent entries
                                    try:
                                        recent_24h = coll.count_documents({date_field: {"$gte": last_24h}})
                                        recent_1h = coll.count_documents({date_field: {"$gte": last_1h}})
                                        print(f"  • Surveys updated in last 24h: {recent_24h}")
                                        print(f"  • Surveys updated in last 1h: {recent_1h}")
                                        
                                        if recent_24h > 0:
                                            print(f"  ✓ CPX SYNC IS ACTIVE")
                                        else:
                                            print(f"  ⚠ WARNING: No CPX updates in last 24 hours!")
                                    except:
                                        pass
                                    break
                        except:
                            continue
                    
                    # Show sample document keys
                    sample = coll.find_one()
                    if sample:
                        print(f"  • Sample doc keys: {list(sample.keys())[:10]}")
                    
                    return True
        
        print("\n⚠ No CPX survey collections found!")
        print("  Checked databases: cpx_research, cpx_db, email_automation")
        return False
        
    except Exception as e:
        print(f"\n✗ Error checking CPX surveys: {e}")
        return False


def check_cint_surveys(client):
    """Check CINT survey inventory status"""
    print("\n" + "=" * 60)
    print("2. CINT SURVEY INVENTORY STATUS")
    print("=" * 60)
    
    try:
        # Try different possible database names
        for db_name in ["cint_research", "cint_db", "email_automation"]:
            db = client[db_name]
            
            # Try different collection names
            for coll_name in ["cint_surveys", "surveys", "opportunities", "cint_inventory"]:
                coll = db[coll_name]
                count = coll.count_documents({})
                if count > 0:
                    print(f"\n✓ Found {count} CINT surveys in {db_name}.{coll_name}")
                    
                    # Check for recently updated surveys
                    now = datetime.now(timezone.utc)
                    last_24h = now - timedelta(hours=24)
                    last_1h = now - timedelta(hours=1)
                    
                    # Find the most recently updated survey
                    for date_field in ["last_updated", "updated_at", "synced_at", "received_at", "created_at", "_id"]:
                        try:
                            recent = coll.find_one(
                                {date_field: {"$exists": True}},
                                sort=[(date_field, -1)]
                            )
                            if recent:
                                last_update = recent.get(date_field)
                                if hasattr(last_update, 'generation_time'):
                                    # It's an ObjectId
                                    last_update = last_update.generation_time
                                if last_update:
                                    print(f"  • Last update: {format_time_ago(last_update)}")
                                    
                                    # Count recent entries
                                    try:
                                        recent_24h = coll.count_documents({date_field: {"$gte": last_24h}})
                                        recent_1h = coll.count_documents({date_field: {"$gte": last_1h}})
                                        print(f"  • Surveys updated in last 24h: {recent_24h}")
                                        print(f"  • Surveys updated in last 1h: {recent_1h}")
                                        
                                        if recent_24h > 0:
                                            print(f"  ✓ CINT SYNC IS ACTIVE")
                                        else:
                                            print(f"  ⚠ WARNING: No CINT updates in last 24 hours!")
                                    except:
                                        pass
                                    break
                        except:
                            continue
                    
                    # Show sample document keys
                    sample = coll.find_one()
                    if sample:
                        print(f"  • Sample doc keys: {list(sample.keys())[:10]}")
                    
                    return True
        
        print("\n⚠ No CINT survey collections found!")
        print("  Checked databases: cint_research, cint_db, email_automation")
        return False
        
    except Exception as e:
        print(f"\n✗ Error checking CINT surveys: {e}")
        return False


def check_gmail_sync(client):
    """Check Gmail email sync status in the last 24 hours"""
    print("\n" + "=" * 60)
    print("3. GMAIL EMAIL SYNC STATUS (Last 24 Hours)")
    print("=" * 60)
    
    try:
        # Try different possible database names
        for db_name in ["email_automation", "gmail_workspace", "emails", "campaign_platform"]:
            db = client[db_name]
            
            # Check multiple possible collection names for emails
            email_collections = [
                "email_metadata", "emails", "gmail_emails", "messages", 
                "email_archive", "unified_emails", "email_documents"
            ]
            
            for coll_name in email_collections:
                coll = db[coll_name]
                total_count = coll.count_documents({})
                
                if total_count > 0:
                    print(f"\n✓ Found {total_count} total emails in {db_name}.{coll_name}")
                    
                    now = datetime.now(timezone.utc)
                    last_24h = now - timedelta(hours=24)
                    last_1h = now - timedelta(hours=1)
                    
                    # Try different date fields
                    for date_field in ["synced_at", "created_at", "received_at", "internal_date", "date", "_id"]:
                        try:
                            # Find most recent email
                            recent = coll.find_one(
                                {date_field: {"$exists": True}},
                                sort=[(date_field, -1)]
                            )
                            
                            if recent:
                                last_sync = recent.get(date_field)
                                if hasattr(last_sync, 'generation_time'):
                                    last_sync = last_sync.generation_time
                                    
                                if last_sync:
                                    print(f"  • Last email received: {format_time_ago(last_sync)}")
                                    
                                    # Count emails in timeframes
                                    try:
                                        emails_24h = coll.count_documents({date_field: {"$gte": last_24h}})
                                        emails_1h = coll.count_documents({date_field: {"$gte": last_1h}})
                                        
                                        print(f"  • Emails synced in last 24h: {emails_24h}")
                                        print(f"  • Emails synced in last 1h: {emails_1h}")
                                        
                                        if emails_24h > 0:
                                            print(f"  ✓ GMAIL SYNC IS ACTIVE")
                                        else:
                                            print(f"  ⚠ WARNING: No emails synced in last 24 hours!")
                                            
                                        # Show breakdown by mailbox if possible
                                        try:
                                            for mailbox_field in ["mailbox_id", "account_email", "mailbox"]:
                                                pipeline = [
                                                    {"$match": {date_field: {"$gte": last_24h}}},
                                                    {"$group": {"_id": f"${mailbox_field}", "count": {"$sum": 1}}},
                                                    {"$sort": {"count": -1}},
                                                    {"$limit": 10}
                                                ]
                                                breakdown = list(coll.aggregate(pipeline))
                                                if breakdown and breakdown[0].get("_id"):
                                                    print(f"\n  Emails by {mailbox_field} (last 24h):")
                                                    for item in breakdown:
                                                        if item.get("_id"):
                                                            print(f"    • {item['_id']}: {item['count']}")
                                                    break
                                        except:
                                            pass
                                            
                                        return emails_24h > 0
                                    except Exception as e:
                                        print(f"  Could not count recent emails: {e}")
                                    break
                        except:
                            continue
                    
                    return True
            
            # Also check mailboxes collection for sync status
            for mb_coll in ["mailboxes", "gmail_accounts", "mail_accounts"]:
                coll = db[mb_coll]
                count = coll.count_documents({})
                if count > 0:
                    print(f"\n  Mailbox accounts in {db_name}.{mb_coll}: {count}")
                    
                    # Check last sync time for each mailbox
                    for sync_field in ["last_sync", "last_synced_at", "sync_status.last_sync"]:
                        mailboxes = list(coll.find({}, {"email": 1, "name": 1, sync_field: 1}).limit(10))
                        if mailboxes and any(mb.get(sync_field.split('.')[0]) for mb in mailboxes):
                            print(f"\n  Mailbox sync status:")
                            for mb in mailboxes:
                                email = mb.get("email") or mb.get("name") or "Unknown"
                                last_sync = mb.get(sync_field.split('.')[0])
                                if isinstance(last_sync, dict):
                                    last_sync = last_sync.get("last_sync")
                                if last_sync:
                                    print(f"    • {email}: {format_time_ago(last_sync)}")
                            break
        
        print("\n⚠ No email collections found with recent data!")
        return False
        
    except Exception as e:
        print(f"\n✗ Error checking Gmail sync: {e}")
        return False


def list_databases(client):
    """List all databases to help debug"""
    print("\n" + "=" * 60)
    print("DATABASE OVERVIEW")
    print("=" * 60)
    
    try:
        db_names = client.list_database_names()
        print(f"\nAvailable databases: {len(db_names)}")
        for db_name in db_names:
            if db_name not in ['admin', 'config', 'local']:
                db = client[db_name]
                colls = db.list_collection_names()
                print(f"\n  {db_name}: {len(colls)} collections")
                for coll_name in colls[:10]:
                    count = db[coll_name].estimated_document_count()
                    if count > 0:
                        print(f"    • {coll_name}: {count:,} docs")
    except Exception as e:
        print(f"Error listing databases: {e}")


def main():
    print("\n" + "#" * 60)
    print("# SYSTEM STATUS CHECK")
    print(f"# Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 60)
    
    try:
        print(f"\nConnecting to MongoDB: {MONGO_URI.split('@')[-1] if '@' in MONGO_URI else MONGO_URI}")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        
        # Test connection
        client.admin.command('ping')
        print("✓ MongoDB connection successful")
        
        # Show database overview
        list_databases(client)
        
        # Run all checks
        cpx_ok = check_cpx_surveys(client)
        cint_ok = check_cint_surveys(client)
        gmail_ok = check_gmail_sync(client)
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  CPX Survey Inventory:  {'✓ ACTIVE' if cpx_ok else '✗ CHECK NEEDED'}")
        print(f"  CINT Survey Inventory: {'✓ ACTIVE' if cint_ok else '✗ CHECK NEEDED'}")
        print(f"  Gmail Email Sync:      {'✓ ACTIVE' if gmail_ok else '✗ CHECK NEEDED'}")
        print("=" * 60)
        
        client.close()
        
    except Exception as e:
        print(f"\n✗ Connection failed: {e}")
        print("\nMake sure MongoDB is running and the connection string is correct.")
        print("You may need to run this on the production server or via SSH tunnel.")
        sys.exit(1)


if __name__ == "__main__":
    main()
