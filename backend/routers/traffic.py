"""
Traffic Flow API Router
Handles survey tracking and URL parameter storage
Uses traffic_flow_db database
"""
from fastapi import APIRouter, HTTPException, Request, Query, Body
from fastapi.responses import RedirectResponse, JSONResponse
from pymongo.collection import Collection
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import os
import random
import base64
import time
import hashlib

# URL validation utility for redirect safety
try:
    from ..utils import validate_redirect_url
except ImportError:
    try:
        from utils import validate_redirect_url
    except ImportError:
        # Fallback if utils not available
        def validate_redirect_url(url: str, require_https: bool = True) -> tuple:
            return True, ""

router = APIRouter(tags=["traffic-flow"])  # No prefix - routes are at root level

# ============== TRAFFIC LIST CACHING ==============
_traffic_list_cache: Dict[str, Dict[str, Any]] = {}
TRAFFIC_CACHE_TTL_SECONDS = 5  # 5 seconds TTL for fast refresh under high traffic

def _get_traffic_cache_key(prefix: str, **kwargs) -> str:
    """Generate a cache key from parameters"""
    params = sorted((k, v) for k, v in kwargs.items() if v is not None)
    param_str = "&".join(f"{k}={v}" for k, v in params)
    return f"traffic:{prefix}:{hashlib.md5(param_str.encode()).hexdigest()}"

def _get_traffic_cached(key: str) -> Optional[Any]:
    """Get value from cache if not expired"""
    if key in _traffic_list_cache:
        entry = _traffic_list_cache[key]
        if time.time() < entry['expires_at']:
            return entry['value']
        del _traffic_list_cache[key]
    return None

def _set_traffic_cached(key: str, value: Any, ttl: int = TRAFFIC_CACHE_TTL_SECONDS):
    """Set value in cache with TTL"""
    _traffic_list_cache[key] = {'value': value, 'expires_at': time.time() + ttl}
    # Cleanup expired entries if cache grows too large
    if len(_traffic_list_cache) > 100:
        now = time.time()
        expired = [k for k, v in _traffic_list_cache.items() if now >= v['expires_at']]
        for k in expired:
            del _traffic_list_cache[k]

def invalidate_traffic_cache():
    """Clear traffic list cache after mutations (inserts, updates, deletes)"""
    _traffic_list_cache.clear()

# Configuration for traffic flow redirects - always from environment file
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://surveyfieldwork.com")

ZOHO_COMPLETE_URL = f"{FRONTEND_URL}/thankyou"
ZOHO_TERMINATE_URL = f"{FRONTEND_URL}/nosurvey"
ZOHO_QUOTA_URL = f"{FRONTEND_URL}/nosurvey"

# This will be injected from main.py
url_parameters_collection: Optional[Collection] = None
traffic_service: Optional[Any] = None
survey_allocation_service: Optional[Any] = None
cpx_service: Optional[Any] = None
cint_service: Optional[Any] = None  # CINT service for direct survey allocation
vendors_collection: Optional[Collection] = None
cpx_callback_logs_collection: Optional[Collection] = None
cpx_postback_logs_collection: Optional[Collection] = None  # S2S postback logs for verification


def set_url_parameters_collection(collection: Collection):
    """Set the MongoDB collection from main.py"""
    global url_parameters_collection
    url_parameters_collection = collection


def set_traffic_service(service: Any):
    """Set the traffic service instance from main.py"""
    global traffic_service
    traffic_service = service


def set_survey_allocation_service(service: Any):
    """Set the survey allocation service instance"""
    global survey_allocation_service
    survey_allocation_service = service


def set_cpx_service(service: Any):
    """Set the CPX service instance for survey allocation"""
    global cpx_service
    cpx_service = service


def set_cint_service(service: Any):
    """Set the CINT service instance for survey allocation"""
    global cint_service
    cint_service = service


def set_vendors_collection(collection: Collection):
    """Set the vendors MongoDB collection from main.py"""
    global vendors_collection
    vendors_collection = collection


def set_cpx_callback_logs_collection(collection: Collection):
    """Set the CPX callback logs MongoDB collection from main.py"""
    global cpx_callback_logs_collection
    cpx_callback_logs_collection = collection


def set_cpx_postback_logs_collection(collection: Collection):
    """Set the CPX S2S postback logs collection for verification"""
    global cpx_postback_logs_collection
    cpx_postback_logs_collection = collection


# ============================================
# TASK 3: CPX Entry Guards - Single-Use ext_user_id
# ============================================
# This prevents the same ext_user_id from being used multiple times
# CPX rejects traffic with: already_clicked, already_do_internal, api_standart_screen_out
cpx_entry_guards_collection: Optional[Collection] = None

# Entry guard status values
CPX_GUARD_STATUS_CREATED = "CREATED"      # ext_user_id registered, not yet redirected
CPX_GUARD_STATUS_REDIRECTED = "REDIRECTED"  # User redirected to CPX survey
CPX_GUARD_STATUS_LOCKED = "LOCKED"        # Entry locked, no more redirects allowed


def set_cpx_entry_guards_collection(collection: Collection):
    """Set the CPX entry guards collection for single-use ext_user_id enforcement"""
    global cpx_entry_guards_collection
    cpx_entry_guards_collection = collection
    print("✅ CPX entry guards collection set for single-use ext_user_id enforcement")


def check_cpx_entry_guard(ext_user_id: str, client_ip: str = None, user_agent: str = None) -> dict:
    """
    TASK 3: Check if ext_user_id can be used for CPX entry.
    
    Returns:
        dict: {"allowed": bool, "reason": str, "existing_status": str or None}
    """
    if cpx_entry_guards_collection is None:
        # If collection not available, allow (fail-open for backwards compatibility)
        print("⚠️ CPX entry guards collection not available - allowing entry (fail-open)")
        return {"allowed": True, "reason": "guard_collection_not_configured", "existing_status": None}
    
    try:
        existing = cpx_entry_guards_collection.find_one({"ext_user_id": ext_user_id})
        
        if existing:
            status = existing.get("status", "UNKNOWN")
            print(f"🚫 CPX ENTRY GUARD: ext_user_id '{ext_user_id}' already exists with status '{status}'")
            
            # Log the duplicate attempt
            cpx_entry_guards_collection.update_one(
                {"ext_user_id": ext_user_id},
                {
                    "$inc": {"duplicate_attempt_count": 1},
                    "$set": {"last_duplicate_attempt": datetime.utcnow()},
                    "$push": {
                        "duplicate_attempts": {
                            "timestamp": datetime.utcnow(),
                            "client_ip": client_ip,
                            "user_agent": user_agent[:200] if user_agent else None
                        }
                    }
                }
            )
            
            return {
                "allowed": False,
                "reason": f"ext_user_id_already_used_{status.lower()}",
                "existing_status": status
            }
        
        # ext_user_id is new, register it
        guard_doc = {
            "ext_user_id": ext_user_id,
            "status": CPX_GUARD_STATUS_CREATED,
            "created_at": datetime.utcnow(),
            "client_ip": client_ip,
            "user_agent": user_agent[:500] if user_agent else None,
            "duplicate_attempt_count": 0,
            "duplicate_attempts": []
        }
        
        try:
            cpx_entry_guards_collection.insert_one(guard_doc)
            print(f"✅ CPX ENTRY GUARD: Registered new ext_user_id '{ext_user_id}' with status CREATED")
            return {"allowed": True, "reason": "new_ext_user_id", "existing_status": None}
        except Exception as dup_err:
            # Race condition - another request registered it first
            if "duplicate" in str(dup_err).lower() or "E11000" in str(dup_err):
                print(f"🚫 CPX ENTRY GUARD: Race condition - ext_user_id '{ext_user_id}' registered by another request")
                return {"allowed": False, "reason": "race_condition_duplicate", "existing_status": "CREATED"}
            raise
            
    except Exception as e:
        print(f"⚠️ CPX ENTRY GUARD ERROR: {e} - allowing entry (fail-open)")
        import traceback
        traceback.print_exc()
        return {"allowed": True, "reason": f"guard_error_{str(e)[:50]}", "existing_status": None}


