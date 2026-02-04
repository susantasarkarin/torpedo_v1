"""
CPX API Integration Router

This router handles the CPX API integration flow:
1. /cpx-postback - Server-to-server postback handler (ALWAYS returns HTTP 200)
2. /response - CRM landing page (reads trans_id, shows status)
3. /survey-status - Polling endpoint for frontend

Key Design Decisions:
- trans_id is the PRIMARY identifier (message_id is NEVER used)
- Postback is the single source of truth for transaction status
- Idempotent handling of duplicate/fraud postbacks
- No dependency on CPX redirect or UI
- S2S postback forwards to vendor server with respondent_id
"""
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime
from typing import Optional
from bson import ObjectId
import os
import hashlib
import logging
import httpx

# Setup logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["cpx-api"])

# Configuration
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://surveyfieldwork.com")
CPX_SECRET_KEY = os.getenv("CPX_SECRET_KEY", "")  # For hash validation

# MongoDB collection references (injected from main.py)
survey_transactions_collection = None
cpx_postback_logs_collection = None
url_parameters_collection = None  # Traffic records collection
vendors_collection = None  # Vendors collection


def set_survey_transactions_collection(collection):
    """Set the survey_transactions MongoDB collection"""
    global survey_transactions_collection
    survey_transactions_collection = collection


def set_cpx_postback_logs_collection(collection):
    """Set the CPX postback logs MongoDB collection"""
    global cpx_postback_logs_collection
    cpx_postback_logs_collection = collection


def set_url_parameters_collection(collection):
    """Set the url_parameters (traffic records) MongoDB collection"""
    global url_parameters_collection
    url_parameters_collection = collection


def set_vendors_collection(collection):
    """Set the vendors MongoDB collection"""
    global vendors_collection
    vendors_collection = collection


def generate_postback_hash(trans_id: str, status: int, amount_usd: float = 0) -> str:
    """Generate a unique hash for deduplication"""
    data = f"{trans_id}:{status}:{amount_usd}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def validate_cpx_hash(trans_id: str, status: int, received_hash: str) -> bool:
    """
    Validate CPX security hash if configured.
    CPX uses: md5(trans_id + status + secret_key)
    """
    if not CPX_SECRET_KEY or not received_hash:
        return True  # Skip validation if not configured
    
    expected = hashlib.md5(f"{trans_id}{status}{CPX_SECRET_KEY}".encode()).hexdigest()
    return expected.lower() == received_hash.lower()


# ============================================
# POSTBACK HANDLER - Single Source of Truth
# ============================================

