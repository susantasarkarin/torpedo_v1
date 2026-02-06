"""
SHARED UTILITIES MODULE
Common helper functions used across the application.

Provides:
- Document serialization (ObjectId -> str)
- Pagination helpers
- Error handling utilities
- Date/time utilities
"""

from typing import Any, Dict, List, Optional, TypeVar, Union
from bson import ObjectId
from datetime import datetime, timezone
from pydantic import BaseModel
import traceback
import re
from urllib.parse import urlparse


# ============== DOCUMENT SERIALIZATION ==============

def serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Convert MongoDB document to JSON-serializable format.
    Handles ObjectId and datetime conversions.
    
    Args:
        doc: MongoDB document (dict with _id as ObjectId)
        
    Returns:
        Serialized document with string _id, or None if doc is None
    """
    if doc is None:
        return None
    
    result = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = serialize_doc(value)
        elif isinstance(value, list):
            result[key] = [
                serialize_doc(item) if isinstance(item, dict)
                else str(item) if isinstance(item, ObjectId)
                else item.isoformat() if isinstance(item, datetime)
                else item
                for item in value
            ]
        else:
            result[key] = value
    
    return result


def serialize_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Serialize a list of MongoDB documents.
    
    Args:
        docs: List of MongoDB documents
        
    Returns:
        List of serialized documents
    """
    return [serialize_doc(doc) for doc in docs if doc is not None]


def to_object_id(id_str: str) -> Optional[ObjectId]:
    """
    Safely convert a string to ObjectId.
    
    Args:
        id_str: String ID to convert
        
    Returns:
        ObjectId or None if conversion fails
    """
    try:
        return ObjectId(id_str)
    except Exception:
        return None


def validate_object_id(id_str: str) -> bool:
    """
    Check if a string is a valid ObjectId.
    
    Args:
        id_str: String to validate
        
    Returns:
        True if valid ObjectId, False otherwise
    """
    try:
        ObjectId(id_str)
        return True
    except Exception:
        return False


# ============== PAGINATION HELPERS ==============

class PaginationParams(BaseModel):
    """Standard pagination parameters."""
    skip: int = 0
    limit: int = 50
    
    class Config:
        extra = "forbid"


class PaginatedResponse(BaseModel):
    """Standard paginated response structure."""
    items: List[Any]
    total: int
    skip: int
    limit: int
    has_more: bool


def paginate_query(
    collection,
    query: Dict[str, Any],
    skip: int = 0,
    limit: int = 50,
    sort_field: str = "_id",
    sort_order: int = -1
) -> PaginatedResponse:
    """
    Execute a paginated query on a MongoDB collection.
    
    Args:
        collection: MongoDB collection
        query: Query filter dict
        skip: Number of documents to skip
        limit: Maximum documents to return
        sort_field: Field to sort by
        sort_order: 1 for ascending, -1 for descending
        
    Returns:
        PaginatedResponse with items and metadata
    """
    # Ensure reasonable limits
    limit = min(limit, 1000)  # Max 1000 items per page
    skip = max(skip, 0)
    
    # Get total count
    total = collection.count_documents(query)
    
    # Get paginated items
    cursor = collection.find(query).sort(sort_field, sort_order).skip(skip).limit(limit)
    items = serialize_docs(list(cursor))
    
    return PaginatedResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
        has_more=(skip + len(items)) < total
    )


def get_pagination_params(skip: int = 0, limit: int = 50) -> Dict[str, int]:
    """
    Validate and return pagination parameters.
    
    Args:
        skip: Number to skip (default 0)
        limit: Number to return (default 50, max 1000)
        
    Returns:
        Dict with validated skip and limit
    """
    return {
        "skip": max(skip, 0),
        "limit": min(max(limit, 1), 1000)
    }


# ============== ERROR HANDLING ==============

