"""
QUERY OPTIMIZER MODULE
Provides query optimization utilities for MongoDB operations.

Features:
- Projection optimization (fetch only needed fields)
- Batch fetching for related data
- Query explain analysis
- Index hint suggestions
"""

import logging
from typing import Dict, Any, List, Optional, Set
from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


# ============== FIELD PROJECTIONS ==============

class QueryProjections:
    """Common field projections for different use cases"""
    
    # Lead list views - minimal fields for table display
    LEAD_LIST = {
        "_id": 1,
        "name": 1,
        "email": 1,
        "company": 1,
        "title": 1,
        "seniority": 1,
        "source": 1,
        "classification_status": 1,
        "created_at": 1
    }
    
    # Lead detail view - full fields
    LEAD_DETAIL = None  # None means all fields
    
    # Email list view
    EMAIL_LIST = {
        "_id": 1,
        "subject": 1,
        "from_address": 1,
        "to_address": 1,
        "snippet": 1,
        "timestamp": 1,
        "is_read": 1,
        "is_starred": 1,
        "category": 1,
        "b2b_category": 1,
        "category_priority": 1,
        "mailbox_id": 1,
        "direction": 1
    }
    
    # Email conversation summary
    EMAIL_CONVERSATION = {
        "_id": 1,
        "subject": 1,
        "from_address": 1,
        "snippet": 1,
        "timestamp": 1,
        "is_read": 1,
        "provider_thread_id": 1,
        "category": 1,
        "b2b_category": 1
    }
    
    # Account/Contact list
    ACCOUNT_LIST = {
        "_id": 1,
        "name": 1,
        "email": 1,
        "company": 1,
        "status": 1,
        "account_type": 1,
        "created_at": 1
    }
    
    # Project list
    PROJECT_LIST = {
        "_id": 1,
        "name": 1,
        "client": 1,
        "projectStatus": 1,
        "projectOwner": 1,
        "startDate": 1,
        "endDate": 1,
        "budget": 1,
        "createdAt": 1
    }
    
    # Invoice list
    INVOICE_LIST = {
        "_id": 1,
        "invoice_number": 1,
        "customer_name": 1,
        "total_amount": 1,
        "balance_due": 1,
        "status": 1,
        "due_date": 1,
        "created_at": 1
    }
    
    # RFQ list
    RFQ_LIST = {
        "_id": 1,
        "rfq_number": 1,
        "contact_name": 1,
        "contact_email": 1,
        "status": 1,
        "manual_value": 1,
        "extracted_value": 1,
        "created_at": 1,
        "closed_date": 1
    }
    
    # User list (no sensitive data)
    USER_LIST = {
        "_id": 1,
        "username": 1,
        "email": 1,
        "roles": 1,
        "status": 1,
        "lastLogin": 1,
        "createdAt": 1
    }


# ============== QUERY OPTIMIZER ==============

class QueryOptimizer:
    """
    MongoDB query optimizer with:
    - Automatic projection selection
    - Batch loading helpers
    - Query analysis
    """
    
    def __init__(self, collection: Collection):
        self.collection = collection
        self._indexes = None
    
    @property
    def indexes(self) -> List[Dict]:
        """Get collection indexes (cached)"""
        if self._indexes is None:
            try:
                self._indexes = list(self.collection.list_indexes())
            except Exception:
                self._indexes = []
        return self._indexes
    
    def get_indexed_fields(self) -> Set[str]:
        """Get set of indexed field names"""
        fields = set()
        for idx in self.indexes:
            for key in idx.get('key', {}).keys():
                fields.add(key)
        return fields
    
    def has_index_for_query(self, query: Dict[str, Any]) -> bool:
        """Check if query can use an index"""
        query_fields = set(query.keys())
        indexed_fields = self.get_indexed_fields()
        
        # At least one query field should be indexed
        return bool(query_fields & indexed_fields)
    
    def suggest_index(self, query: Dict[str, Any], sort: Dict[str, int] = None) -> Optional[List[tuple]]:
        """Suggest an index for the query"""
        query_fields = list(query.keys())
        sort_fields = list(sort.keys()) if sort else []
        
        # Check if we already have a suitable index
        indexed = self.get_indexed_fields()
        
        # Build suggested index
        suggested = []
        
        # Add equality fields first (from query)
        for field in query_fields:
            if field not in indexed and not field.startswith('$'):
                suggested.append((field, ASCENDING))
        
        # Add sort fields
        for field in sort_fields:
            if field not in indexed and field not in query_fields:
                direction = ASCENDING if sort.get(field, 1) > 0 else DESCENDING
                suggested.append((field, direction))
        
        return suggested if suggested else None
    
    def find_optimized(
        self,
        query: Dict[str, Any],
        projection: Dict[str, int] = None,
        sort: List[tuple] = None,
        skip: int = 0,
        limit: int = 0
    ) -> List[Dict]:
        """
        Execute optimized find query.
        
        Args:
            query: MongoDB query filter
            projection: Field projection (uses defaults if None)
            sort: Sort order as list of (field, direction) tuples
            skip: Number of documents to skip
            limit: Maximum documents to return
        """
        cursor = self.collection.find(query, projection)
        
        if sort:
            cursor = cursor.sort(sort)
        
        if skip:
            cursor = cursor.skip(skip)
        
        if limit:
            cursor = cursor.limit(limit)
        
        return list(cursor)
    
    def count_optimized(self, query: Dict[str, Any]) -> int:
        """
        Execute optimized count query.
        Uses count_documents for accuracy, estimated_document_count for speed.
        """
        if not query:
            # Empty query - use fast estimate
            return self.collection.estimated_document_count()
        
        return self.collection.count_documents(query)
    
    def aggregate_optimized(
        self,
        pipeline: List[Dict],
        batch_size: int = 1000,
        allow_disk_use: bool = True
    ) -> List[Dict]:
        """
        Execute optimized aggregation.
        
        Args:
            pipeline: Aggregation pipeline stages
            batch_size: Cursor batch size
            allow_disk_use: Allow MongoDB to use disk for large aggregations
        """
        cursor = self.collection.aggregate(
            pipeline,
            allowDiskUse=allow_disk_use,
            batchSize=batch_size
        )
        return list(cursor)