@router.get("/cpx-postback")
async def cpx_postback_handler(
    request: Request,
    trans_id: str = Query(..., description="Transaction ID from CPX"),
    status: int = Query(..., description="Status: 1=complete, 2=canceled/fraud"),
    amount_usd: Optional[float] = Query(None, description="Payout in USD"),
    amount_local: Optional[float] = Query(None, description="Payout in local currency"),
    subid_1: Optional[str] = Query(None, alias="subid", description="Primary sub ID (SFWID)"),
    subid_2: Optional[str] = Query(None, description="Secondary sub ID"),
    ip: Optional[str] = Query(None, description="User IP address"),
    offer_id: Optional[str] = Query(None, description="CPX offer/survey ID"),
    hash: Optional[str] = Query(None, description="Security hash for validation")
):
    """
    CPX Server-to-Server Postback Handler
    
    This endpoint ALWAYS returns HTTP 200 (required by CPX).
    
    URL format: /cpx-postback?trans_id={trans_id}&status={status}&amount_usd={amount}&subid={subid_1}
    
    Status codes:
    - 1 = COMPLETED (successful survey completion)
    - 2 = CANCELED / FRAUD (user left or flagged)
    
    Flow:
    1. Receive postback from CPX
    2. Validate hash (if configured)
    3. Check for duplicate postback (idempotency)
    4. Upsert transaction by trans_id
    5. Log postback for monitoring
    6. Return HTTP 200 (always)
    """
    try:
        logger.info(f"📥 CPX Postback: trans_id={trans_id}, status={status}, amount={amount_usd}")
        
        # Generate postback hash for deduplication
        postback_hash = generate_postback_hash(trans_id, status, amount_usd or 0)
        
        # Validate CPX security hash
        if not validate_cpx_hash(trans_id, status, hash):
            logger.warning(f"⚠️ Invalid hash for trans_id={trans_id}")
            # Still return 200 to not cause CPX retries, but log the issue
            _log_postback(trans_id, status, amount_usd, subid_1, False, "Invalid hash")
            return JSONResponse(content={"status": "ok"}, status_code=200)
        
        if survey_transactions_collection is None:
            logger.error("❌ survey_transactions_collection not initialized")
            return JSONResponse(content={"status": "ok"}, status_code=200)
        
        # Check for duplicate postback
        existing = survey_transactions_collection.find_one({"trans_id": trans_id})
        
        if existing:
            # Check if this is a duplicate (same hash)
            if existing.get("postback_hash") == postback_hash:
                logger.info(f"⚠️ Duplicate postback ignored for trans_id={trans_id}")
                _log_postback(trans_id, status, amount_usd, subid_1, True, "Duplicate ignored")
                return JSONResponse(content={"status": "ok"}, status_code=200)
            
            # Update existing transaction
            update_data = {
                "cpx_status": status,
                "status": "completed" if status == 1 else ("fraud" if status == 2 else "canceled"),
                "updated_at": datetime.utcnow(),
                "last_postback_at": datetime.utcnow(),
                "postback_hash": postback_hash,
                "$inc": {"postback_count": 1}
            }
            
            if amount_usd is not None:
                update_data["amount_usd"] = amount_usd
            if amount_local is not None:
                update_data["amount_local"] = amount_local
            if status == 1:
                update_data["completed_at"] = datetime.utcnow()
            if ip:
                update_data["ip_address"] = ip
            
            # Remove $inc from the $set operation
            inc_data = update_data.pop("$inc", {})
            
            survey_transactions_collection.update_one(
                {"trans_id": trans_id},
                {"$set": update_data, "$inc": inc_data}
            )
            
            logger.info(f"✅ Updated transaction: trans_id={trans_id}, status={status}")
        else:
            # Create new transaction
            new_transaction = {
                "trans_id": trans_id,
                "cpx_status": status,
                "status": "completed" if status == 1 else ("fraud" if status == 2 else "canceled"),
                "amount_usd": amount_usd,
                "amount_local": amount_local,
                "subid": subid_1,
                "subid_2": subid_2,
                "survey_id": offer_id,
                "ip_address": ip,
                "callback_url": str(request.url),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "last_postback_at": datetime.utcnow(),
                "postback_count": 1,
                "postback_hash": postback_hash,
                "completed_at": datetime.utcnow() if status == 1 else None
            }
            
            survey_transactions_collection.insert_one(new_transaction)
            logger.info(f"✅ Created transaction: trans_id={trans_id}, status={status}")
        
        # ============================================
        # VENDOR POSTBACK - Forward to vendor server
        # ============================================
        # After processing the CPX postback, we need to notify the vendor
        # 1. Look up traffic record by subid_1 (SFWID)
        # 2. Get vendor from traffic record
        # 3. Build vendor postback URL with respondent_id
        # 4. Make async HTTP GET call to vendor's server
        vendor_postback_result = await _forward_to_vendor(subid_1, status, amount_usd, trans_id)
        
        # Log successful postback
        _log_postback(trans_id, status, amount_usd, subid_1, True, "Processed", vendor_postback_result)
        
        # ALWAYS return 200
        return JSONResponse(content={"status": "ok"}, status_code=200)
        
    except Exception as e:
        logger.error(f"❌ Postback error: {e}")
        import traceback
        traceback.print_exc()
        
        # Log error but still return 200
        _log_postback(trans_id, status, amount_usd, subid_1, False, str(e), None)
        return JSONResponse(content={"status": "ok"}, status_code=200)