def update_cpx_entry_guard_status(ext_user_id: str, new_status: str, survey_id: str = None, entry_link: str = None):
    """
    TASK 4: Update ext_user_id status after redirect.
    
    Call this AFTER generating the entry link but BEFORE returning to frontend.
    """
    if cpx_entry_guards_collection is None:
        print("⚠️ CPX entry guards collection not available - cannot update status")
        return False
    
    try:
        update_data = {
            "status": new_status,
            f"{new_status.lower()}_at": datetime.utcnow()
        }
        
        if survey_id:
            update_data["survey_id"] = survey_id
        if entry_link:
            update_data["entry_link"] = entry_link[:500]  # Truncate for storage
        
        result = cpx_entry_guards_collection.update_one(
            {"ext_user_id": ext_user_id},
            {"$set": update_data}
        )
        
        if result.modified_count > 0:
            print(f"✅ CPX ENTRY GUARD: Updated ext_user_id '{ext_user_id}' status to '{new_status}'")
            return True
        else:
            print(f"⚠️ CPX ENTRY GUARD: No document found to update for ext_user_id '{ext_user_id}'")
            return False
            
    except Exception as e:
        print(f"⚠️ CPX ENTRY GUARD UPDATE ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================
# TASK 5: WebView Detection
# ============================================
WEBVIEW_SIGNATURES = [
    "wv",           # Android WebView generic marker
    "webview",      # Generic WebView
    "fbav",         # Facebook App WebView
    "fban",         # Facebook App Native
    "instagram",    # Instagram WebView
    "twitter",      # Twitter WebView
    "line/",        # LINE app
    "kakaotalk",    # KakaoTalk app
    "timebucks",    # TimeBucks app (specific to CPX)
    ";wv)",         # Android WebView pattern
    "micromessenger",  # WeChat
    "snapchat",     # Snapchat
    "tiktok",       # TikTok
]


def is_webview_user_agent(user_agent: str) -> tuple:
    """
    TASK 5: Detect if user agent indicates WebView traffic.
    
    CPX explicitly blocks WebView traffic. We should reject before calling API.
    
    Returns:
        tuple: (is_webview: bool, detected_signature: str or None)
    """
    if not user_agent:
        return False, None
    
    ua_lower = user_agent.lower()
    
    for signature in WEBVIEW_SIGNATURES:
        if signature.lower() in ua_lower:
            print(f"🚫 WEBVIEW DETECTED: User agent contains '{signature}' - CPX will reject this traffic")
            return True, signature
    
    return False, None


@router.get("/cint-response")
async def cint_callback(
    request: Request,
    status: str = Query(..., description="Response status: complete, terminate, quota_full, quality_terminate"),
    pid: str = Query(None, description="Participant ID (traffic record ID) - PRIMARY identifier"),
    mid: str = Query(None, description="Cint session ID (MID) - for logging only"),
    revenue: str = Query(None, description="Revenue/payout amount")
):
    """
    Cint Survey Callback Handler
    
    URL format: /cint-response?status={status}&pid={pid}&mid={mid}&revenue={revenue}
    
    - status: complete, terminate, quota_full, quality_terminate
    - pid: The Participant ID (traffic record _id) - PRIMARY identifier for finding the record
    - mid: The Cint session ID (MID) - for logging/debugging only
    - revenue: The payout amount (REVENUE placeholder replaced by Cint)
    """
    try:
        print(f"📥 Cint Callback received: status={status}, pid={pid}, mid={mid}, revenue={revenue}")
        print(f"📥 Full callback URL: {request.url}")
        
        # Map Cint status to internal status
        status_mapping = {
            "complete": "COMPLETE",
            "terminate": "TERMINATED",
            "quota_full": "OVERQUOTA",
            "quality_terminate": "QUALITY_TERM"
        }
        new_status = status_mapping.get(status.lower(), "TERMINATED")
        redirect_type = "completeRD" if new_status == "COMPLETE" else "terminateRD"
        
        # Primary lookup key is PID (traffic record ID), fallback to MID for legacy compatibility
        lookup_id = pid or mid
        if not lookup_id:
            print("❌ Neither pid nor mid provided in callback")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=missing_id")
        
        # Find traffic record - PID is the traffic record ObjectId
        traffic_record = None
        if url_parameters_collection is not None:
            # Try PID as ObjectId first (preferred)
            try:
                traffic_record = url_parameters_collection.find_one({"_id": ObjectId(lookup_id)})
                if traffic_record:
                    print(f"✅ Found traffic record by ObjectId: {lookup_id}")
            except:
                pass
            
            # Try as respondentId (legacy fallback)
            if not traffic_record:
                traffic_record = url_parameters_collection.find_one({"respondentId": lookup_id})
                if traffic_record:
                    print(f"✅ Found traffic record by respondentId: {lookup_id}")
            
            # Try as string _id (edge case)
            if not traffic_record:
                traffic_record = url_parameters_collection.find_one({"_id": lookup_id})
                if traffic_record:
                    print(f"✅ Found traffic record by string _id: {lookup_id}")

            # Try lookup by stored CINT MID (if PID did not resolve)
            if not traffic_record and mid:
                traffic_record = url_parameters_collection.find_one({"cint_mid": mid})
                if traffic_record:
                    print(f"✅ Found traffic record by cint_mid: {mid}")
        
        if not traffic_record:
            print(f"⚠️ Traffic record not found for pid={pid}, mid={mid}")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=not_found")
        
        # Get vendor info
        vendor_id = traffic_record.get("vendorId")
        respondent_id = traffic_record.get("respondentId", "")
        
        # Update traffic status
        if url_parameters_collection is not None:
            url_parameters_collection.update_one(
                {"_id": traffic_record["_id"]},
                {"$set": {
                    "status": new_status,
                    "cint_mid": mid,  # Store Cint session ID for reference
                    "cint_revenue": revenue,
                    "updatedAt": datetime.utcnow(),
                    "completedAt": datetime.utcnow() if new_status == "COMPLETE" else None
                }}
            )
        
        # Get vendor redirect URL
        redirect_url = f"{FRONTEND_URL}/thankyou"
        if vendor_id and vendors_collection is not None:
            vendor = vendors_collection.find_one({"vendorId": vendor_id})
            if vendor:
                redirect_url = vendor.get(redirect_type, redirect_url)
        
        # Append respondent ID
        if respondent_id:
            separator = "&" if "?" in redirect_url else "?"
            redirect_url = f"{redirect_url}{separator}id={respondent_id}"
        
        print(f"✅ Cint callback: Redirecting to {redirect_url}")
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        print(f"❌ Cint callback error: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")


@router.get("/cpx-response")
async def cpx_callback(
    request: Request,
    msg: str = Query(None, description="Response type: complete or out (can also be message_id)"),
    status: str = Query(None, description="Response status: complete or out (alternative to msg)"),
    message_id: str = Query(None, description="Message ID (alternative identifier)"),
    trans_id: str = Query(None, description="Transaction ID (preferred, replaces message_id)"),
    rid: str = Query(None, description="CPX respondent ID (optional, for backwards compatibility)"),
    sfwid: str = Query(None, description="SFWID passed via subid_1 from CPX - PRIMARY identifier"),
    subid_1: Optional[str] = Query(None, alias="subid_1", description="Legacy subid_1 (SFWID)"),
    subid: Optional[str] = Query(None, alias="subid", description="Legacy subid (SFWID)")
):
    """
    CPX Survey Callback Handler (LEGACY - prefer /cpx-api/cpx-postback for new integrations)
    
    URL formats supported:
    - /cpx-response?msg={type}&trans_id={trans_id}&sfwid={subid_1}
    - /cpx-response?msg={message_id}&status={status}&sfwid={subid_1}
    
    - msg: "complete" or "out" (terminate) OR can be message_id
    - status: "complete" or "out" (alternative to msg for status)
    - message_id: Message identifier
    - trans_id: Transaction ID (preferred identifier, replaces message_id)
    - sfwid: The SFWID (traffic record _id) passed via subid_1 - PRIMARY identifier
    
    Logic:
    1. Use sfwid (from subid_1) to find the traffic record
    2. Get the vendorId from the traffic record
    3. Look up vendor's redirect URL (completeRD or terminateRD)
    4. Append the original respondentId from the traffic record to vendor's redirect URL
    5. Update traffic status and redirect to vendor
    """
    try:
        # Priority for status: 'status' param > 'msg' param (if it looks like a status) > default to "out"
        # The 'status' param is the explicit status indicator
        # The 'msg' param can be either status type OR a message_id
        if status:
            # Explicit status parameter provided
            status_code = status
        elif msg and msg.lower() in ["complete", "out", "terminate", "quotafull", "quality_terminate"]:
            # msg looks like a status value
            status_code = msg
        else:
            # Default to "out" (terminate)
            status_code = "out"
        
        resolved_sfwid = sfwid or subid_1 or subid
        print(f"📥 CPX Callback received: msg={msg}, status={status}, resolved_status={status_code}, trans_id={trans_id}, message_id={message_id}, rid={rid}, sfwid={resolved_sfwid}")
        print(f"📥 Full callback URL: {request.url}")
        
        # sfwid from subid_1 is the PRIMARY identifier - it contains the SFWID (traffic record _id)
        if not resolved_sfwid:
            print(f"❌ Missing sfwid parameter - cannot identify traffic record")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        decoded_sfwid = resolved_sfwid
        print(f"✅ Using sfwid from query params: {decoded_sfwid}")
        
        # Determine status based on msg ("out" treated as terminate)
        if status_code.lower() == "complete":
            new_status = "COMPLETE"
            redirect_type = "completeRD"
        else:  # "out" = terminate
            new_status = "TERMINATED"
            redirect_type = "terminateRD"
        
        # ============================================
        # IMMEDIATE CALLBACK LOGGING: Log every callback attempt for monitoring
        # This ensures visibility even if verification fails or times out
        # ============================================
        initial_log_id = None
        if cpx_callback_logs_collection is not None:
            try:
                initial_log_entry = {
                    "timestamp": datetime.utcnow(),
                    "callback_url": str(request.url),
                    "msg_param": msg,
                    "status_param": status,
                    "status_code": status_code,
                    "new_status": new_status,
                    "redirect_type": redirect_type,
                    "decoded_sfwid": decoded_sfwid,
                    "rid_received": rid,
                    "trans_id": trans_id,
                    "message_id": message_id,
                    "event": "callback_received",
                    "processing_status": "pending",
                    "success": False,  # Will be updated after successful processing
                    "verified": False  # Will be updated after postback verification
                }
                result = cpx_callback_logs_collection.insert_one(initial_log_entry)
                initial_log_id = result.inserted_id
                print(f"📝 Logged initial callback receipt: {initial_log_id}")
            except Exception as log_error:
                print(f"⚠️ Failed to log initial callback: {log_error}")
        
        # P0.15: CPX Callback Idempotency Check
        # Generate callback key: {click_id}:{conversion_type}:{hour_bucket}
        hour_bucket = datetime.utcnow().strftime("%Y%m%d%H")
        callback_key = f"{decoded_sfwid}:{new_status}:{hour_bucket}"
        
        # Check for existing callback with same key (within the hour)
        if cpx_callback_logs_collection is not None:
            existing_callback = cpx_callback_logs_collection.find_one({
                "callback_key": callback_key,
                "success": True
            })
            if existing_callback:
                print(f"⚠️ Duplicate callback detected: {callback_key}")
                # Return the same redirect as before
                existing_redirect = existing_callback.get("vendor_redirect_url")
                if existing_redirect:
                    return RedirectResponse(url=existing_redirect)
                return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        # ============================================
        # POSTBACK VERIFICATION: DISABLED
        # The redirect URL is now the primary source of truth
        # S2S postback verification has been permanently disabled
        # ============================================
        postback_verified = False  # Not using postback verification
        print(f"ℹ️ Postback verification disabled - proceeding directly with redirect flow")
        print(f"📋 Processing redirect: sfwid={decoded_sfwid}, status={new_status}, redirect_type={redirect_type}")
        
        # Step 1: Find the traffic record by _id (SFWID)
        traffic_record = None
        search_values = [decoded_sfwid]
        
        print(f"🔍 Searching for traffic record with SFWID: {search_values}")
        
        if url_parameters_collection is not None:
            for search_val in search_values:
                if traffic_record:
                    break
                    
                # Try to find by ObjectId first
                try:
                    traffic_record = url_parameters_collection.find_one({"_id": ObjectId(search_val)})
                    if traffic_record:
                        print(f"✅ Found traffic record by ObjectId: {search_val}")
                except Exception as e:
                    print(f"⚠️ ObjectId search failed for {search_val}: {e}")
                
                # Try as string _id (same field, different format)
                if not traffic_record:
                    traffic_record = url_parameters_collection.find_one({"_id": search_val})
                    if traffic_record:
                        print(f"✅ Found traffic record by string _id: {search_val}")
                
                # NOTE: respondentId fallback REMOVED - violates deterministic mapping
                # SFWID must resolve to exactly one traffic record via _id field only
        
        if not traffic_record:
            print(f"❌ No traffic record found for SFWID: {decoded_sfwid}")
            # Redirect to error page
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        traffic_id = str(traffic_record["_id"])
        vendor_id = traffic_record.get("vendorId")
        original_respondent_id = traffic_record.get("respondentId")  # This is what we send to the vendor
        
        print(f"📋 Found traffic record: SFWID={traffic_id}, vendorId={vendor_id}, respondentId={original_respondent_id}")
        
        # Step 2: Look up the vendor
        # The vid parameter from URL is stored as vendorId in traffic record
        # This should match vid in the vendors collection
        vendor = None
        vendor_redirect_url = None
        
        if vendors_collection is not None and vendor_id:
            print(f"🔍 Looking up vendor with vid: {vendor_id}")
            
            # Try to find vendor by vid (try both string and original type)
            vendor = vendors_collection.find_one({"vid": vendor_id})
            if not vendor and isinstance(vendor_id, str):
                # Try as integer if it's a numeric string
                if vendor_id.isdigit():
                    try:
                        vendor = vendors_collection.find_one({"vid": int(vendor_id)})
                    except ValueError:
                        pass
            
            if not vendor and isinstance(vendor_id, int):
                # Try as string
                vendor = vendors_collection.find_one({"vid": str(vendor_id)})
            
            if vendor:
                print(f"✅ Found vendor by vid: {vendor_id} - {vendor.get('vendorName')}")
            else:
                print(f"❌ Vendor not found by vid: {vendor_id}")
                # Enhanced debugging
                DEBUG_VENDOR_LIMIT = 10
                all_vendors = list(vendors_collection.find({}, {"vid": 1, "vendorName": 1}))
                print(f"📋 Available vendors (total {len(all_vendors)}):")
                for v in all_vendors[:DEBUG_VENDOR_LIMIT]:  # Show first few for debugging
                    print(f"  - vid: {v.get('vid')} ({type(v.get('vid')).__name__}), name: {v.get('vendorName')}")
        else:
            print(f"⚠️ vendors_collection is None or vendor_id is empty. vendor_id={vendor_id}")
        
        if vendor:
            print(f"📋 Found vendor: {vendor.get('vendorName')}, vid: {vendor.get('vid')}")
            print(f"📋 Vendor _id: {vendor.get('_id')}")
            print(f"📋 Vendor redirect type: {redirect_type}")
            print(f"📋 Full vendor document: {vendor}")
            print(f"📋 Vendor {redirect_type}: {vendor.get(redirect_type, [])}")
            
            # Step 3: Get the appropriate redirect URL array
            redirect_urls = vendor.get(redirect_type, [])
            vendor_variable = vendor.get("vendorVariable", "rid")
            
            print(f"📋 Vendor variable name: {vendor_variable}")
            print(f"📋 All redirect URLs in array: {redirect_urls}")
            
            if redirect_urls and len(redirect_urls) > 0:
                # Use the first redirect URL
                base_url = redirect_urls[0].strip()
                print(f"📋 Base redirect URL (first in array): {base_url}")
                
                if base_url:
                    # Step 4: Append respondent ID using vendor's variable name
                    # The URL might already have query params, so we need to append properly
                    # Check if URL already ends with the variable placeholder (e.g., "&RID=" or "?RID=")
                    if base_url.endswith(f"&{vendor_variable}=") or base_url.endswith(f"?{vendor_variable}="):
                        # URL already has the variable with trailing =, just append the value
                        vendor_redirect_url = f"{base_url}{original_respondent_id}"
                    elif f"&{vendor_variable}=" in base_url or f"?{vendor_variable}=" in base_url:
                        # URL already has the variable somewhere, don't duplicate it
                        # Replace any placeholder value or append at the existing position
                        vendor_redirect_url = base_url
                        print(f"⚠️ URL already contains {vendor_variable}= parameter, using as-is")
                    else:
                        # Need to add the variable and value
                        separator = "&" if "?" in base_url else "?"
                        vendor_redirect_url = f"{base_url}{separator}{vendor_variable}={original_respondent_id}"
                    print(f"🔗 Constructed vendor redirect URL: {vendor_redirect_url}")
            else:
                print(f"⚠️ No redirect URLs configured for {redirect_type}")
        else:
            print(f"❌ Vendor not found for vendor_id: {vendor_id}")
        
        # Step 5: Update traffic record status
        if traffic_service:
            traffic_service.update_traffic_status(
                traffic_id=traffic_id,
                status=new_status,
                redirect_url=str(request.url),
                out_url=vendor_redirect_url
            )
        elif url_parameters_collection:
            update_data = {
                "status": new_status,
                "updatedAt": datetime.utcnow(),
                "cpxCallbackUrl": str(request.url)
            }
            if vendor_redirect_url:
                update_data["outUrl"] = vendor_redirect_url
            if new_status == "COMPLETE":
                update_data["completedAt"] = datetime.utcnow()
            
            url_parameters_collection.update_one(
                {"_id": ObjectId(traffic_id)},
                {"$set": update_data}
            )
        
        print(f"✅ Updated traffic record {traffic_id} status to {new_status}")
        
        # Step 6: Update the initial callback log with complete processing details
        if cpx_callback_logs_collection is not None and initial_log_id:
            try:
                update_fields = {
                    "callback_key": callback_key,  # P0.15: Idempotency key for deduplication
                    "event": "callback_processed",
                    "processing_status": "completed",
                    "traffic_found": True,
                    "traffic_id": traffic_id,
                    "vendor_id": vendor_id,
                    "respondent_id": original_respondent_id,
                    "vendor_found": vendor is not None,
                    "vendor_name": vendor.get("vendorName") if vendor else None,
                    "vendor_redirect_url": vendor_redirect_url,
                    "success": vendor_redirect_url is not None,
                    "verified": postback_verified,
                    "completed_at": datetime.utcnow()
                }
                cpx_callback_logs_collection.update_one(
                    {"_id": initial_log_id},
                    {"$set": update_fields}
                )
                print(f"📝 Updated CPX callback log with processing result")
            except Exception as log_error:
                print(f"⚠️ Failed to update callback log: {log_error}")
        elif cpx_callback_logs_collection is not None:
            # Fallback: insert new log if initial_log_id is not available
            try:
                log_entry = {
                    "timestamp": datetime.utcnow(),
                    "callback_key": callback_key,
                    "callback_url": str(request.url),
                    "msg_param": msg,
                    "status_param": status,
                    "message_id_param": message_id,
                    "rid_received": rid,
                    "decoded_sfwid": decoded_sfwid,
                    "status_code": status_code,
                    "new_status": new_status,
                    "redirect_type": redirect_type,
                    "event": "callback_processed",
                    "processing_status": "completed",
                    "traffic_found": True,
                    "traffic_id": traffic_id,
                    "vendor_id": vendor_id,
                    "respondent_id": original_respondent_id,
                    "vendor_found": vendor is not None,
                    "vendor_name": vendor.get("vendorName") if vendor else None,
                    "vendor_redirect_url": vendor_redirect_url,
                    "success": vendor_redirect_url is not None,
                    "verified": postback_verified
                }
                cpx_callback_logs_collection.insert_one(log_entry)
                print(f"📝 Logged CPX callback (fallback insert)")
            except Exception as log_error:
                print(f"⚠️ Failed to log callback: {log_error}")
        
        # Step 7: Handle redirect based on status
        # COMPLETE → vendor complete URL
        # TERMINATE/SCREENOUT → try CINT fallback before vendor terminate URL
        
        if new_status == "COMPLETE":
            # Complete: redirect to vendor complete URL
            if vendor_redirect_url:
                print(f"➡️ Complete - Redirecting to vendor: {vendor_redirect_url}")
                return RedirectResponse(url=vendor_redirect_url)
            else:
                print(f"➡️ No vendor redirect URL found, redirecting to thank you page")
                return RedirectResponse(url=f"{FRONTEND_URL}/thankyou")
        else:
            # TERMINATED/SCREENOUT: Try CINT fallback
            print(f"🔄 CPX terminated/screened out - attempting CINT fallback for SFWID={traffic_id}")
            
            # Check if already tried CINT (prevent infinite loop)
            cint_already_tried = traffic_record.get("cint_fallback_attempted", False)
            
            if not cint_already_tried:
                try:
                    from pymongo import MongoClient
                    import os
                    import httpx
                    import uuid
                    
                    mongo_uri = os.getenv("MONGO_URI")
                    cint_api_key = os.getenv("CINT_API_KEY")
                    cint_supplier_code = os.getenv("CINT_SUPPLIER_CODE")
                    
                    if mongo_uri and cint_api_key and cint_supplier_code:
                        client = MongoClient(mongo_uri)
                        
                        try:
                            cint_collection = client["cint_research"]["cint_surveys"]
                            entry_links_collection = client["cint_research"]["cint_entry_links"]
                            
                            # Get user's country and respondent ID from traffic record
                            user_country = traffic_record.get("countryCode", "")
                            respondent_id = traffic_record.get("respondentId") or traffic_id
                            
                            cint_query = {
                                "$and": [
                                    {"$or": [{"is_active": True}, {"is_active": {"$exists": False}}]},
                                    {"$or": [{"is_live": True}, {"is_live": {"$exists": False}}]},
                                    {"$or": [{"is_active_in_pool": True}, {"is_active_in_pool": {"$exists": False}}]}
                                ]
                            }
                            
                            if user_country:
                                # Use country_code field (added by migration) for direct matching
                                cint_query["country_code"] = user_country.upper()
                            
                            cint_surveys = list(cint_collection.find(cint_query).limit(150))
                            
                            if cint_surveys:
                                import random
                                random.shuffle(cint_surveys)
                                
                                # Try surveys until one works (limited to 100)
                                # Use RESPONDENT-LEVEL entry links (not project-level)
                                success = False
                                for selected_survey in cint_surveys[:100]:
                                    if success:
                                        break
                                    cint_survey_id = str(selected_survey.get('survey_id') or selected_survey.get('_id'))
                                    
                                    try:
                                        # Use respondent-level entry link (Cint Exchange correct model)
                                        from app.services.cint_entrylink_service import CintEntryLinkService
                                        
                                        entrylink_service = CintEntryLinkService(
                                            api_key=cint_api_key,
                                            encryption_key=os.getenv("CINT_ENCRYPTION_KEY") or os.getenv("CINT_WEBHOOK_SECRET"),
                                        )
                                        
                                        import asyncio
                                        result = asyncio.get_event_loop().run_until_complete(
                                            entrylink_service.create_entry_link(
                                                survey_id=cint_survey_id,
                                                respondent_id=respondent_id,
                                            )
                                        )
                                        
                                        if result.get("success") and result.get("live_link"):
                                            cint_entry_link = result["live_link"]
                                            
                                            # Mark fallback attempted and store CINT info
                                            if url_parameters_collection is not None:
                                                url_parameters_collection.update_one(
                                                    {"_id": ObjectId(traffic_id)},
                                                    {"$set": {
                                                        "cint_fallback_attempted": True,
                                                        "cint_survey_id": cint_survey_id,
                                                        "cint_entry_link": cint_entry_link,
                                                        "status": "CPX_TERMINATED_CINT_FALLBACK",
                                                        "updatedAt": datetime.utcnow()
                                                    }}
                                                )
                                            
                                            print(f"✅ CINT fallback (respondent-level): Redirecting SFWID={traffic_id} to survey {cint_survey_id}")
                                            success = True
                                            return RedirectResponse(url=cint_entry_link)
                                        
                                        elif result.get("should_mark_inactive"):
                                            # Survey not found / inactive - mark it
                                            print(f"⚠️ CINT fallback: Survey {cint_survey_id} inactive (404), marking and trying next")
                                            cint_collection.update_one(
                                                {"survey_id": int(cint_survey_id)},
                                                {"$set": {"is_active": False, "is_active_in_pool": False}}
                                            )
                                            continue
                                        
                                        else:
                                            print(f"⚠️ CINT fallback: Survey {cint_survey_id} failed: {result.get('error')}, trying next")
                                            continue
                                            
                                    except Exception as survey_err:
                                        print(f"⚠️ CINT fallback: Survey {cint_survey_id} failed: {survey_err}, trying next")
                                        continue
                                
                                if not success:
                                    print(f"⚠️ CINT fallback: All surveys exhausted for country {user_country}")
                            else:
                                print(f"⚠️ CINT fallback: No active surveys for country {user_country}")
                        finally:
                            client.close()
                    else:
                        print(f"⚠️ CINT fallback: Missing credentials")
                except Exception as cint_err:
                    print(f"⚠️ CINT fallback error: {cint_err}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"⚠️ CINT fallback already attempted for SFWID={traffic_id}, sending to vendor terminate")
            
            # Fallback to vendor terminate URL if CINT fallback fails
            if vendor_redirect_url:
                print(f"➡️ Terminate - Redirecting to vendor: {vendor_redirect_url}")
                return RedirectResponse(url=vendor_redirect_url)
            else:
                print(f"➡️ No vendor redirect URL found, redirecting to error page")
                return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
    except Exception as e:
        print(f"❌ Error in CPX callback: {e}")
        import traceback
        traceback.print_exc()
        
        # Enhanced error logging
        error_log = {
            "timestamp": datetime.utcnow(),
            "callback_url": str(request.url),
            "msg_param": msg,
            "status_param": status,
            "message_id_param": message_id,
            "rid_received": rid,
            "trans_id": trans_id,
            "sfwid_param": sfwid,
            "subid_1_param": subid_1,
            "subid_param": subid,
            "status_code": status or msg or "unknown",
            "traffic_found": False,
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        
        if cpx_callback_logs_collection is not None:
            try:
                cpx_callback_logs_collection.insert_one(error_log)
                print(f"📝 Logged error to callback logs")
            except Exception as log_err:
                print(f"⚠️ Failed to log error: {log_err}")
        
        # Always redirect to error page on error
        return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")


@router.get("/api/cpx-callback-logs")
async def get_cpx_callback_logs(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Records per page"),
    success_filter: Optional[str] = Query(None, description="Filter by success status: true/false/all"),
):
    """
    Get CPX callback logs for monitoring
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if cpx_callback_logs_collection is None:
            raise HTTPException(status_code=503, detail="Callback logs collection not initialized")
        
        # Build query
        query = {}
        if success_filter == "true":
            query["success"] = True
        elif success_filter == "false":
            query["success"] = False
        
        # Get total count
        total = cpx_callback_logs_collection.count_documents(query)
        
        # Calculate pagination
        skip = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        
        # Fetch logs (newest first)
        logs = list(
            cpx_callback_logs_collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        # Convert ObjectId to string
        for log in logs:
            log["_id"] = str(log["_id"])
            if log.get("timestamp"):
                log["timestamp"] = log["timestamp"].isoformat()
        
        # Get stats
        success_count = cpx_callback_logs_collection.count_documents({"success": True})
        failed_count = cpx_callback_logs_collection.count_documents({"success": False})
        
        return {
            "logs": logs,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages
            },
            "stats": {
                "total": total,
                "success": success_count,
                "failed": failed_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching CPX callback logs: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.delete("/api/cpx-callback-logs")
async def clear_cpx_callback_logs(request: Request):
    """
    Clear all CPX callback logs
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if cpx_callback_logs_collection is None:
            raise HTTPException(status_code=503, detail="Callback logs collection not initialized")
        
        result = cpx_callback_logs_collection.delete_many({})
        
        return {
            "message": "Logs cleared",
            "deleted_count": result.deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error clearing CPX callback logs: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ===================================================================================
# ZERO-DELAY IP PREFETCH ENDPOINT
# ===================================================================================
# This endpoint is called when the parsing page loads (before user clicks PROCEED)
# It captures the user's real IP from server headers (CloudFlare/Nginx) instantly
# This eliminates the 3-9 second delay of calling external IP services
# ===================================================================================

@router.get("/api/prefetch-ip")
async def prefetch_client_ip(request: Request):
    """
    Instantly capture client IP from server headers on page load.
    
    This endpoint replaces the slow external IP service calls (ipify, ipinfo, ip.sb)
    by using CloudFlare/Nginx headers that are already available on every request.
    
    Benefits:
    - Instant (0ms) vs 3-9 seconds from external APIs
    - More reliable (always available, never fails)
    - Same IP the user will have when clicking through to CPX surveys
    
    Called by: TrafficFlowParser.jsx on component mount
    
    Returns:
        {
            "ip": "123.45.67.89",
            "source": "CF-Connecting-IP" | "X-Forwarded-For" | "X-Real-IP" | "direct",
            "userAgent": "Mozilla/5.0...",
            "timestamp": "2026-02-04T10:30:00.000Z"
        }
    """
    try:
        # Import IP extraction utilities
        try:
            from ..utils import extract_real_client_ip, extract_user_agent
        except ImportError:
            from utils import extract_real_client_ip, extract_user_agent
        
        # Extract IP from headers (instant, no external calls)
        client_ip, ip_source = extract_real_client_ip(request)
        user_agent = extract_user_agent(request)
        
        # Log for monitoring
        print(f"📍 Prefetch IP: {client_ip} (source: {ip_source})")
        
        return JSONResponse(content={
            "ip": client_ip,
            "source": ip_source,
            "userAgent": user_agent,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        
    except Exception as e:
        print(f"❌ Prefetch IP error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "ip": None,
                "source": "error",
                "error": str(e)
            }
        )


@router.post("/api/store")
async def store_url_params(request: Request, data: Dict[str, Any] = Body(...)):
    """
    Store URL parameters from survey tracking
    Creates a traffic record with vid, cc, rid if available
    Also attempts to allocate a survey to the respondent
    
    ZERO-DELAY OPTIMIZATION:
    - Client may provide prefetched IP from /api/prefetch-ip endpoint
    - If client provides valid IP, use it (maintains consistency with prefetch)
    - Otherwise, extract from server headers as fallback
    """
    try:
        if url_parameters_collection is None:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        # Extract traffic parameters
        params = data.get('params', {})
        vendor_id = params.get('vid', '')
        country_code = params.get('cc', '')
        respondent_id = params.get('rid', '')
        
        traffic_id = None
        entry_link = None
        survey_id = None
        allocation_success = False
        allocation_error = None  # Track allocation failure reason for debugging
        
        # ===================================================================================
        # IP EXTRACTION: Prefer client-provided (from prefetch), fallback to server headers
        # ===================================================================================
        # The frontend calls /api/prefetch-ip on page load which returns server-side IP
        # The client then sends this IP in the request body for consistency
        # If client doesn't provide IP, we extract it ourselves from headers
        
        # Import utilities for server-side extraction
        try:
            from ..utils import extract_real_client_ip, extract_user_agent
        except ImportError:
            from utils import extract_real_client_ip, extract_user_agent
        
        # Check if client provided IP (from browser-based collection)
        client_provided_ip = data.get('clientIp')
        client_ip_source = data.get('ipSource', 'unknown')

        # Validate client-provided IP (accept both IPv4 and IPv6)
        def is_valid_ip(ip_str):
            """Check if IP is valid (IPv4 or IPv6)"""
            if not ip_str or not isinstance(ip_str, str):
                return False
            # IPv4: contains dots
            # IPv6: contains colons
            # Basic validation - more robust than just checking for dots
            return ('.' in ip_str and ip_str.replace('.', '').replace(':', '').isdigit()) or \
                   (':' in ip_str and all(c in '0123456789abcdefABCDEF:' for c in ip_str))

        if client_provided_ip and is_valid_ip(client_provided_ip):
            # Use client-provided IP (from browser - CRITICAL for CPX compatibility)
            client_ip = client_provided_ip
            print(f"📍 Using browser-collected IP: {client_ip} (source: {client_ip_source})")
            print(f"   ✅ This IP will match what CPX sees when user clicks survey")
        else:
            # Fallback: Extract from server headers (may cause mismatch on mobile)
            client_ip, client_ip_source = extract_real_client_ip(request)
            print(f"📍 Using server-extracted IP: {client_ip} (source: {client_ip_source})")
            print(f"   ⚠️ Server IP may differ from browser IP on mobile networks")
        
        # Extract User-Agent from request headers (for CPX fingerprint matching)
        client_user_agent = data.get('userAgent') or request.headers.get("User-Agent") or ""
        print(f"📱 User-Agent: {client_user_agent[:80]}..." if len(client_user_agent) > 80 else f"📱 User-Agent: {client_user_agent}")
        
        # Extract device fingerprint from client
        device_fingerprint = data.get('deviceFingerprint', '')
        fingerprint_components = data.get('fingerprintComponents', {})
        
        # Extract email from client (mandatory field)
        user_email = data.get('email', '').strip()
        if user_email:
            print(f"📧 User email: {user_email}")

        # Extract CPX User Profiling Parameters (CRITICAL for survey matching)
        birthday_day = data.get('birthday_day')
        birthday_month = data.get('birthday_month')
        birthday_year = data.get('birthday_year')
        gender = data.get('gender', '').strip().lower()
        zip_code = data.get('zip_code', '').strip()

        # Log profiling data if provided
        if birthday_day and birthday_month and birthday_year:
            print(f"📅 User DOB: {birthday_year}-{birthday_month:02d}-{birthday_day:02d}")
        if gender:
            print(f"⚧ User gender: {gender}")
        if zip_code:
            print(f"📮 User zip/postal code: {zip_code}")

        # Log IP extraction for debugging
        if not client_ip:
            print("⚠️ WARNING: No valid IP could be extracted! CPX API targeting may fail.")
        
        # ===================================================================================
        # STEP 1: CREATE TRAFFIC RECORD (SFWID)
        # ===================================================================================
        
        # If traffic service is available and we have the required params, use it
        if traffic_service and vendor_id and country_code and respondent_id:
            try:
                traffic_id = traffic_service.create_traffic_record(
                    vendor_id=vendor_id,
                    country_code=country_code,
                    respondent_id=respondent_id,
                    url=data.get('url'),
                    user_agent=client_user_agent,
                    params=params,
                    client_ip=client_ip,
                    ip_source=client_ip_source,
                    device_fingerprint=device_fingerprint,
                    fingerprint_source="client",
                    fingerprint_components=fingerprint_components,
                    email=user_email
                )
                print(f"✅ Created traffic record (SFWID): {traffic_id}")
            except Exception as e:
                print(f"⚠️ Failed to create traffic record, falling back to legacy: {e}")
        
        # Legacy fallback - store as before
        if not traffic_id:
            data['timestamp'] = datetime.utcnow().isoformat()
            data['status'] = 'incomplete'
            data['redirectUrl'] = None
            data['email'] = user_email  # Store email in legacy records too
            # Store respondentId at top level for /cpx/redirect fallback lookup
            data['respondentId'] = respondent_id
            data['vendorId'] = vendor_id
            data['countryCode'] = country_code
            result = url_parameters_collection.insert_one(data)
            traffic_id = str(result.inserted_id)
        
        # ===============================================================================
        # ALTERNATING CPX/CINT ALLOCATION (Load Balancing)
        # ===============================================================================
        # Respondent ID for BOTH CPX and CINT is the SFWID (traffic_id)
        # This ensures unique tracking per respondent across both providers
        # Provider is selected based on hash of traffic_id (deterministic 50/50 split)
        # ===============================================================================
        
        # CPX-FIRST ALLOCATION STRATEGY
        # Always try CPX first, fallback to CINT if CPX fails or has no surveys
        # On CPX terminate/screenout, user will be redirected to CINT via /cpx-response handler
        primary_provider = "CPX"
        
        print(f"🔀 Provider strategy: CPX first, CINT fallback. SFWID={traffic_id}")
        print(f"🆔 Using SFWID '{traffic_id}' as respondent ID for both CPX and CINT")
        
        # DEBUG: Log allocation check
        print(f"🔍 Allocation check: allocation_success={allocation_success}, vendor_id={vendor_id}, country_code={country_code}, SFWID={traffic_id}")
        
        # ============================================
        # IP CONSISTENCY VALIDATION
        # ============================================
        # Compare browser-collected IP vs server-extracted IP to detect routing issues
        # This helps diagnose mobile carrier NAT/CGNAT problems
        server_extracted_ip, server_ip_source = extract_real_client_ip(request)

        if client_provided_ip and server_extracted_ip:
            ip_match = client_provided_ip == server_extracted_ip

            if ip_match:
                print(f"✅ IP MATCH: Browser IP matches server IP: {client_provided_ip}")
                print(f"   This is ideal - CPX will see the same IP")
            else:
                print(f"⚠️ IP MISMATCH DETECTED:")
                print(f"   Browser IP (from ipify.org): {client_provided_ip}")
                print(f"   Server IP (from {server_ip_source}): {server_extracted_ip}")
                print(f"   Likely cause: Mobile carrier NAT or multi-path routing")
                print(f"   CPX WILL USE: {client_ip} (browser-collected, more accurate)")
                print(f"   If screenout occurs, this mismatch may be why")

        # Validate we have a usable IP for survey providers
        if not client_ip or client_ip in ['127.0.0.1', 'localhost', '0.0.0.0', '::1']:
            print(f"❌ CRITICAL: Invalid IP: {client_ip}")
            print(f"   Survey providers require real public IP address")
            allocation_error = f"Invalid client IP ({client_ip}) - cannot call survey API"
        
        # ============================================
        # HELPER FUNCTION: CPX Allocation
        # ============================================
        def try_cpx_allocation():
            nonlocal allocation_success, entry_link, survey_id, allocation_error
            
            if not cpx_service:
                print("⚠️ CPX service not available")
                return False
                
            # WebView Detection
            is_webview, webview_signature = is_webview_user_agent(client_user_agent)
            if is_webview:
                print(f"🚫 CPX WEBVIEW BLOCK: User agent contains WebView signature '{webview_signature}'")
                return False
            
            # Guard check using SFWID (traffic_id) as ext_user_id
            guard_result = check_cpx_entry_guard(traffic_id, client_ip, client_user_agent)
            if not guard_result["allowed"]:
                print(f"🚫 CPX ENTRY GUARD BLOCK: {guard_result['reason']} (existing status: {guard_result['existing_status']})")
                return False
            
            try:
                print(f"📍 CPX: IP={client_ip}, SFWID={traffic_id}")
                print(f"🔑 Using SFWID '{traffic_id}' as ext_user_id for CPX")
                
                # Generate CPX session MID and pass in subid_1 for tracking
                import uuid
                cpx_mid = uuid.uuid4().hex[:16]
                
                result = cpx_service.fetch_and_allocate_for_respondent(
                    vendor_user_id=traffic_id,           # Use SFWID as ext_user_id
                    internal_tracking_id=f"{traffic_id}_{cpx_mid}",  # SFWID + MID in subid_1
                    user_ip=client_ip,
                    user_agent=client_user_agent,
                    country_code=country_code,
                    email=user_email,
                    birthday_day=birthday_day,
                    birthday_month=birthday_month,
                    birthday_year=birthday_year,
                    gender=gender,
                    zip_code=zip_code,
                )
                
                if result.get("success"):
                    entry_link = result.get("entry_link", "")
                    survey_id = result.get("survey_id", "")
                    allocation_success = True
                    
                    # Update guard status to REDIRECTED
                    update_cpx_entry_guard_status(
                        ext_user_id=traffic_id,
                        new_status=CPX_GUARD_STATUS_REDIRECTED,
                        survey_id=str(survey_id),
                        entry_link=entry_link
                    )
                    
                    # Update traffic record with CPX MID
                    if traffic_service:
                        traffic_service.assign_survey_to_traffic(
                            traffic_id=traffic_id,
                            survey_id=str(survey_id),
                            redirect_url=entry_link
                        )
                    
                    # Always store CPX MID for tracking
                    if url_parameters_collection is not None:
                        url_parameters_collection.update_one(
                            {"_id": ObjectId(traffic_id)},
                            {"$set": {
                                "status": "INCOMPLETE",
                                "assignedSurveyId": str(survey_id),
                                "redirectUrl": entry_link,
                                "surveySource": "CPX",
                                "cpx_mid": cpx_mid,
                                "updatedAt": datetime.utcnow().isoformat(),
                            }}
                        )
                    
                    print(f"✅ CPX allocated survey {survey_id} to SFWID={traffic_id} (cpx_mid={cpx_mid})")
                    return True
                else:
                    print(f"⚠️ CPX returned no surveys: {result.get('error', 'unknown')}")
                    # Mark as LOCKED since CPX API was called
                    update_cpx_entry_guard_status(
                        ext_user_id=traffic_id,
                        new_status=CPX_GUARD_STATUS_LOCKED,
                        survey_id=None,
                        entry_link=None
                    )
                    return False
                    
            except Exception as e:
                print(f"⚠️ CPX allocation error: {e}")
                update_cpx_entry_guard_status(
                    ext_user_id=traffic_id,
                    new_status=CPX_GUARD_STATUS_LOCKED,
                    survey_id=None,
                    entry_link=None
                )
                return False
        
        # ============================================
        # HELPER FUNCTION: CINT Allocation
        # ============================================
        def try_cint_allocation():
            nonlocal allocation_success, entry_link, survey_id, allocation_error
            
            try:
                from pymongo import MongoClient
                import os
                import httpx
                
                mongo_uri = os.getenv("MONGO_URI")
                if not mongo_uri:
                    print("❌ MONGO_URI not configured for CINT")
                    return False
                
                # CINT API credentials
                cint_api_key = os.getenv("CINT_API_KEY")
                cint_supplier_code = os.getenv("CINT_SUPPLIER_CODE")
                
                if not cint_api_key or not cint_supplier_code:
                    print("❌ CINT API credentials not configured")
                    return False
                
                client = MongoClient(mongo_uri)

                try:
                    # Get active CINT surveys matching user's country
                    cint_collection = client["cint_research"]["cint_surveys"]

                    # Map country code to CINT country_language suffix
                    # CINT uses format like "eng_us", "eng_gb", "eng_in", "spa_mx", etc.
                    country_suffix = country_code.lower() if country_code else ""

                    # Prefer is_active_in_pool when available; otherwise fall back to is_active/is_live
                    cint_query = {
                        "$or": [
                            {"is_active_in_pool": True},
                            {
                                "is_active_in_pool": {"$exists": False},
                                "is_active": True,
                                "$or": [
                                    {"is_live": True},
                                    {"is_live": {"$exists": False}}
                                ]
                            },
                        ]
                    }

                    # Add country filter if we have a country code
                    if country_suffix:
                        # Filter by country_language ending with user's country code
                        cint_query["country_language"] = {"$regex": f"_{country_suffix}$", "$options": "i"}
                    print(f"🌍 CINT filtering surveys for country: {country_suffix}")

                    cint_surveys = list(cint_collection.find(cint_query).limit(50))

                    if not cint_surveys:
                        print(f"⚠️ No active CINT surveys available for country: {country_suffix or 'any'}")
                        return False

                    # Select a random survey
                    selected_survey = random.choice(cint_surveys)
                    raw_survey_id = selected_survey.get('survey_id') or selected_survey.get('_id')

                    if not raw_survey_id:
                        print("⚠️ Selected survey has no survey_id or _id field")
                        return False

                    survey_id = str(raw_survey_id)

                    print(f"🎯 CINT selected survey: {survey_id} (country: {selected_survey.get('country_language')})")

                    # Use RESPONDENT-LEVEL entry link (Cint Exchange correct model)
                    # NO caching - create fresh per respondent
                    from app.services.cint_entrylink_service import CintEntryLinkService
                    
                    try:
                        entrylink_service = CintEntryLinkService(
                            api_key=cint_api_key,
                            encryption_key=os.getenv("CINT_ENCRYPTION_KEY") or os.getenv("CINT_WEBHOOK_SECRET"),
                        )
                        
                        import asyncio
                        result = asyncio.get_event_loop().run_until_complete(
                            entrylink_service.create_entry_link(
                                survey_id=survey_id,
                                respondent_id=traffic_id,
                            )
                        )
                        
                        if not result.get("success") or not result.get("live_link"):
                            print(f"❌ Could not create respondent entry link for CINT survey {survey_id}: {result.get('error')}")
                            
                            # If survey inactive, mark it
                            if result.get("should_mark_inactive"):
                                cint_collection.update_one(
                                    {"survey_id": int(survey_id)},
                                    {"$set": {"is_active": False, "is_active_in_pool": False}}
                                )
                            return False
                        
                        entry_link = result["live_link"]
                        print(f"🔗 CINT respondent entry link: {entry_link[:100]}...")
                        
                    except Exception as entrylink_err:
                        print(f"❌ CINT entry link service error: {entrylink_err}")
                        return False

                    allocation_success = True

                    # Update traffic record
                    if traffic_service:
                        traffic_service.assign_survey_to_traffic(
                            traffic_id=traffic_id,
                            survey_id=survey_id,
                            redirect_url=entry_link
                        )
                    else:
                        url_parameters_collection.update_one(
                            {"_id": ObjectId(traffic_id)},
                            {"$set": {
                                "status": "INCOMPLETE",
                                "assignedSurveyId": survey_id,
                                "redirectUrl": entry_link,
                                "surveySource": "CINT",
                                "cint_entry_link_type": "RESPONDENT",  # Mark as respondent-level link
                                "updatedAt": datetime.utcnow().isoformat(),
                            }}
                        )

                    print(f"✅ CINT allocated survey {survey_id} to SFWID={traffic_id}")
                    return True

                except Exception as e:
                    print(f"⚠️ CINT allocation error: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
                finally:
                    client.close()

            except Exception as outer_e:
                print(f"⚠️ CINT allocation setup failed: {outer_e}")
                import traceback
                traceback.print_exc()
                return False
        
        # ============================================
        # MAIN ALLOCATION LOGIC: Alternate CPX/CINT
        # ============================================
        actual_provider = None  # Track which provider was actually used
        
        if not allocation_success and vendor_id and country_code and traffic_id:
            if primary_provider == "CPX":
                # Try CPX first, fallback to CINT
                print("🔄 Trying CPX (primary)...")
                if try_cpx_allocation():
                    actual_provider = "CPX"
                else:
                    print("🔄 CPX failed, trying CINT (fallback)...")
                    if try_cint_allocation():
                        actual_provider = "CINT"
            else:
                # Try CINT first, fallback to CPX
                print("🔄 Trying CINT (primary)...")
                if try_cint_allocation():
                    actual_provider = "CINT"
                else:
                    print("🔄 CINT failed, trying CPX (fallback)...")
                    if try_cpx_allocation():
                        actual_provider = "CPX"
        
        # Build response with diagnostic info
        response_data = {
            "id": traffic_id,
            "type": "traffic_record" if traffic_service else "legacy",
            "allocation_success": allocation_success,
            "entry_link": entry_link,
            "survey_id": survey_id,
            "survey_provider": actual_provider,
            "primary_provider": primary_provider
        }
        
        # Include allocation error for debugging (only if allocation failed)
        if not allocation_success and allocation_error:
            response_data["allocation_error"] = allocation_error
            response_data["debug_info"] = {
                "client_ip": client_ip,
                "country_code": country_code,
                "cpx_service_available": cpx_service is not None,
                "cint_service_available": cint_service is not None
            }
        
        return response_data
        
    except Exception as e:
        print(f"Error storing URL parameters: {e}")
        raise HTTPException(status_code=500, detail=f"Store error: {str(e)}")


@router.get("/cpx/redirect")
async def cpx_redirect(request: Request, id: str = Query(..., description="Traffic record ID (SFWID)")):
    """
    Pure HTTP redirect to the survey entry link stored on the traffic record.
    Supports both CPX and CINT survey links.
    This avoids JS-based redirects and preserves the exact href returned by the provider.
    """
    try:
        if url_parameters_collection is None:
            raise HTTPException(status_code=500, detail="Database not connected")

        def is_valid_survey_link(url: str) -> bool:
            """Check if URL is a valid CPX or CINT survey link"""
            valid_prefixes = [
                "https://click.cpx-research.com/",
                "https://offers.cpx-research.com/",
                "https://samplicio.us/",
                "https://www.samplicio.us/",
                "https://s.samplicio.us/",
            ]
            return any(url.startswith(prefix) for prefix in valid_prefixes)

        try:
            record = url_parameters_collection.find_one({"_id": ObjectId(id)})
        except Exception:
            record = None

        if not record:
            print(f"❌ Survey redirect: traffic record not found (id={id})")
            raise HTTPException(status_code=404, detail="Traffic record not found")

        entry_link = record.get("redirectUrl") or record.get("redirect_url") or ""
        entry_source = record.get("surveySource", "unknown")

        # Don't clear entry_link if it's a valid survey link
        if entry_link and not is_valid_survey_link(entry_link):
            # Check if it might be a CPX guard link
            entry_link = ""

        # Fallback: Try CPX guard for CPX allocated surveys
        if not entry_link and cpx_entry_guards_collection:
            # Use traffic_id (SFWID) as the guard key since that's now the ext_user_id
            guard_key = str(record.get("_id"))
            if guard_key:
                guard_doc = cpx_entry_guards_collection.find_one({"ext_user_id": guard_key})
                guard_link = guard_doc.get("entry_link") if guard_doc else ""
                if guard_link and is_valid_survey_link(guard_link):
                    entry_link = guard_link
                    entry_source = "cpx_entry_guard"

        if not entry_link:
            print(
                "❌ Survey redirect: entry link not available "
                f"(id={id}, source={entry_source})"
            )
            raise HTTPException(status_code=404, detail="Entry link not available")

        # Validate the link
        if not is_valid_survey_link(entry_link):
            print(
                "❌ Survey redirect: invalid entry link "
                f"(id={id}, url={entry_link[:120]}...)")
            raise HTTPException(status_code=400, detail="Invalid survey entry link")

        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")[:160]
        print(
            f"✅ Survey redirect: sending user to {entry_source} survey "
            f"(id={id}, ip={client_ip}, ua={user_agent})"
        )

        return RedirectResponse(url=entry_link, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ CPX redirect error: {e}")
        raise HTTPException(status_code=500, detail="Redirect error")


@router.get("/surveycomplete")
async def survey_complete(request: Request, rid: str = Query(None)):
    """
    Survey completion callback
    Updates status to 'complete' and redirects
    """
    try:
        if rid:
            # Try traffic service first
            if traffic_service:
                traffic_service.update_traffic_status(
                    traffic_id=rid,
                    status="COMPLETE",
                    redirect_url=str(request.url)
                )
            # Fallback to direct collection update
            elif url_parameters_collection:
                url_parameters_collection.update_one(
                    {"_id": ObjectId(rid)},
                    {"$set": {"status": "complete", "redirectUrl": str(request.url)}}
                )
        return RedirectResponse(url=ZOHO_COMPLETE_URL)
    except Exception as e:
        print(f"Error in survey_complete: {e}")
        # Still redirect even if update fails
        return RedirectResponse(url=ZOHO_COMPLETE_URL)


@router.get("/surveyterminate")
async def survey_terminate(request: Request, rid: str = Query(None)):
    """
    Survey termination callback
    Updates status to 'terminated' and redirects
    """
    try:
        if rid:
            # Try traffic service first
            if traffic_service:
                traffic_service.update_traffic_status(
                    traffic_id=rid,
                    status="TERMINATED",
                    redirect_url=str(request.url)
                )
            # Fallback to direct collection update
            elif url_parameters_collection:
                url_parameters_collection.update_one(
                    {"_id": ObjectId(rid)},
                    {"$set": {"status": "terminated", "redirectUrl": str(request.url)}}
                )
        return RedirectResponse(url=ZOHO_TERMINATE_URL)
    except Exception as e:
        print(f"Error in survey_terminate: {e}")
        # Still redirect even if update fails
        return RedirectResponse(url=ZOHO_TERMINATE_URL)


@router.get("/surveyquotafull")
async def survey_quotafull(request: Request, rid: str = Query(None)):
    """
    Survey quota full callback
    Updates status to 'quotafull' and redirects
    """
    try:
        if rid:
            # Try traffic service first
            if traffic_service:
                traffic_service.update_traffic_status(
                    traffic_id=rid,
                    status="QUOTAFULL",
                    redirect_url=str(request.url)
                )
            # Fallback to direct collection update
            elif url_parameters_collection:
                url_parameters_collection.update_one(
                    {"_id": ObjectId(rid)},
                    {"$set": {"status": "quotafull", "redirectUrl": str(request.url)}}
                )
        return RedirectResponse(url=ZOHO_QUOTA_URL)
    except Exception as e:
        print(f"Error in survey_quotafull: {e}")
        # Still redirect even if update fails
        return RedirectResponse(url=ZOHO_QUOTA_URL)


@router.get("/api/health")
async def health():
    """
    Health check endpoint for traffic flow API
    """
    return {"status": "ok", "service": "traffic-flow"}


@router.get("/api/traffic/stats")
async def get_traffic_stats(
    request: Request,
    survey_id: str = Query(None, description="Optional survey ID to filter stats")
):
    """
    Get traffic statistics by status, optionally filtered by survey_id
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        stats = traffic_service.get_traffic_stats(survey_id=survey_id)
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting traffic stats: {e}")
        raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")


@router.get("/traffic/surveys-stats")
async def get_all_surveys_traffic_stats(request: Request):
    """
    Get aggregated traffic statistics (clicks and completes) for all surveys.
    Returns survey_id -> {"clicks": int, "completes": int} mapping.
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        surveys_stats = traffic_service.get_all_surveys_traffic_stats()
        return {"surveys_stats": surveys_stats}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting all surveys traffic stats: {e}")
        raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")


@router.post("/api/traffic/assign-survey")
async def assign_survey_batch(
    request: Request,
    data: Dict[str, Any] = Body(...)
):
    """
    Assign a survey to a batch of NEW traffic records
    
    Body:
    {
        "survey_id": "57572480",
        "survey_url": "https://offers.cpx-research.com/index.php",
        "client_id": "10754",
        "batch_size": 100
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        # Extract parameters
        survey_id = data.get('survey_id')
        survey_url = data.get('survey_url')
        client_id = data.get('client_id')
        batch_size = data.get('batch_size', 100)
        
        if not all([survey_id, survey_url, client_id]):
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: survey_id, survey_url, client_id"
            )
        
        # Perform batch assignment
        result = traffic_service.batch_assign_surveys(
            survey_id=survey_id,
            survey_url=survey_url,
            client_id=client_id,
            batch_size=batch_size
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error assigning survey batch: {e}")
        raise HTTPException(status_code=500, detail=f"Assignment error: {str(e)}")


@router.get("/api/traffic/new-batch")
async def get_new_traffic_batch(
    request: Request,
    batch_size: int = Query(100, ge=1, le=1000, description="Batch size (1-1000)")
):
    """
    Get a batch of NEW traffic records
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        batch = traffic_service.get_new_traffic_batch(batch_size)
        
        return {
            "count": len(batch),
            "batch_size": batch_size,
            "records": batch
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting traffic batch: {e}")
        raise HTTPException(status_code=500, detail=f"Batch error: {str(e)}")


@router.get("/api/traffic/list")
async def list_traffic_records(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Records per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search term"),
    survey_id: Optional[str] = Query(None, description="Filter by survey ID"),
    bypass_cache: bool = Query(False, description="Force fresh data"),
):
    """
    List all traffic records with pagination and optional filters
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        # Check cache first (skip if bypass_cache or search query)
        cache_key = _get_traffic_cache_key(
            "list", page=page, page_size=page_size, 
            status=status, search=search, survey_id=survey_id
        )
        
        # Don't cache search queries as they're usually unique
        if not bypass_cache and not search:
            cached_result = _get_traffic_cached(cache_key)
            if cached_result is not None:
                return cached_result
        
        result = traffic_service.list_traffic_records(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            survey_id=survey_id,
        )
        
        # Cache the result (skip search queries)
        if not search:
            _set_traffic_cached(cache_key, result)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error listing traffic records: {e}")
        raise HTTPException(status_code=500, detail=f"List error: {str(e)}")


@router.delete("/api/traffic/delete")
async def delete_traffic_records(
    request: Request,
    data: Dict[str, Any] = Body(...)
):
    """
    Delete multiple traffic records by IDs
    
    Body:
    {
        "ids": ["id1", "id2", "id3"]
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        ids = data.get('ids', [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        # Convert string IDs to ObjectId and delete
        object_ids = []
        for id_str in ids:
            try:
                object_ids.append(ObjectId(id_str))
            except Exception:
                pass  # Skip invalid IDs
        
        if not object_ids:
            raise HTTPException(status_code=400, detail="No valid IDs provided")
        
        result = traffic_service.traffic_collection.delete_many({"_id": {"$in": object_ids}})
        
        return {
            "deleted_count": result.deleted_count,
            "requested_count": len(ids)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting traffic records: {e}")
        raise HTTPException(status_code=500, detail=f"Delete error: {str(e)}")


# ============================================================================
# ASYNC TRAFFIC ENDPOINTS
# ============================================================================
# These endpoints return immediately with operation_id for long-running tasks

@router.post("/api/traffic/async/batch-assign")
async def start_async_batch_assign(
    request: Request,
    data: Dict[str, Any] = Body(...)
):
    """
    Start async batch survey assignment for traffic records
    Returns operation_id immediately, poll for status
    
    Body:
    {
        "traffic_ids": ["id1", "id2", ...],
        "survey_id": "survey_id"
    }
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        traffic_ids = data.get('traffic_ids', [])
        survey_id = data.get('survey_id')
        
        if not traffic_ids:
            raise HTTPException(status_code=400, detail="No traffic IDs provided")
        if not survey_id:
            raise HTTPException(status_code=400, detail="No survey ID provided")
        
        # Start async task
        try:
            from ..tasks.async_helpers import start_batch_assign_surveys
            operation_id = start_batch_assign_surveys(traffic_ids, survey_id)
            
            return {
                "status": "started",
                "operation_id": operation_id,
                "poll_url": f"/operations/async/{operation_id}/status",
                "message": f"Batch assignment started for {len(traffic_ids)} records"
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="Async tasks not configured")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting async batch assign: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/traffic/async/bulk-delete")
async def start_async_bulk_delete(
    request: Request,
    data: Dict[str, Any] = Body(...)
):
    """
    Start async bulk delete of traffic records
    Returns operation_id immediately, poll for status
    
    Body:
    {
        "filter": {"status": "complete", "created_before": "2024-01-01"}
    }
    or
    {
        "ids": ["id1", "id2", ...]
    }
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        filter_criteria = data.get('filter', {})
        ids = data.get('ids', [])
        
        if not filter_criteria and not ids:
            raise HTTPException(status_code=400, detail="Provide either filter or ids")
        
        try:
            from ..tasks.async_helpers import start_bulk_delete_traffic
            operation_id = start_bulk_delete_traffic(filter_criteria if filter_criteria else {"ids": ids})
            
            return {
                "status": "started",
                "operation_id": operation_id,
                "poll_url": f"/operations/async/{operation_id}/status",
                "message": "Bulk delete operation started"
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="Async tasks not configured")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting async bulk delete: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/traffic/async/generate-stats")
async def start_async_generate_stats(
    request: Request,
    data: Dict[str, Any] = Body(default={})
):
    """
    Start async generation of comprehensive traffic statistics
    Returns operation_id immediately, poll for status
    
    Body (optional):
    {
        "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
        "group_by": ["survey_id", "vendor", "status"]
    }
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        date_range = data.get('date_range', {})
        group_by = data.get('group_by', ['status'])
        
        try:
            from ..tasks.async_helpers import start_traffic_stats_generation
            operation_id = start_traffic_stats_generation(date_range, group_by)
            
            return {
                "status": "started",
                "operation_id": operation_id,
                "poll_url": f"/operations/async/{operation_id}/status",
                "message": "Statistics generation started"
            }
        except ImportError:
            raise HTTPException(status_code=503, detail="Async tasks not configured")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting async stats generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/traffic/async/reports/{report_id}")
async def get_traffic_report(
    request: Request,
    report_id: str
):
    """
    Retrieve a generated traffic report by ID
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")
        
        # Look up report in database
        db = traffic_service.traffic_collection.database
        report = db.traffic_reports.find_one({"_id": ObjectId(report_id)})
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Convert ObjectId to string
        report["_id"] = str(report["_id"])
        
        return report
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving traffic report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/traffic/export")
async def export_traffic_records(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status"),
    survey_id: Optional[str] = Query(None, description="Filter by survey ID"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(10000, ge=1, le=50000, description="Maximum records to export"),
):
    """
    Export all historic traffic records with URL information
    
    Returns for each record:
    - SFWID (traffic record ID)
    - Redirect URL (survey entry URL)  
    - Client URL (appended vendor redirect URL with respondent ID)
    - Out URL (raw vendor redirect URL)
    - Status, timestamps, and other metadata
    
    Requires authentication
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if url_parameters_collection is None:
            raise HTTPException(status_code=503, detail="Traffic collection not initialized")
        
        # Build query
        query = {}
        
        if status:
            query["status"] = status.upper()
        
        if survey_id:
            query["assignedSurveyId"] = survey_id
        
        if start_date or end_date:
            date_query = {}
            if start_date:
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    date_query["$gte"] = start_dt
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
            if end_date:
                try:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    date_query["$lte"] = end_dt
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
            if date_query:
                query["createdAt"] = date_query
        
        # Get total count
        total_count = url_parameters_collection.count_documents(query)
        
        # Fetch records
        records = list(
            url_parameters_collection.find(query)
            .sort("createdAt", -1)
            .limit(limit)
        )
        
        # Serialize for export
        export_records = []
        for record in records:
            # Format dates
            created_at = record.get("createdAt")
            updated_at = record.get("updatedAt")
            assigned_at = record.get("assignedAt")
            completed_at = record.get("completedAt")
            
            export_record = {
                "sfwid": str(record.get("_id", "")),
                "status": record.get("status", ""),
                "vendor_id": record.get("vendorId", ""),
                "country_code": record.get("countryCode", ""),
                "respondent_id": record.get("respondentId", ""),
                "survey_id": record.get("assignedSurveyId", ""),
                # URL Fields
                "redirect_url": record.get("redirectUrl", ""),  # Survey entry URL
                "out_url": record.get("outUrl", ""),  # Client redirect URL (with respondent appended)
                "cpx_callback_url": record.get("cpxCallbackUrl", ""),  # Callback URL from CPX
                # Timestamps
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "assigned_at": assigned_at.isoformat() if assigned_at else None,
                "completed_at": completed_at.isoformat() if completed_at else None,
                # Raw params
                "params": record.get("params", {}),
            }
            export_records.append(export_record)
        
        return {
            "total_available": total_count,
            "exported_count": len(export_records),
            "limit_applied": limit,
            "filters": {
                "status": status,
                "survey_id": survey_id,
                "start_date": start_date,
                "end_date": end_date,
            },
            "records": export_records
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error exporting traffic records: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Export error: {str(e)}")


@router.get("/api/traffic/export/csv")
async def export_traffic_csv(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status"),
    survey_id: Optional[str] = Query(None, description="Filter by survey ID"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(10000, ge=1, le=50000, description="Maximum records to export"),
):
    """
    Export all historic traffic records as CSV
    
    Columns:
    - SFWID, Status, Vendor ID, Country, Respondent ID, Survey ID
    - Redirect URL, Client URL (Out URL), CPX Callback URL
    - Created At, Assigned At, Completed At
    
    Requires authentication
    """
    from fastapi.responses import StreamingResponse
    import io
    import csv
    
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        if url_parameters_collection is None:
            raise HTTPException(status_code=503, detail="Traffic collection not initialized")
        
        # Build query
        query = {}
        
        if status:
            query["status"] = status.upper()
        
        if survey_id:
            query["assignedSurveyId"] = survey_id
        
        if start_date or end_date:
            date_query = {}
            if start_date:
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    date_query["$gte"] = start_dt
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
            if end_date:
                try:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    date_query["$lte"] = end_dt
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
            if date_query:
                query["createdAt"] = date_query
        
        # Fetch records
        records = list(
            url_parameters_collection.find(query)
            .sort("createdAt", -1)
            .limit(limit)
        )
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "SFWID",
            "Status",
            "Vendor ID",
            "Country Code",
            "Respondent ID",
            "Survey ID",
            "Redirect URL",
            "Client URL (Out URL)",
            "CPX Callback URL",
            "Created At",
            "Assigned At",
            "Completed At",
        ])
        
        # Write data rows
        for record in records:
            created_at = record.get("createdAt")
            assigned_at = record.get("assignedAt")
            completed_at = record.get("completedAt")
            
            writer.writerow([
                str(record.get("_id", "")),
                record.get("status", ""),
                record.get("vendorId", ""),
                record.get("countryCode", ""),
                record.get("respondentId", ""),
                record.get("assignedSurveyId", ""),
                record.get("redirectUrl", ""),
                record.get("outUrl", ""),
                record.get("cpxCallbackUrl", ""),
                created_at.isoformat() if created_at else "",
                assigned_at.isoformat() if assigned_at else "",
                completed_at.isoformat() if completed_at else "",
            ])
        
        # Create streaming response
        output.seek(0)
        
        filename = f"traffic_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error exporting traffic CSV: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"CSV export error: {str(e)}")


# ============================================
# CPX DIAGNOSTIC ENDPOINTS
# ============================================

@router.get("/api/debug/cpx-test")
async def test_cpx_multi_country(
    request: Request,
    countries: str = Query("IN,US,GB,CA", description="Comma-separated ISO2 country codes to test"),
    test_ip: Optional[str] = Query(None, description="Optional test IP (defaults to request IP)"),
):
    """
    CPX Multi-Country Diagnostic Endpoint
    
    Tests CPX API availability for multiple countries to diagnose screenout issues.
    This helps identify if the root cause is CPX survey inventory availability
    for specific regions (e.g., India).
    
    Returns count_available_surveys for each country tested.
    """
    import requests
    import hashlib
    import json
    
    try:
        # Get CPX credentials from environment or cpx_service
        app_id = os.getenv("CPX_APP_ID", "")
        secure_hash_key = os.getenv("CPX_SECURE_HASH_KEY", "")
        
        if not app_id or not secure_hash_key:
            # Try to get from cpx_service if injected
            if cpx_service:
                app_id = cpx_service.app_id
                secure_hash_key = cpx_service.secure_hash_key
        
        if not app_id or not secure_hash_key:
            raise HTTPException(status_code=503, detail="CPX credentials not configured")
        
        # Get test IP (use provided or extract from request)
        client_ip = test_ip or request.headers.get("CF-Connecting-IP") or \
                    request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or \
                    request.headers.get("X-Real-IP") or \
                    (request.client.host if request.client else "127.0.0.1")
        
        user_agent = request.headers.get("User-Agent", "Mozilla/5.0 Diagnostic Test")
        
        # Parse countries
        country_list = [c.strip().upper() for c in countries.split(",") if c.strip()]
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "test_ip": client_ip,
            "user_agent": user_agent[:80],
            "countries_tested": country_list,
            "results": {},
            "summary": {
                "total_tested": 0,
                "with_surveys": 0,
                "without_surveys": 0,
                "errors": 0
            }
        }
        
        CPX_API_URL = "https://live-api.cpx-research.com/api/get-surveys.php"
        
        for country in country_list:
            results["summary"]["total_tested"] += 1
            
            # Generate test ext_user_id
            test_ext_user_id = f"diagnostic_test_{country}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            secure_hash = hashlib.md5(f"{test_ext_user_id}-{secure_hash_key}".encode()).hexdigest()
            
            params = {
                "app_id": app_id,
                "ext_user_id": test_ext_user_id,
                "output_method": "api",
                "ip_user": client_ip,
                "user_agent": user_agent,
                "limit": 100,
                "secure_hash": secure_hash,
                "user_country_code": country,
            }
            
            try:
                response = requests.get(CPX_API_URL, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                
                count = data.get("count_available_surveys", 0)
                status = data.get("status", "unknown")
                message = data.get("message_not_found", "")
                surveys = data.get("surveys", []) or data.get("info", [])
                
                country_result = {
                    "count_available_surveys": count,
                    "status": status,
                    "message": message,
                    "survey_count_in_response": len(surveys) if surveys else 0,
                    "sample_survey": None,
                    "error": None
                }
                
                # Include sample survey info (without href for security)
                if surveys and len(surveys) > 0:
                    sample = surveys[0]
                    country_result["sample_survey"] = {
                        "id": sample.get("id"),
                        "title": sample.get("survey_title", sample.get("title", ""))[:50],
                        "loi": sample.get("loi"),
                        "payout_publisher_usd": sample.get("payout_publisher_usd"),
                        "conversion_rate": sample.get("conversion_rate")
                    }
                    results["summary"]["with_surveys"] += 1
                else:
                    results["summary"]["without_surveys"] += 1
                
                results["results"][country] = country_result
                
            except Exception as e:
                results["results"][country] = {
                    "count_available_surveys": 0,
                    "status": "error",
                    "message": str(e),
                    "survey_count_in_response": 0,
                    "sample_survey": None,
                    "error": str(e)
                }
                results["summary"]["errors"] += 1
        
        # Add diagnostic conclusion
        if results["summary"]["with_surveys"] == 0:
            results["diagnosis"] = "CRITICAL: No surveys found for ANY country. Check CPX credentials or account status."
        elif "IN" in results["results"] and results["results"]["IN"]["count_available_surveys"] == 0:
            other_countries_with_surveys = [c for c in country_list if c != "IN" and 
                                            results["results"].get(c, {}).get("count_available_surveys", 0) > 0]
            if other_countries_with_surveys:
                results["diagnosis"] = f"ROOT CAUSE IDENTIFIED: CPX has NO survey inventory for India (IN), but has surveys for {', '.join(other_countries_with_surveys)}. This explains the screenouts for Indian traffic."
            else:
                results["diagnosis"] = "No India surveys and no surveys for other tested countries."
        else:
            india_count = results["results"].get("IN", {}).get("count_available_surveys", 0)
            results["diagnosis"] = f"India has {india_count} surveys available. Screenouts may be due to filter settings or entry guard blocks."
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in CPX multi-country test: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"CPX diagnostic error: {str(e)}")


@router.get("/api/debug/entry-guard-stats")
async def get_entry_guard_stats(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Hours to look back (1-168)"),
):
    """
    Entry Guard Analytics Endpoint
    
    Shows statistics about CPX entry guards to diagnose if duplicate
    ext_user_id blocking is contributing to screenouts.
    """
    try:
        if cpx_entry_guards_collection is None:
            raise HTTPException(status_code=503, detail="Entry guards collection not initialized")
        
        # Time window for recent stats
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Get overall counts by status
        status_counts = {}
        for status in [CPX_GUARD_STATUS_CREATED, CPX_GUARD_STATUS_REDIRECTED, CPX_GUARD_STATUS_LOCKED]:
            status_counts[status] = cpx_entry_guards_collection.count_documents({"status": status})
        
        # Get recent entries
        recent_count = cpx_entry_guards_collection.count_documents({"created_at": {"$gte": since}})
        
        # Get entries with duplicate attempts
        with_duplicates = cpx_entry_guards_collection.count_documents({"duplicate_attempt_count": {"$gt": 0}})
        
        # Get top duplicates (most blocked)
        top_duplicates = list(
            cpx_entry_guards_collection.find(
                {"duplicate_attempt_count": {"$gt": 0}},
                {"ext_user_id": 1, "duplicate_attempt_count": 1, "status": 1, "created_at": 1, "client_ip": 1}
            ).sort("duplicate_attempt_count", -1).limit(10)
        )
        
        for doc in top_duplicates:
            doc["_id"] = str(doc["_id"])
            if doc.get("created_at"):
                doc["created_at"] = doc["created_at"].isoformat()
        
        # Get recent entries with IPs (for geo analysis)
        recent_entries = list(
            cpx_entry_guards_collection.find(
                {"created_at": {"$gte": since}},
                {"ext_user_id": 1, "status": 1, "client_ip": 1, "created_at": 1}
            ).sort("created_at", -1).limit(20)
        )
        
        for entry in recent_entries:
            entry["_id"] = str(entry["_id"])
            if entry.get("created_at"):
                entry["created_at"] = entry["created_at"].isoformat()
        
        # Total count
        total_guards = cpx_entry_guards_collection.count_documents({})
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "time_window_hours": hours,
            "total_guards": total_guards,
            "status_breakdown": status_counts,
            "recent_entries_count": recent_count,
            "entries_with_duplicate_attempts": with_duplicates,
            "duplicate_rate": round((with_duplicates / total_guards * 100), 2) if total_guards > 0 else 0,
            "top_blocked_ext_user_ids": top_duplicates,
            "recent_entries": recent_entries,
            "diagnosis": f"{'HIGH' if with_duplicates > total_guards * 0.2 else 'LOW'} duplicate rate ({with_duplicates}/{total_guards}). " + 
                        ("Entry guards may be blocking legitimate traffic." if with_duplicates > total_guards * 0.2 else "Entry guard blocking is not a significant factor.")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching entry guard stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Entry guard stats error: {str(e)}")


@router.get("/api/debug/cpx-diagnostic-logs")
async def get_cpx_diagnostic_logs(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Hours to look back (1-168)"),
    country: Optional[str] = Query(None, description="Filter by country code (e.g., IN, US)"),
    outcome: Optional[str] = Query(None, description="Filter by outcome (surveys_found, no_surveys_after_filter)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Records per page"),
):
    """
    Get CPX diagnostic logs showing filter outcomes and survey availability.
    
    This helps identify if screenouts are due to:
    - No CPX surveys for the region
    - Over-restrictive filter settings
    - Specific rejection reasons (LOI, CPI, IR)
    """
    from pymongo import MongoClient
    
    try:
        # Connect to cpx_diagnostic_logs
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        client = MongoClient(mongo_uri)
        cpx_db = client["cpx_research"]
        diagnostic_logs = cpx_db["cpx_diagnostic_logs"]
        
        # Time window
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Build query
        query = {"timestamp": {"$gte": since}}
        if country:
            query["country_code"] = country.upper()
        if outcome:
            query["outcome"] = outcome
        
        # Get total count
        total = diagnostic_logs.count_documents(query)
        
        # Calculate pagination
        skip = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        
        # Fetch logs (newest first)
        logs = list(
            diagnostic_logs.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        # Convert ObjectId to string
        for log in logs:
            log["_id"] = str(log["_id"])
            if log.get("timestamp"):
                log["timestamp"] = log["timestamp"].isoformat()
        
        # Aggregations for summary
        country_stats = list(diagnostic_logs.aggregate([
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": "$country_code",
                "total_requests": {"$sum": 1},
                "surveys_found": {"$sum": {"$cond": [{"$eq": ["$outcome", "surveys_found"]}, 1, 0]}},
                "no_surveys": {"$sum": {"$cond": [{"$eq": ["$outcome", "no_surveys_after_filter"]}, 1, 0]}},
                "avg_cpx_surveys": {"$avg": "$cpx_response.surveys_returned"},
                "avg_after_filter": {"$avg": "$filter_results.surveys_after_filter"}
            }},
            {"$sort": {"total_requests": -1}}
        ]))
        
        # Get filter rejection breakdown
        rejection_totals = list(diagnostic_logs.aggregate([
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": None,
                "total_loi_rejected": {"$sum": "$filter_results.rejection_stats.loi_too_high"},
                "total_cpi_rejected": {"$sum": "$filter_results.rejection_stats.cpi_too_low"},
                "total_ir_rejected": {"$sum": "$filter_results.rejection_stats.ir_too_low"},
                "total_no_href": {"$sum": "$filter_results.rejection_stats.no_href"},
            }}
        ]))
        
        rejection_summary = rejection_totals[0] if rejection_totals else {
            "total_loi_rejected": 0,
            "total_cpi_rejected": 0,
            "total_ir_rejected": 0,
            "total_no_href": 0
        }
        if "_id" in rejection_summary:
            del rejection_summary["_id"]
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "time_window_hours": hours,
            "filters_applied": {
                "country": country,
                "outcome": outcome
            },
            "country_summary": country_stats,
            "rejection_summary": rejection_summary,
            "logs": logs,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages
            },
            "diagnosis": _generate_diagnostic_summary(country_stats, rejection_summary) if country_stats else "No diagnostic data available"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching CPX diagnostic logs: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Diagnostic logs error: {str(e)}")


def _generate_diagnostic_summary(country_stats: list, rejection_summary: dict) -> str:
    """Generate a human-readable diagnostic summary"""
    summary_parts = []
    
    # Check India specifically
    india_stats = next((s for s in country_stats if s["_id"] == "IN"), None)
    if india_stats:
        success_rate = round((india_stats["surveys_found"] / india_stats["total_requests"] * 100), 1) if india_stats["total_requests"] > 0 else 0
        if success_rate < 10:
            summary_parts.append(f"CRITICAL: India survey success rate is only {success_rate}% ({india_stats['surveys_found']}/{india_stats['total_requests']})")
        elif success_rate < 50:
            summary_parts.append(f"WARNING: India survey success rate is low at {success_rate}%")
    
    # Check rejection reasons
    total_rejections = sum([
        rejection_summary.get("total_loi_rejected", 0),
        rejection_summary.get("total_cpi_rejected", 0),
        rejection_summary.get("total_ir_rejected", 0),
        rejection_summary.get("total_no_href", 0)
    ])
    
    if total_rejections > 0:
        cpi_pct = round((rejection_summary.get("total_cpi_rejected", 0) / total_rejections * 100), 1) if total_rejections > 0 else 0
        if cpi_pct > 50:
            summary_parts.append(f"CPI filter is rejecting {cpi_pct}% of surveys. Consider lowering min_cpi.")
        
        loi_pct = round((rejection_summary.get("total_loi_rejected", 0) / total_rejections * 100), 1) if total_rejections > 0 else 0
        if loi_pct > 50:
            summary_parts.append(f"LOI filter is rejecting {loi_pct}% of surveys. Consider increasing max_loi.")
    
    return " | ".join(summary_parts) if summary_parts else "No critical issues detected"