class APIError(Exception):
    """Custom API error with status code and details."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.message,
            "status_code": self.status_code,
            "details": self.details
        }


def format_error_response(
    message: str,
    status_code: int = 500,
    details: Optional[Dict[str, Any]] = None,
    include_traceback: bool = False
) -> Dict[str, Any]:
    """
    Format a standardized error response.
    
    Args:
        message: Error message
        status_code: HTTP status code
        details: Additional error details
        include_traceback: Include stack trace (only for dev)
        
    Returns:
        Formatted error dict
    """
    response = {
        "success": False,
        "error": message,
        "status_code": status_code,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if details:
        response["details"] = details
    
    if include_traceback:
        response["traceback"] = traceback.format_exc()
    
    return response


def handle_db_error(e: Exception, operation: str = "database operation") -> Dict[str, Any]:
    """
    Handle database errors with appropriate logging and response.
    
    Args:
        e: Exception that occurred
        operation: Description of the operation that failed
        
    Returns:
        Error response dict
    """
    error_msg = str(e)
    print(f"❌ Database error during {operation}: {error_msg}")
    
    if "timeout" in error_msg.lower():
        return format_error_response(
            f"Database timeout during {operation}",
            status_code=504
        )
    elif "connection" in error_msg.lower():
        return format_error_response(
            f"Database connection error during {operation}",
            status_code=503
        )
    else:
        return format_error_response(
            f"Database error during {operation}: {error_msg}",
            status_code=500
        )


# ============== DATE/TIME UTILITIES ==============

def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_str() -> str:
    """Get current UTC datetime as ISO string."""
    return utc_now().isoformat()


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO datetime string.
    
    Args:
        dt_str: ISO format datetime string
        
    Returns:
        datetime object or None if parsing fails
    """
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except Exception:
        return None


def format_datetime(dt: Optional[datetime], default: str = "") -> str:
    """
    Format a datetime to ISO string.
    
    Args:
        dt: datetime object
        default: Default value if dt is None
        
    Returns:
        ISO format string or default
    """
    if dt is None:
        return default
    return dt.isoformat()


# ============== VALIDATION UTILITIES ==============

def clean_string(value: Any, default: str = "") -> str:
    """
    Clean and validate a string value.
    
    Args:
        value: Value to clean
        default: Default if value is None/empty
        
    Returns:
        Cleaned string
    """
    if value is None:
        return default
    return str(value).strip()


def clean_int(value: Any, default: int = 0) -> int:
    """
    Clean and validate an integer value.
    
    Args:
        value: Value to convert
        default: Default if conversion fails
        
    Returns:
        Integer value
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean_float(value: Any, default: float = 0.0) -> float:
    """
    Clean and validate a float value.
    
    Args:
        value: Value to convert
        default: Default if conversion fails
        
    Returns:
        Float value
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_bool(value: Any, default: bool = False) -> bool:
    """
    Clean and validate a boolean value.
    
    Args:
        value: Value to convert
        default: Default if conversion fails
        
    Returns:
        Boolean value
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


# ============== QUERY BUILDERS ==============

def build_text_search_query(
    search_term: str,
    fields: List[str]
) -> Dict[str, Any]:
    """
    Build a MongoDB query for text search across multiple fields.
    
    Args:
        search_term: Term to search for
        fields: Fields to search in
        
    Returns:
        MongoDB query dict
    """
    if not search_term:
        return {}
    
    regex = {"$regex": search_term, "$options": "i"}
    return {"$or": [{field: regex} for field in fields]}


def build_date_range_query(
    field: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Build a MongoDB query for date range filtering.
    
    Args:
        field: Date field name
        start_date: Start of range (inclusive)
        end_date: End of range (inclusive)
        
    Returns:
        MongoDB query dict
    """
    if not start_date and not end_date:
        return {}
    
    query = {}
    if start_date:
        query["$gte"] = start_date
    if end_date:
        query["$lte"] = end_date
    
    return {field: query} if query else {}