async def _forward_to_vendor(sfwid: str, status: int, amount_usd: float, trans_id: str) -> dict:
    """
    Forward the postback to the vendor's server.
    
    Flow:
    1. Look up traffic record by SFWID (subid_1)
    2. Get vendor from traffic record's vendorId
    3. Build vendor postback URL with respondent_id
    4. Make HTTP GET call to vendor's server
    
    Args:
        sfwid: The SFWID (traffic record _id) from subid_1
        status: CPX status (1=complete, 2=canceled/fraud)
        amount_usd: Payout amount in USD
        trans_id: CPX transaction ID
        
    Returns:
        dict with vendor_url, success, response_status, error
    """
    result = {
        "vendor_url": None,
        "success": False,
        "response_status": None,
        "error": None,
        "traffic_id": sfwid,
        "respondent_id": None,
        "vendor_id": None
    }
    
    if not sfwid:
        result["error"] = "No SFWID provided"
        logger.warning(f"⚠️ Vendor postback skipped: No SFWID provided")
        return result
    
    if url_parameters_collection is None or vendors_collection is None:
        result["error"] = "Collections not initialized"
        logger.warning(f"⚠️ Vendor postback skipped: Collections not initialized")
        return result
    
    try:
        # Step 1: Find traffic record by SFWID (_id)
        traffic_record = None
        
        # Try ObjectId first
        try:
            traffic_record = url_parameters_collection.find_one({"_id": ObjectId(sfwid)})
        except Exception:
            pass
        
        # Try as string _id
        if not traffic_record:
            traffic_record = url_parameters_collection.find_one({"_id": sfwid})
        
        if not traffic_record:
            result["error"] = f"Traffic record not found for SFWID: {sfwid}"
            logger.warning(f"⚠️ Vendor postback skipped: {result['error']}")
            return result
        
        vendor_id = traffic_record.get("vendorId")
        respondent_id = traffic_record.get("respondentId")
        result["respondent_id"] = respondent_id
        result["vendor_id"] = vendor_id
        
        if not vendor_id:
            result["error"] = "No vendorId in traffic record"
            logger.warning(f"⚠️ Vendor postback skipped: {result['error']}")
            return result
        
        # Step 2: Look up vendor
        vendor = vendors_collection.find_one({"vid": vendor_id})
        if not vendor and isinstance(vendor_id, str) and vendor_id.isdigit():
            vendor = vendors_collection.find_one({"vid": int(vendor_id)})
        if not vendor and isinstance(vendor_id, int):
            vendor = vendors_collection.find_one({"vid": str(vendor_id)})
        
        if not vendor:
            result["error"] = f"Vendor not found for vid: {vendor_id}"
            logger.warning(f"⚠️ Vendor postback skipped: {result['error']}")
            return result
        
        # Step 3: Determine redirect type based on status
        # status=1 -> complete, status=2 -> canceled/fraud (terminate)
        redirect_type = "completeRD" if status == 1 else "terminateRD"
        redirect_urls = vendor.get(redirect_type, [])
        vendor_variable = vendor.get("vendorVariable", "rid")
        
        if not redirect_urls or len(redirect_urls) == 0:
            result["error"] = f"No {redirect_type} URLs configured for vendor"
            logger.warning(f"⚠️ Vendor postback skipped: {result['error']}")
            return result
        
        # Step 4: Build vendor postback URL
        base_url = redirect_urls[0].strip()
        
        if not base_url:
            result["error"] = "Empty redirect URL"
            logger.warning(f"⚠️ Vendor postback skipped: {result['error']}")
            return result
        
        # Append respondent_id using vendor's variable name
        if base_url.endswith(f"&{vendor_variable}=") or base_url.endswith(f"?{vendor_variable}="):
            vendor_url = f"{base_url}{respondent_id}"
        elif f"&{vendor_variable}=" in base_url or f"?{vendor_variable}=" in base_url:
            vendor_url = base_url
        else:
            separator = "&" if "?" in base_url else "?"
            vendor_url = f"{base_url}{separator}{vendor_variable}={respondent_id}"
        
        result["vendor_url"] = vendor_url
        
        # Step 5: Make HTTP GET call to vendor
        logger.info(f"📤 Forwarding postback to vendor: {vendor_url}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(vendor_url)
            result["response_status"] = response.status_code
            result["success"] = 200 <= response.status_code < 300
            
            if result["success"]:
                logger.info(f"✅ Vendor postback successful: {response.status_code}")
            else:
                logger.warning(f"⚠️ Vendor postback returned: {response.status_code}")
        
        # Step 6: Update traffic record with postback info
        update_data = {
            "cpxPostbackReceived": True,
            "cpxPostbackStatus": status,
            "cpxPostbackAt": datetime.utcnow(),
            "cpxTransId": trans_id,
            "vendorPostbackUrl": vendor_url,
            "vendorPostbackSuccess": result["success"],
            "vendorPostbackStatus": result["response_status"]
        }
        
        if status == 1:
            update_data["status"] = "COMPLETE"
            update_data["completedAt"] = datetime.utcnow()
        elif status == 2:
            update_data["status"] = "FRAUD"
        
        url_parameters_collection.update_one(
            {"_id": traffic_record["_id"]},
            {"$set": update_data}
        )
        
        return result
        
    except httpx.TimeoutException:
        result["error"] = "Vendor postback timeout"
        logger.error(f"❌ Vendor postback timeout: {result['vendor_url']}")
        return result
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"❌ Vendor postback error: {e}")
        return result


