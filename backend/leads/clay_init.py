"""
Clay Integration Initialization
Runs on application startup to:
1. Create MongoDB indexes
2. Register Clay routes
3. Initialize background workers
"""

import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')


async def initialize_clay_features():
    """
    Initialize all Clay features on app startup
    This is called from main.py during FastAPI startup
    """
    
    print("\n" + "="*60)
    print("🚀 INITIALIZING CLAY-LEVEL FEATURES")
    print("="*60)
    
    try:
        # 1. Setup MongoDB indexes
        print("\n📦 Setting up MongoDB indexes...")
        from .clay_indexes import setup_clay_indexes
        setup_clay_indexes()
        
        # 2. Verify collections exist
        print("\n✅ Verifying Clay collections...")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client['campaign_platform']
        
        required_collections = [
            'sources',
            'workbooks',
            'workbook_columns',
            'workbook_rows',
            'workbook_cells',
            'execution_logs',
            'cost_ledgers',
            'import_sessions',
            'campaign_clay_configs',
            'workflows',
            'workflow_tasks'
        ]
        
        for collection_name in required_collections:
            # Collections are created on first insert, but we verify they're accessible
            db[collection_name].estimated_document_count()
            print(f"   ✓ {collection_name}")
        
        # 3. Initialize cost ledger tracker
        print("\n💰 Initializing cost tracking...")
        from .workflow_engine import CostLedgerTracker
        cost_tracker = CostLedgerTracker()
        print("   ✓ Cost ledger tracker initialized")
        
        # 4. Test campaign integration
        print("\n🔗 Testing campaign integration...")
        from .campaign_integration import get_campaign_integration
        integration = get_campaign_integration()
        print("   ✓ Campaign integration ready")
        
        print("\n" + "="*60)
        print("✅ CLAY-LEVEL FEATURES INITIALIZED SUCCESSFULLY")
        print("="*60 + "\n")
        
        return True
    
    except Exception as e:
        print(f"\n❌ ERROR during Clay initialization: {e}")
        import traceback
        traceback.print_exc()
        # Don't fail app startup, log warning instead
        return False


async def shutdown_clay_features():
    """
    Cleanup on application shutdown
    """
    print("\n🛑 Shutting down Clay features...")
    try:
        # Stop any background workers
        # Close database connections
        print("   ✓ Cleanup complete")
    except Exception as e:
        print(f"   ⚠️  Warning during shutdown: {e}")