def merge_queries(*queries: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge multiple MongoDB queries with $and.
    
    Args:
        queries: Query dicts to merge
        
    Returns:
        Merged query dict
    """
    valid_queries = [q for q in queries if q]
    
    if not valid_queries:
        return {}
    if len(valid_queries) == 1:
        return valid_queries[0]
    
    return {"$and": valid_queries}


# ============== URL VALIDATION ==============

def validate_redirect_url(url: str, require_https: bool = True) -> tuple:
    """
    Validate a redirect URL for safety.
    Returns (is_valid, error_message)
    
    Args:
        url: URL to validate
        require_https: Whether to require HTTPS scheme
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    if not url:
        return False, "URL is required"
    
    url = url.strip()
    
    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"
    
    # Check scheme
    if require_https:
        if parsed.scheme != "https":
            return False, "URL must use HTTPS"
    elif parsed.scheme not in ("http", "https"):
        return False, "URL must use HTTP or HTTPS"
    
    # Check for localhost/internal IPs
    host = parsed.netloc.lower().split(":")[0]
    blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
    if host in blocked_hosts:
        return False, "Internal/localhost URLs not allowed"
    
    # Check for private IP ranges
    if re.match(r"^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)", host):
        return False, "Private IP addresses not allowed"
    
    # Check for javascript: or data: schemes
    if parsed.scheme in ("javascript", "data", "vbscript"):
        return False, f"Scheme '{parsed.scheme}' not allowed"
    
    # Basic path validation
    if not parsed.netloc:
        return False, "URL must have a valid host"
    
    return True, ""


# ============== SOFT DELETE UTILITIES ==============

def soft_delete_update(deleted_by: Optional[str] = None) -> dict:
    """
    Generate the $set update for soft delete.
    
    Args:
        deleted_by: Username or ID of the user performing the delete
        
    Returns:
        Dict to use with MongoDB $set for soft delete
    """
    return {
        "$set": {
            "is_deleted": True,
            "deleted_at": datetime.utcnow(),
            "deleted_by": deleted_by
        }
    }


def not_deleted_filter() -> dict:
    """
    Filter to exclude soft-deleted documents.
    
    Returns:
        MongoDB query dict to filter out deleted documents
    """
    return {"is_deleted": {"$ne": True}}


def include_deleted_filter(include: bool = False) -> dict:
    """
    Conditionally filter deleted documents.
    
    Args:
        include: If True, include deleted documents; if False, exclude them
        
    Returns:
        MongoDB query dict (empty if including, filter if excluding)
    """
    if include:
        return {}
    return {"is_deleted": {"$ne": True}}


# ============== HTTP REQUEST UTILITIES ==============

def _is_ipv4(ip: str) -> bool:
    """Check if an IP address is IPv4 format (contains dots, no colons)."""
    if not ip:
        return False
    ip = ip.strip()
    # IPv4: contains dots, no colons (e.g., 192.168.1.1)
    # IPv6: contains colons (e.g., 2001:db8::1)
    return '.' in ip and ':' not in ip


def extract_real_client_ip(request) -> tuple:
    """
    Extract the real client IP from request headers.
    
    CRITICAL FOR CPX: Must return IPv4 when available!
    CPX validates that the IP in API call matches the IP when user clicks survey.
    If we send IPv6 but user connects with IPv4, CPX rejects with api_standart_screen_out.
    
    Checks headers in priority order:
    1. CF-Connecting-IP (Cloudflare) - PREFER IPv4
    2. X-Forwarded-For (prefer IPv4 from the list)
    3. X-Real-IP (Nginx)
    4. request.client.host (direct connection)
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Tuple of (ip_address: str, source: str)
    """
    # Collect all available IPs with their sources
    all_ips = []
    
    # Priority 1: Cloudflare header
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        all_ips.append((cf_ip.strip(), "CF-Connecting-IP"))
    
    # Priority 2: X-Forwarded-For - may contain multiple IPs
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # X-Forwarded-For format: "client, proxy1, proxy2"
        ips = [ip.strip() for ip in xff.split(",")]
        for ip in ips:
            if ip and not _is_private_ip(ip):
                all_ips.append((ip, "X-Forwarded-For"))
    
    # Priority 3: X-Real-IP (Nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        all_ips.append((real_ip.strip(), "X-Real-IP"))
    
    # Priority 4: Direct connection
    if request.client and request.client.host:
        all_ips.append((request.client.host, "direct"))
    
    if not all_ips:
        return "0.0.0.0", "unknown"
    
    # CRITICAL: Prefer IPv4 over IPv6 for CPX compatibility
    # CPX tracking uses IPv4, if we send IPv6 but user clicks with IPv4, we get rejected
    ipv4_ips = [(ip, src) for ip, src in all_ips if _is_ipv4(ip)]
    
    if ipv4_ips:
        # Return the first IPv4 (highest priority source that has IPv4)
        selected_ip, source = ipv4_ips[0]
        print(f"📍 IP Selection: Using IPv4 {selected_ip} from {source} (had {len(all_ips)} total IPs)")
        return selected_ip, source
    
    # No IPv4 available, use whatever we have (IPv6)
    selected_ip, source = all_ips[0]
    print(f"⚠️ IP Selection: No IPv4 available, using IPv6 {selected_ip} from {source}")
    return selected_ip, source


def _is_private_ip(ip: str) -> bool:
    """
    Check if an IP address is private/internal.
    
    Args:
        ip: IP address string
        
    Returns:
        True if private, False if public
    """
    private_prefixes = [
        "10.",
        "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.",
        "172.24.", "172.25.", "172.26.", "172.27.",
        "172.28.", "172.29.", "172.30.", "172.31.",
        "192.168.",
        "127.",
        "0.",
        "::1",
        "localhost"
    ]
    ip_lower = ip.lower().strip()
    return any(ip_lower.startswith(prefix) for prefix in private_prefixes)


def extract_user_agent(request) -> str:
    """
    Extract User-Agent from request headers.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        User-Agent string or empty string if not present
    """
    return request.headers.get("User-Agent", "") or ""