def _log_postback(trans_id: str, status: int, amount: float, subid: str, success: bool, message: str, vendor_result: dict = None):
    """Log postback for monitoring"""
    if cpx_postback_logs_collection is None:
        return
    
    try:
        log_entry = {
            "trans_id": trans_id,
            "cpx_status": status,
            "amount_usd": amount,
            "subid": subid,
            "success": success,
            "message": message,
            "timestamp": datetime.utcnow()
        }
        
        # Add vendor postback details if available
        if vendor_result:
            log_entry["vendor_postback"] = {
                "url": vendor_result.get("vendor_url"),
                "success": vendor_result.get("success"),
                "response_status": vendor_result.get("response_status"),
                "error": vendor_result.get("error"),
                "respondent_id": vendor_result.get("respondent_id"),
                "vendor_id": vendor_result.get("vendor_id")
            }
        
        cpx_postback_logs_collection.insert_one(log_entry)
    except Exception as e:
        logger.error(f"Failed to log postback: {e}")


# ============================================
# CRM RESPONSE PAGE - User Landing Page
# ============================================

@router.get("/response")
async def response_page(
    request: Request,
    trans_id: str = Query(..., description="Transaction ID"),
    status: Optional[str] = Query(None, description="Status hint from redirect"),
    subid: Optional[str] = Query(None, description="Sub ID for tracking")
):
    """
    CRM Response Landing Page
    
    URL format: /response?trans_id={trans_id}&status={status}&subid={subid}
    
    This page:
    1. Reads trans_id from URL
    2. Fetches transaction status from DB
    3. Renders appropriate page (success/failure/pending)
    
    NOTE: The 'status' parameter is just a hint from the redirect.
    The actual status is always fetched from the database (postback is source of truth).
    """
    try:
        if survey_transactions_collection is None:
            return _render_error_page("System temporarily unavailable")
        
        # Fetch transaction from database
        transaction = survey_transactions_collection.find_one({"trans_id": trans_id})
        
        if not transaction:
            # Transaction not found - might be pending postback
            logger.warning(f"Transaction not found: trans_id={trans_id}")
            return _render_pending_page(trans_id, "Transaction pending")
        
        db_status = transaction.get("status", "pending")
        amount = transaction.get("amount_usd")
        
        if db_status == "completed":
            return _render_success_page(trans_id, amount)
        elif db_status in ["fraud", "canceled"]:
            return _render_failure_page(trans_id, "Survey not completed")
        else:
            return _render_pending_page(trans_id, "Waiting for confirmation")
            
    except Exception as e:
        logger.error(f"Response page error: {e}")
        return _render_error_page("An error occurred")