# ============== BATCH LOADING ==============

class BatchLoader:
    """
    Batch load related documents to avoid N+1 query problems.
    """
    
    def __init__(self, db: Database):
        self.db = db
    
    def load_by_ids(
        self,
        collection_name: str,
        ids: List[str],
        projection: Dict[str, int] = None,
        id_field: str = "_id"
    ) -> Dict[str, Dict]:
        """
        Load multiple documents by IDs.
        
        Returns:
            Dict mapping ID string to document
        """
        from bson import ObjectId
        
        collection = self.db[collection_name]
        
        # Convert string IDs to ObjectId if needed
        if id_field == "_id":
            try:
                obj_ids = [ObjectId(id) for id in ids if id]
            except Exception:
                obj_ids = ids
        else:
            obj_ids = ids
        
        cursor = collection.find(
            {id_field: {"$in": obj_ids}},
            projection
        )
        
        result = {}
        for doc in cursor:
            key = str(doc.get(id_field))
            result[key] = doc
        
        return result
    
    def load_related(
        self,
        documents: List[Dict],
        foreign_key: str,
        target_collection: str,
        target_field: str = "_id",
        projection: Dict[str, int] = None,
        embed_as: str = None
    ) -> List[Dict]:
        """
        Load related documents and embed them.
        
        Args:
            documents: Source documents
            foreign_key: Field in source pointing to target
            target_collection: Collection to load from
            target_field: Field in target to match against
            projection: Fields to include from target
            embed_as: Field name for embedded doc (uses foreign_key + '_data' if None)
        
        Returns:
            Documents with related data embedded
        """
        # Extract foreign keys
        fks = [doc.get(foreign_key) for doc in documents if doc.get(foreign_key)]
        fks = list(set(fks))  # Unique
        
        if not fks:
            return documents
        
        # Batch load related
        related = self.load_by_ids(
            target_collection,
            fks,
            projection,
            target_field
        )
        
        # Embed in documents
        embed_field = embed_as or f"{foreign_key}_data"
        for doc in documents:
            fk = doc.get(foreign_key)
            if fk and str(fk) in related:
                doc[embed_field] = related[str(fk)]
        
        return documents


# ============== HELPER FUNCTIONS ==============

def optimize_query(collection: Collection) -> QueryOptimizer:
    """Create a query optimizer for a collection"""
    return QueryOptimizer(collection)


def get_projection(view_type: str) -> Optional[Dict[str, int]]:
    """Get projection for a view type"""
    projections = {
        'lead_list': QueryProjections.LEAD_LIST,
        'lead_detail': QueryProjections.LEAD_DETAIL,
        'email_list': QueryProjections.EMAIL_LIST,
        'email_conversation': QueryProjections.EMAIL_CONVERSATION,
        'account_list': QueryProjections.ACCOUNT_LIST,
        'project_list': QueryProjections.PROJECT_LIST,
        'invoice_list': QueryProjections.INVOICE_LIST,
        'rfq_list': QueryProjections.RFQ_LIST,
        'user_list': QueryProjections.USER_LIST
    }
    return projections.get(view_type)


def paginate_query(
    collection: Collection,
    query: Dict[str, Any],
    page: int = 1,
    page_size: int = 50,
    sort_field: str = "_id",
    sort_order: int = -1,
    projection: Dict[str, int] = None
) -> Dict[str, Any]:
    """
    Execute paginated query with optimizations.
    
    Returns:
        Dict with 'items', 'total', 'page', 'page_size', 'total_pages'
    """
    # Count total (could use estimated for large collections)
    total = collection.count_documents(query)
    
    # Calculate skip
    skip = (page - 1) * page_size
    
    # Execute query
    cursor = collection.find(query, projection)
    cursor = cursor.sort(sort_field, sort_order)
    cursor = cursor.skip(skip)
    cursor = cursor.limit(page_size)
    
    items = list(cursor)
    
    # Convert ObjectIds to strings
    for item in items:
        if '_id' in item:
            item['_id'] = str(item['_id'])
    
    total_pages = (total + page_size - 1) // page_size
    
    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages
    }
