"""
MongoDB Indexes for Clay-like functionality
Ensures optimal query performance for list building, enrichment, and workbooks
"""

from pymongo import MongoClient, ASCENDING, DESCENDING
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')


def setup_clay_indexes():
    """Create all MongoDB indexes for Clay collections"""
    
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client['campaign_platform']
        
        # ============== SOURCES COLLECTION ==============
        sources = db['sources']
        
        sources.create_index([('campaign_id', ASCENDING), ('provider', ASCENDING)], unique=False)
        sources.create_index([('campaign_id', ASCENDING), ('status', ASCENDING)])
        sources.create_index([('created_at', DESCENDING)])
        sources.create_index([('source_type', ASCENDING)])
        
        print("✅ Sources collection indexes created")
        
        # ============== WORKBOOKS COLLECTION ==============
        workbooks = db['workbooks']
        
        workbooks.create_index([('campaign_id', ASCENDING)], unique=False)
        workbooks.create_index([('campaign_id', ASCENDING), ('status', ASCENDING)])
        workbooks.create_index([('created_by', ASCENDING), ('created_at', DESCENDING)])
        workbooks.create_index([('name', ASCENDING)])
        
        print("✅ Workbooks collection indexes created")
        
        # ============== WORKBOOK_COLUMNS COLLECTION ==============
        columns = db['workbook_columns']
        
        columns.create_index([('workbook_id', ASCENDING), ('column_index', ASCENDING)])
        columns.create_index([('workbook_id', ASCENDING), ('type', ASCENDING)])
        columns.create_index([('execution_state', ASCENDING)])
        
        print("✅ Workbook columns collection indexes created")
        
        # ============== WORKBOOK_ROWS COLLECTION ==============
        rows = db['workbook_rows']
        
        rows.create_index([('workbook_id', ASCENDING), ('row_index', ASCENDING)], unique=True)
        rows.create_index([('workbook_id', ASCENDING), ('status', ASCENDING)])
        rows.create_index([('entity_id', ASCENDING)])
        
        print("✅ Workbook rows collection indexes created")
        
        # ============== WORKBOOK_CELLS COLLECTION ==============
        cells = db['workbook_cells']
        
        cells.create_index([('workbook_id', ASCENDING), ('row_index', ASCENDING), ('column_id', ASCENDING)], unique=True)
        cells.create_index([('workbook_id', ASCENDING), ('column_id', ASCENDING)])
        cells.create_index([('has_override', ASCENDING)])
        cells.create_index([('updated_at', DESCENDING)])
        
        print("✅ Workbook cells collection indexes created")
        
        # ============== EXECUTION_LOGS COLLECTION ==============
        exec_logs = db['execution_logs']
        
        exec_logs.create_index([('campaign_id', ASCENDING), ('created_at', DESCENDING)])
        exec_logs.create_index([('workbook_id', ASCENDING), ('column_id', ASCENDING)])
        exec_logs.create_index([('status', ASCENDING)])
        exec_logs.create_index([('action', ASCENDING)])
        
        print("✅ Execution logs collection indexes created")
        
        # ============== COST_LEDGERS COLLECTION ==============
        costs = db['cost_ledgers']
        
        costs.create_index([('campaign_id', ASCENDING), ('created_at', DESCENDING)])
        costs.create_index([('campaign_id', ASCENDING), ('source_id', ASCENDING)])
        costs.create_index([('provider', ASCENDING)])
        costs.create_index([('created_at', DESCENDING)])
        
        print("✅ Cost ledgers collection indexes created")
        
        # ============== IMPORT_SESSIONS COLLECTION ==============
        imports = db['import_sessions']
        
        imports.create_index([('campaign_id', ASCENDING), ('created_at', DESCENDING)])
        imports.create_index([('status', ASCENDING)])
        imports.create_index([('created_at', DESCENDING)])
        
        print("✅ Import sessions collection indexes created")
        
        # ============== CAMPAIGN_CLAY_CONFIGS COLLECTION ==============
        configs = db['campaign_clay_configs']
        
        configs.create_index([('campaign_id', ASCENDING)], unique=True)
        configs.create_index([('created_at', DESCENDING)])
        
        print("✅ Campaign Clay configs collection indexes created")
        
        # ============== WORKFLOWS COLLECTION ==============
        workflows = db['workflows']
        
        workflows.create_index([('campaign_id', ASCENDING), ('created_at', DESCENDING)])
        workflows.create_index([('status', ASCENDING)])
        workflows.create_index([('created_by', ASCENDING)])
        
        print("✅ Workflows collection indexes created")
        
        # ============== WORKFLOW_TASKS COLLECTION ==============
        tasks = db['workflow_tasks']
        
        tasks.create_index([('workflow_id', ASCENDING), ('task_id', ASCENDING)])
        tasks.create_index([('workflow_id', ASCENDING), ('status', ASCENDING)])
        tasks.create_index([('status', ASCENDING)])
        
        print("✅ Workflow tasks collection indexes created")
        
        print("\n✅ All Clay indexes created successfully!")
        
        client.close()
        return True
    
    except Exception as e:
        print(f"❌ Error creating Clay indexes: {e}")
        return False


if __name__ == "__main__":
    setup_clay_indexes()