def _render_success_page(trans_id: str, amount: Optional[float] = None) -> HTMLResponse:
    """Render success page HTML"""
    amount_text = f"${amount:.2f}" if amount else ""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Survey Complete - SurveyFieldwork</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
            .card {{ background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }}
            .logo {{ max-width: 200px; margin-bottom: 20px; }}
            h1 {{ color: #28a745; margin-bottom: 15px; }}
            p {{ color: #666; line-height: 1.6; }}
            .amount {{ font-size: 24px; color: #28a745; font-weight: bold; margin: 20px 0; }}
            .trans-id {{ font-size: 12px; color: #999; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <img src="/SF.png" alt="SurveyFieldwork" class="logo">
            <h1>✓ Survey Completed!</h1>
            <p>Thank you for completing the survey.</p>
            {f'<div class="amount">Earned: {amount_text}</div>' if amount_text else ''}
            <p>Your response has been recorded and you will be credited accordingly.</p>
            <div class="trans-id">Transaction: {trans_id}</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


def _render_failure_page(trans_id: str, reason: str) -> HTMLResponse:
    """Render failure page HTML"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Survey Incomplete - SurveyFieldwork</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
            .card {{ background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }}
            .logo {{ max-width: 200px; margin-bottom: 20px; }}
            h1 {{ color: #dc3545; margin-bottom: 15px; }}
            p {{ color: #666; line-height: 1.6; }}
            .trans-id {{ font-size: 12px; color: #999; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <img src="/SF.png" alt="SurveyFieldwork" class="logo">
            <h1>Survey Not Completed</h1>
            <p>{reason}</p>
            <p>If you believe this is an error, please contact support.</p>
            <div class="trans-id">Transaction: {trans_id}</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


def _render_pending_page(trans_id: str, message: str) -> HTMLResponse:
    """Render pending page HTML with auto-refresh"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Processing - SurveyFieldwork</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
            .card {{ background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }}
            .logo {{ max-width: 200px; margin-bottom: 20px; }}
            h1 {{ color: #ffc107; margin-bottom: 15px; }}
            p {{ color: #666; line-height: 1.6; }}
            .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            .trans-id {{ font-size: 12px; color: #999; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <img src="/SF.png" alt="SurveyFieldwork" class="logo">
            <h1>⏳ Processing...</h1>
            <div class="spinner"></div>
            <p>{message}</p>
            <p>This page will automatically refresh.</p>
            <div class="trans-id">Transaction: {trans_id}</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


def _render_error_page(message: str) -> HTMLResponse:
    """Render error page HTML"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Error - SurveyFieldwork</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
            .card {{ background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; max-width: 500px; }}
            .logo {{ max-width: 200px; margin-bottom: 20px; }}
            h1 {{ color: #dc3545; margin-bottom: 15px; }}
            p {{ color: #666; line-height: 1.6; }}
        </style>
    </head>
    <body>
        <div class="card">
            <img src="/SF.png" alt="SurveyFieldwork" class="logo">
            <h1>Something Went Wrong</h1>
            <p>{message}</p>
            <p>Please try again later or contact support.</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


# ============================================
# SURVEY STATUS POLLING ENDPOINT
# ============================================

@router.get("/survey-status")
async def survey_status_poll(
    trans_id: str = Query(..., description="Transaction ID to check")
):
    """
    Survey Status Polling Endpoint
    
    Frontend polls this endpoint to check if postback has arrived.
    Returns status and redirect URL when completed.
    
    Response:
    {
        "trans_id": "xxx",
        "status": "pending|completed|canceled|fraud",
        "completed": true/false,
        "redirect_url": "/response?trans_id=xxx&status=success" (when completed),
        "poll_again": true/false,
        "poll_interval_ms": 2000
    }
    """
    try:
        if survey_transactions_collection is None:
            return {
                "trans_id": trans_id,
                "status": "error",
                "completed": False,
                "redirect_url": None,
                "poll_again": True,
                "poll_interval_ms": 3000,
                "message": "Service initializing"
            }
        
        transaction = survey_transactions_collection.find_one({"trans_id": trans_id})
        
        if not transaction:
            # Not found yet - tell frontend to keep polling
            return {
                "trans_id": trans_id,
                "status": "pending",
                "completed": False,
                "redirect_url": None,
                "poll_again": True,
                "poll_interval_ms": 2000,
                "message": "Waiting for survey response"
            }
        
        status = transaction.get("status", "pending")
        completed = status == "completed"
        
        # Build redirect URL for completed transactions
        redirect_url = None
        if completed:
            redirect_url = f"/response?trans_id={trans_id}&status=success"
        elif status in ["canceled", "fraud"]:
            redirect_url = f"/response?trans_id={trans_id}&status=failed"
        
        return {
            "trans_id": trans_id,
            "status": status,
            "completed": completed,
            "redirect_url": redirect_url,
            "poll_again": status == "pending",
            "poll_interval_ms": 2000,
            "message": "Survey completed" if completed else f"Status: {status}"
        }
        
    except Exception as e:
        logger.error(f"Survey status poll error: {e}")
        return {
            "trans_id": trans_id,
            "status": "error",
            "completed": False,
            "redirect_url": None,
            "poll_again": True,
            "poll_interval_ms": 5000,
            "message": str(e)
        }


# ============================================
# TRANSACTION MANAGEMENT ENDPOINTS
# ============================================

@router.post("/transaction/create")
async def create_transaction(
    request: Request,
    trans_id: Optional[str] = Query(None, description="Transaction ID (query param)"),
    user_id: Optional[str] = Query(None, description="User/Respondent ID"),
    subid: Optional[str] = Query(None, description="Sub ID"),
    survey_id: Optional[str] = Query(None, description="Survey ID"),
    vendor_id: Optional[str] = Query(None, description="Vendor ID"),
    country_code: Optional[str] = Query(None, description="Country code")
):
    """
    Create a new pending transaction before redirecting user to CPX.
    
    Call this endpoint when generating the CPX survey link to pre-register
    the transaction. The postback will then update this record.
    
    Accepts parameters via query string OR JSON body for flexibility.
    """
    try:
        if survey_transactions_collection is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Support both query params and JSON body
        body_data = {}
        try:
            body_data = await request.json()
        except:
            pass  # No JSON body, use query params
        
        # Prefer body data, fall back to query params
        final_trans_id = body_data.get("trans_id") or trans_id
        final_user_id = body_data.get("user_id") or user_id
        final_subid = body_data.get("subid") or subid
        final_survey_id = body_data.get("survey_id") or survey_id
        final_vendor_id = body_data.get("vendor_id") or vendor_id
        final_country_code = body_data.get("country_code") or country_code
        
        if not final_trans_id:
            raise HTTPException(status_code=400, detail="trans_id is required")
        
        # Check if already exists
        existing = survey_transactions_collection.find_one({"trans_id": final_trans_id})
        if existing:
            return {"success": True, "trans_id": final_trans_id, "message": "Transaction already exists"}
        
        new_transaction = {
            "trans_id": final_trans_id,
            "user_id": final_user_id,
            "subid": final_subid,
            "survey_id": final_survey_id,
            "vendor_id": final_vendor_id,
            "country_code": final_country_code,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "postback_count": 0
        }
        
        survey_transactions_collection.insert_one(new_transaction)
        
        return {
            "success": True,
            "trans_id": final_trans_id,
            "message": "Transaction created"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create transaction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transaction/{trans_id}")
async def get_transaction(trans_id: str):
    """Get transaction details by trans_id"""
    try:
        if survey_transactions_collection is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        transaction = survey_transactions_collection.find_one({"trans_id": trans_id})
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        # Convert ObjectId to string
        transaction["_id"] = str(transaction["_id"])
        
        return transaction
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get transaction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/cpx-postback-logs")
async def get_postback_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    trans_id: Optional[str] = Query(None, description="Filter by trans_id")
):
    """Get CPX postback logs for monitoring"""
    try:
        if cpx_postback_logs_collection is None:
            return {"logs": [], "total": 0}
        
        query = {}
        if trans_id:
            query["trans_id"] = trans_id
        
        total = cpx_postback_logs_collection.count_documents(query)
        skip = (page - 1) * page_size
        
        logs = list(
            cpx_postback_logs_collection
            .find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        for log in logs:
            log["_id"] = str(log["_id"])
            if log.get("timestamp"):
                log["timestamp"] = log["timestamp"].isoformat()
        
        return {
            "logs": logs,
            "total": total,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        logger.error(f"Get postback logs error: {e}")
        return {"logs": [], "total": 0, "error": str(e)}
