"""
UNIFIED INBOX API
=================

Aggregated inbox view across all mailboxes with conversation threading,
filtering, and search capabilities.

Features:
- Aggregate emails from all connected mailboxes
- Conversation threading by thread ID and subject
- Filter by category, status, mailbox, date range
- Full-text search
- Bulk operations (mark read, archive, categorize)
- Lead/contact association
- OPTIMIZED: Caching and projection optimization for performance

Endpoints:
- GET /inbox - List emails with filters
- GET /inbox/conversations - List conversation threads
- GET /inbox/{email_id} - Get single email
- GET /inbox/thread/{thread_id} - Get full conversation
- POST /inbox/bulk - Bulk operations
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field
from bson import ObjectId
from pymongo import MongoClient

import os
import time
import hashlib


router = APIRouter(prefix="/inbox", tags=["Unified Inbox"])


# ============== CACHING ==============
_inbox_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 30  # 30 seconds for inbox (more dynamic data)

def _get_cache_key(prefix: str, **kwargs) -> str:
    params = sorted((k, v) for k, v in kwargs.items() if v is not None)
    param_str = "&".join(f"{k}={v}" for k, v in params)
    return f"inbox:{prefix}:{hashlib.md5(param_str.encode()).hexdigest()}"

def _get_cached(key: str) -> Optional[Any]:
    if key in _inbox_cache:
        entry = _inbox_cache[key]
        if time.time() < entry['expires_at']:
            return entry['value']
        del _inbox_cache[key]
    return None

def _set_cached(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS):
    _inbox_cache[key] = {'value': value, 'expires_at': time.time() + ttl}
    if len(_inbox_cache) > 100:
        now = time.time()
        expired = [k for k, v in _inbox_cache.items() if now >= v['expires_at']]
        for k in expired:
            del _inbox_cache[k]

def invalidate_inbox_cache():
    """Clear inbox cache after mutations"""
    _inbox_cache.clear()

# Optimized projections for list views
EMAIL_LIST_PROJECTION = {
    "_id": 1,
    "mailbox_id": 1,
    "mailbox_email": 1,
    "provider_thread_id": 1,
    "direction": 1,
    "from_address": 1,
    "to_address": 1,
    "subject": 1,
    "snippet": 1,
    "timestamp": 1,
    "is_read": 1,
    "is_starred": 1,
    "is_archived": 1,
    "has_attachments": 1,
    "category": 1,
    "b2b_category": 1,
    "category_confidence": 1,
    "category_department": 1,
    "category_priority": 1,
    "crm_lead_id": 1,
    "crm_rfq_id": 1
}


# ============== MODELS ==============

class EmailAddress(BaseModel):
    email: str
    name: Optional[str] = None


class EmailSummary(BaseModel):
    """Summary view of an email for list display"""
    id: str
    mailbox_id: str
    mailbox_email: str
    thread_id: Optional[str] = None
    
    # Core fields
    direction: str  # inbound, outbound
    from_address: EmailAddress
    to_addresses: List[EmailAddress] = []
    subject: str
    snippet: str
    timestamp: datetime
    
    # Status
    is_read: bool = False
    is_starred: bool = False
    is_archived: bool = False
    has_attachments: bool = False
    
    # Classification
    category: Optional[str] = None
    category_confidence: Optional[float] = None
    department: Optional[str] = None
    priority: Optional[str] = None
    
    # CRM links
    lead_id: Optional[str] = None
    contact_id: Optional[str] = None
    rfq_id: Optional[str] = None
    project_id: Optional[str] = None  # P1.4: Link to Operations project


class EmailDetail(EmailSummary):
    """Full email detail"""
    body_plain: Optional[str] = None
    body_html: Optional[str] = None
    cc_addresses: List[EmailAddress] = []
    bcc_addresses: List[EmailAddress] = []
    attachments: List[Dict[str, Any]] = []
    labels: List[str] = []
    
    # Full classification
    b2b_category: Optional[str] = None
    sub_category: Optional[str] = None
    intent: Optional[str] = None
    reply_sentiment: Optional[str] = None
    key_entities: Dict[str, Any] = {}
    suggested_action: Optional[str] = None
    
    # Routing info
    routed_to_department: Optional[str] = None
    routing_record_id: Optional[str] = None


class ConversationThread(BaseModel):
    """Conversation thread summary"""
    thread_id: str
    subject: str
    participants: List[EmailAddress]
    email_count: int
    first_email_at: datetime
    last_email_at: datetime
    last_snippet: str
    
    # Status
    has_unread: bool = False
    is_starred: bool = False
    
    # Classification (from latest email)
    category: Optional[str] = None
    priority: Optional[str] = None
    
    # Associated records
    lead_id: Optional[str] = None
    rfq_id: Optional[str] = None


class InboxFilters(BaseModel):
    """Filters for inbox queries"""
    mailbox_ids: Optional[List[str]] = None
    direction: Optional[Literal["inbound", "outbound", "all"]] = "all"
    categories: Optional[List[str]] = None
    departments: Optional[List[str]] = None
    priorities: Optional[List[str]] = None
    is_read: Optional[bool] = None
    is_starred: Optional[bool] = None
    is_archived: Optional[bool] = None
    has_attachments: Optional[bool] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search_query: Optional[str] = None
    lead_id: Optional[str] = None
    contact_id: Optional[str] = None


class BulkOperation(BaseModel):
    """Bulk operation request"""
    email_ids: List[str]
    operation: Literal[
        "mark_read", "mark_unread", 
        "star", "unstar",
        "archive", "unarchive",
        "categorize", "delete"
    ]
    category: Optional[str] = None  # For categorize operation


class InboxStats(BaseModel):
    """Inbox statistics"""
    total_emails: int
    unread_count: int
    starred_count: int
    by_category: Dict[str, int]
    by_department: Dict[str, int]
    by_mailbox: Dict[str, int]


# ============== DATABASE ==============

def get_db():
    """Get MongoDB database instance"""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    return client['email_automation']


# ============== ENDPOINTS (OPTIMIZED) ==============

@router.get("", response_model=Dict[str, Any])
async def list_emails(
    # Pagination
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    
    # Filters
    mailbox_id: Optional[str] = None,
    direction: Optional[str] = None,
    category: Optional[str] = None,
    department: Optional[str] = None,
    priority: Optional[str] = None,
    is_read: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    
    # Sorting
    sort_by: str = "timestamp",
    sort_order: Literal["asc", "desc"] = "desc",
    
    db: MongoClient = Depends(get_db)
):
    """
    List emails with filters and pagination.
    Returns aggregated emails from all connected mailboxes.
    OPTIMIZED: Uses projection and caching for performance.
    """
    emails_collection = db["emails"]
    
    # Build query
    query = {}
    
    if mailbox_id:
        query["mailbox_id"] = mailbox_id
    
    if direction and direction != "all":
        query["direction"] = direction
    
    if category:
        query["$or"] = [
            {"category": category},
            {"b2b_category": category}
        ]
    
    if department:
        query["category_department"] = department
    
    if priority:
        query["category_priority"] = priority
    
    if is_read is not None:
        query["is_read"] = is_read
    
    if is_starred is not None:
        query["is_starred"] = is_starred
    
    if is_archived is not None:
        query["is_archived"] = is_archived if is_archived else {"$ne": True}
    else:
        # By default, exclude archived
        query["is_archived"] = {"$ne": True}
    
    if date_from:
        query["timestamp"] = {"$gte": date_from}
    
    if date_to:
        if "timestamp" in query:
            query["timestamp"]["$lte"] = date_to
        else:
            query["timestamp"] = {"$lte": date_to}
    
    if search:
        query["$text"] = {"$search": search}
    
    # Count total
    total = emails_collection.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_order == "asc" else -1
    
    # Fetch emails with PROJECTION for faster queries
    skip = (page - 1) * page_size
    cursor = emails_collection.find(query, EMAIL_LIST_PROJECTION).sort(sort_by, sort_direction).skip(skip).limit(page_size)
    
    emails = []
    for doc in cursor:
        email = _format_email_summary(doc)
        emails.append(email)
    
    return {
        "emails": emails,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/conversations", response_model=Dict[str, Any])
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50),
    mailbox_id: Optional[str] = None,
    category: Optional[str] = None,
    has_unread: Optional[bool] = None,
    search: Optional[str] = None,
    
    db: MongoClient = Depends(get_db)
):
    """
    List conversation threads.
    
    Groups emails by thread_id and returns aggregated thread info.
    """
    emails_collection = db["emails"]
    
    # Build match stage
    match_stage = {"is_archived": {"$ne": True}}
    
    if mailbox_id:
        match_stage["mailbox_id"] = mailbox_id
    
    if category:
        match_stage["$or"] = [
            {"category": category},
            {"b2b_category": category}
        ]
    
    if search:
        match_stage["$text"] = {"$search": search}
    
    # Aggregation pipeline
    pipeline = [
        {"$match": match_stage},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$provider_thread_id",
            "subject": {"$first": "$subject"},
            "last_snippet": {"$first": "$snippet"},
            "first_email_at": {"$min": "$timestamp"},
            "last_email_at": {"$max": "$timestamp"},
            "email_count": {"$sum": 1},
            "participants": {"$addToSet": "$from_address"},
            "has_unread": {"$max": {"$cond": [{"$eq": ["$is_read", False]}, True, False]}},
            "is_starred": {"$max": "$is_starred"},
            "category": {"$first": {"$ifNull": ["$b2b_category", "$category"]}},
            "priority": {"$first": "$category_priority"},
            "lead_id": {"$first": "$crm_lead_id"},
            "rfq_id": {"$first": "$crm_rfq_id"}
        }},
        {"$sort": {"last_email_at": -1}}
    ]
    
    if has_unread is not None:
        pipeline.append({"$match": {"has_unread": has_unread}})
    
    # Add pagination
    pipeline.append({"$skip": (page - 1) * page_size})
    pipeline.append({"$limit": page_size})
    
    threads = list(emails_collection.aggregate(pipeline))
    
    # Format response
    conversations = []
    for t in threads:
        if not t["_id"]:  # Skip emails without thread_id
            continue
        
        conversations.append({
            "thread_id": t["_id"],
            "subject": t["subject"] or "(No Subject)",
            "participants": t.get("participants", []),
            "email_count": t["email_count"],
            "first_email_at": t["first_email_at"],
            "last_email_at": t["last_email_at"],
            "last_snippet": t["last_snippet"] or "",
            "has_unread": t.get("has_unread", False),
            "is_starred": t.get("is_starred", False),
            "category": t.get("category"),
            "priority": t.get("priority"),
            "lead_id": t.get("lead_id"),
            "rfq_id": t.get("rfq_id")
        })
    
    return {
        "conversations": conversations,
        "page": page,
        "page_size": page_size
    }


@router.get("/stats", response_model=InboxStats)
async def get_inbox_stats(
    mailbox_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    bypass_cache: bool = Query(False, description="Force fresh data"),
    
    db: MongoClient = Depends(get_db)
):
    """Get inbox statistics (CACHED for 60 seconds)"""
    
    # Check cache
    cache_key = _get_cache_key("stats", mailbox=mailbox_id, date_from=str(date_from) if date_from else None)
    if not bypass_cache:
        cached = _get_cached(cache_key)
        if cached:
            return cached
    
    emails_collection = db["emails"]
    
    match_stage = {"is_archived": {"$ne": True}}
    if mailbox_id:
        match_stage["mailbox_id"] = mailbox_id
    if date_from:
        match_stage["timestamp"] = {"$gte": date_from}
    
    # OPTIMIZED: Single aggregation for all counts instead of multiple queries
    stats_pipeline = [
        {"$match": match_stage},
        {"$facet": {
            "totals": [
                {"$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "unread": {"$sum": {"$cond": [{"$ne": ["$is_read", True]}, 1, 0]}},
                    "starred": {"$sum": {"$cond": ["$is_starred", 1, 0]}}
                }}
            ],
            "by_category": [
                {"$group": {
                    "_id": {"$ifNull": ["$b2b_category", "$category"]},
                    "count": {"$sum": 1}
                }}
            ],
            "by_department": [
                {"$match": {"category_department": {"$exists": True, "$ne": None}}},
                {"$group": {
                    "_id": "$category_department",
                    "count": {"$sum": 1}
                }}
            ],
            "by_mailbox": [
                {"$group": {
                    "_id": "$mailbox_id",
                    "count": {"$sum": 1}
                }}
            ]
        }}
    ]
    
    result = list(emails_collection.aggregate(stats_pipeline))
    
    if result:
        data = result[0]
        totals = data["totals"][0] if data["totals"] else {"total": 0, "unread": 0, "starred": 0}
        by_category = {r["_id"] or "uncategorized": r["count"] for r in data["by_category"]}
        by_department = {r["_id"]: r["count"] for r in data["by_department"] if r["_id"]}
        by_mailbox = {r["_id"]: r["count"] for r in data["by_mailbox"] if r["_id"]}
    else:
        totals = {"total": 0, "unread": 0, "starred": 0}
        by_category = {}
        by_department = {}
        by_mailbox = {}
    
    response = InboxStats(
        total_emails=totals.get("total", 0),
        unread_count=totals.get("unread", 0),
        starred_count=totals.get("starred", 0),
        by_category=by_category,
        by_department=by_department,
        by_mailbox=by_mailbox
    )
    
    _set_cached(cache_key, response, ttl=60)
    return response


@router.get("/{email_id}", response_model=EmailDetail)
async def get_email(
    email_id: str,
    mark_read: bool = True,
    
    db: MongoClient = Depends(get_db)
):
    """Get a single email by ID"""
    emails_collection = db["emails"]
    
    try:
        doc = emails_collection.find_one({"_id": ObjectId(email_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid email ID")
    
    if not doc:
        raise HTTPException(status_code=404, detail="Email not found")
    
    # Mark as read
    if mark_read and not doc.get("is_read"):
        emails_collection.update_one(
            {"_id": ObjectId(email_id)},
            {"$set": {"is_read": True, "read_at": datetime.utcnow()}}
        )
    
    return _format_email_detail(doc)


@router.get("/thread/{thread_id}", response_model=Dict[str, Any])
async def get_thread(
    thread_id: str,
    db: MongoClient = Depends(get_db)
):
    """Get all emails in a conversation thread"""
    emails_collection = db["emails"]
    
    docs = list(emails_collection.find(
        {"provider_thread_id": thread_id}
    ).sort("timestamp", 1))
    
    if not docs:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    emails = [_format_email_detail(doc) for doc in docs]
    
    # Collect unique participants
    participants = {}
    for email in emails:
        addr = email.from_address
        participants[addr.email] = addr
        for to in email.to_addresses:
            participants[to.email] = to
    
    return {
        "thread_id": thread_id,
        "subject": emails[0].subject,
        "participants": list(participants.values()),
        "emails": emails,
        "email_count": len(emails)
    }


@router.post("/bulk", response_model=Dict[str, Any])
async def bulk_operation(
    operation: BulkOperation,
    db: MongoClient = Depends(get_db)
):
    """Perform bulk operations on emails"""
    emails_collection = db["emails"]
    
    # Convert IDs
    try:
        object_ids = [ObjectId(eid) for eid in operation.email_ids]
    except:
        raise HTTPException(status_code=400, detail="Invalid email ID(s)")
    
    # Build update based on operation
    update = {"$set": {"updated_at": datetime.utcnow()}}
    
    if operation.operation == "mark_read":
        update["$set"]["is_read"] = True
        update["$set"]["read_at"] = datetime.utcnow()
    
    elif operation.operation == "mark_unread":
        update["$set"]["is_read"] = False
        update["$unset"] = {"read_at": ""}
    
    elif operation.operation == "star":
        update["$set"]["is_starred"] = True
    
    elif operation.operation == "unstar":
        update["$set"]["is_starred"] = False
    
    elif operation.operation == "archive":
        update["$set"]["is_archived"] = True
        update["$set"]["archived_at"] = datetime.utcnow()
    
    elif operation.operation == "unarchive":
        update["$set"]["is_archived"] = False
        update["$unset"] = {"archived_at": ""}
    
    elif operation.operation == "categorize":
        if not operation.category:
            raise HTTPException(status_code=400, detail="Category required for categorize operation")
        update["$set"]["b2b_category"] = operation.category
        update["$set"]["category_method"] = "manual"
        update["$set"]["categorized_at"] = datetime.utcnow()
    
    elif operation.operation == "delete":
        # Soft delete
        update["$set"]["is_deleted"] = True
        update["$set"]["deleted_at"] = datetime.utcnow()
    
    result = emails_collection.update_many(
        {"_id": {"$in": object_ids}},
        update
    )
    
    return {
        "success": True,
        "operation": operation.operation,
        "modified_count": result.modified_count
    }


@router.post("/{email_id}/link-lead", response_model=Dict[str, Any])
async def link_to_lead(
    email_id: str,
    lead_id: str,
    db: MongoClient = Depends(get_db)
):
    """Link an email to a lead"""
    emails_collection = db["emails"]
    leads_collection = db["email_leads"]
    
    # Verify email exists
    email = emails_collection.find_one({"_id": ObjectId(email_id)})
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    # Verify lead exists
    lead = leads_collection.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Update email
    emails_collection.update_one(
        {"_id": ObjectId(email_id)},
        {"$set": {"crm_lead_id": lead_id}}
    )
    
    # Update lead
    leads_collection.update_one(
        {"_id": ObjectId(lead_id)},
        {
            "$addToSet": {"email_ids": email_id},
            "$set": {"last_activity_at": datetime.utcnow()}
        }
    )
    
    return {"success": True, "email_id": email_id, "lead_id": lead_id}


@router.post("/{email_id}/link-project", response_model=Dict[str, Any])
async def link_to_project(
    email_id: str,
    project_id: str,
    db: MongoClient = Depends(get_db)
):
    """
    P1.4: Link an email to an Operations project.
    Optionally links all emails in the same thread.
    """
    emails_collection = db["emails"]
    
    # Get operations database for project validation
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    operations_db = client["campaign_platform"]
    projects_collection = operations_db["projects"]
    
    # Verify email exists
    email = emails_collection.find_one({"_id": ObjectId(email_id)})
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    # Verify project exists
    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Update email
    emails_collection.update_one(
        {"_id": ObjectId(email_id)},
        {"$set": {"project_id": project_id, "project_linked_at": datetime.utcnow()}}
    )
    
    return {
        "success": True,
        "email_id": email_id,
        "project_id": project_id,
        "project_name": project.get("name")
    }


@router.post("/thread/{thread_id}/link-project", response_model=Dict[str, Any])
async def link_thread_to_project(
    thread_id: str,
    project_id: str,
    db: MongoClient = Depends(get_db)
):
    """
    P1.4: Link all emails in a thread to an Operations project.
    """
    emails_collection = db["emails"]
    
    # Get operations database for project validation
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    operations_db = client["campaign_platform"]
    projects_collection = operations_db["projects"]
    
    # Verify project exists
    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Find all emails in thread
    thread_emails = list(emails_collection.find({"provider_thread_id": thread_id}))
    if not thread_emails:
        raise HTTPException(status_code=404, detail="No emails found for this thread")
    
    # Update all emails in thread
    result = emails_collection.update_many(
        {"provider_thread_id": thread_id},
        {"$set": {"project_id": project_id, "project_linked_at": datetime.utcnow()}}
    )
    
    return {
        "success": True,
        "thread_id": thread_id,
        "project_id": project_id,
        "project_name": project.get("name"),
        "emails_linked": result.modified_count
    }


# ============== HELPER FUNCTIONS ==============

def _format_email_summary(doc: Dict) -> Dict[str, Any]:
    """Format email document for summary view"""
    from_addr = doc.get("from_address", {})
    if isinstance(from_addr, str):
        from_addr = {"email": from_addr, "name": ""}
    
    to_addrs = doc.get("to_addresses", [])
    formatted_to = []
    for addr in to_addrs:
        if isinstance(addr, str):
            formatted_to.append({"email": addr, "name": ""})
        elif isinstance(addr, dict):
            formatted_to.append(addr)
    
    return {
        "id": str(doc["_id"]),
        "mailbox_id": doc.get("mailbox_id", ""),
        "mailbox_email": doc.get("mailbox_email", ""),
        "thread_id": doc.get("provider_thread_id"),
        "direction": doc.get("direction", "inbound"),
        "from_address": from_addr,
        "to_addresses": formatted_to,
        "subject": doc.get("subject", "(No Subject)"),
        "snippet": doc.get("snippet", "")[:200],
        "timestamp": doc.get("timestamp", datetime.utcnow()),
        "is_read": doc.get("is_read", False),
        "is_starred": doc.get("is_starred", False),
        "is_archived": doc.get("is_archived", False),
        "has_attachments": bool(doc.get("attachments")),
        "category": doc.get("b2b_category") or doc.get("category"),
        "category_confidence": doc.get("category_confidence"),
        "department": doc.get("category_department"),
        "priority": doc.get("category_priority"),
        "lead_id": doc.get("crm_lead_id"),
        "contact_id": doc.get("crm_contact_id"),
        "rfq_id": doc.get("crm_rfq_id"),
        "project_id": doc.get("project_id")
    }


def _format_email_detail(doc: Dict) -> EmailDetail:
    """Format email document for detail view"""
    summary = _format_email_summary(doc)
    
    # Add full content
    cc_addrs = doc.get("cc_addresses", [])
    formatted_cc = []
    for addr in cc_addrs:
        if isinstance(addr, str):
            formatted_cc.append({"email": addr, "name": ""})
        elif isinstance(addr, dict):
            formatted_cc.append(addr)
    
    return EmailDetail(
        **summary,
        body_plain=doc.get("body_plain"),
        body_html=doc.get("body_html"),
        cc_addresses=formatted_cc,
        bcc_addresses=[],
        attachments=doc.get("attachments", []),
        labels=doc.get("labels", []),
        b2b_category=doc.get("b2b_category"),
        sub_category=doc.get("b2b_sub_category"),
        intent=doc.get("category_intent"),
        reply_sentiment=doc.get("reply_sentiment"),
        key_entities=doc.get("key_entities", {}),
        suggested_action=doc.get("suggested_action"),
        routed_to_department=doc.get("routed_to_department"),
        routing_record_id=doc.get("routing_record_id")
    )
