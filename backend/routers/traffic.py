"""
Traffic Flow API Router
Handles survey tracking and URL parameter storage
Uses traffic_flow_db database
"""
from fastapi import APIRouter, HTTPException, Request, Query, Body
from fastapi.responses import RedirectResponse
from pymongo.collection import Collection
from bson import ObjectId
from datetime import datetime
from typing import Dict, Any, Optional, List
import os
import random
import base64

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
vendors_collection: Optional[Collection] = None
cpx_callback_logs_collection: Optional[Collection] = None


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


def set_vendors_collection(collection: Collection):
    """Set the vendors MongoDB collection from main.py"""
    global vendors_collection
    vendors_collection = collection


def set_cpx_callback_logs_collection(collection: Collection):
    """Set the CPX callback logs MongoDB collection from main.py"""
    global cpx_callback_logs_collection
    cpx_callback_logs_collection = collection


@router.get("/cint-response")
async def cint_callback(
    request: Request,
    status: str = Query(..., description="Response status: complete, terminate, quota_full, quality_terminate"),
    mid: str = Query(..., description="Cint session ID (MID)"),
    revenue: str = Query(None, description="Revenue/payout amount")
):
    """
    Cint Survey Callback Handler
    
    URL format: /cint-response?status={status}&mid={mid}&revenue={revenue}
    
    - status: complete, terminate, quota_full, quality_terminate
    - mid: The Cint session ID (MID placeholder replaced by Cint)
    - revenue: The payout amount (REVENUE placeholder replaced by Cint)
    """
    try:
        print(f"📥 Cint Callback received: status={status}, mid={mid}, revenue={revenue}")
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
        
        # Find traffic record by respondentId (which should be the mid)
        traffic_record = None
        if url_parameters_collection is not None:
            # Try ObjectId first
            try:
                traffic_record = url_parameters_collection.find_one({"_id": ObjectId(mid)})
            except:
                pass
            
            # Try as respondentId
            if not traffic_record:
                traffic_record = url_parameters_collection.find_one({"respondentId": mid})
            
            # Try as string _id
            if not traffic_record:
                traffic_record = url_parameters_collection.find_one({"_id": mid})
        
        if not traffic_record:
            print(f"⚠️ Traffic record not found for mid: {mid}")
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
    msg: str = Query(None, description="Response type: complete or out"),
    message_id: str = Query(None, description="Response type: complete or out (alias)"),
    rid: str = Query(None, description="CPX message_id (optional, for backwards compatibility)"),
    sfwid: str = Query(None, description="SFWID passed via subid_1 from CPX - PRIMARY identifier")
):
    """
    CPX Survey Callback Handler
    
    URL format: /cpx-response?msg={type}&rid={message_id}&sfwid={subid_1}
    
    - msg: "complete" or "out" (terminate)
    - rid: CPX message_id (optional, not used for lookup)
    - sfwid: The SFWID (traffic record _id) passed via subid_1 - PRIMARY identifier
    
    Logic:
    1. Use sfwid (from subid_1) to find the traffic record
    2. Get the vendorId from the traffic record
    3. Look up vendor's redirect URL (completeRD or terminateRD)
    4. Append the original respondentId from the traffic record to vendor's redirect URL
    5. Update traffic status and redirect to vendor
    """
    try:
        # Support both 'msg' and 'message_id' parameters for status
        status_code = msg or message_id or "out"
        
        print(f"📥 CPX Callback received: msg={status_code}, rid={rid}, sfwid={sfwid}")
        print(f"📥 Full callback URL: {request.url}")
        
        # sfwid from subid_1 is the PRIMARY identifier - it contains the SFWID (traffic record _id)
        if not sfwid:
            print(f"❌ Missing sfwid parameter - cannot identify traffic record")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        decoded_sfwid = sfwid
        print(f"✅ Using sfwid from subid_1: {sfwid}")
        
        # Determine status based on msg/message_id ("out" treated as terminate)
        if status_code.lower() == "complete":
            new_status = "COMPLETE"
            redirect_type = "completeRD"
        else:  # "out" = terminate
            new_status = "TERMINATED"
            redirect_type = "terminateRD"
        
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
                
                # Try as string _id
                if not traffic_record:
                    traffic_record = url_parameters_collection.find_one({"_id": search_val})
                    if traffic_record:
                        print(f"✅ Found traffic record by string _id: {search_val}")
                
                # Try by respondentId as fallback
                if not traffic_record:
                    traffic_record = url_parameters_collection.find_one({"respondentId": search_val})
                    if traffic_record:
                        print(f"✅ Found traffic record by respondentId: {search_val}")
        
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
        
        # Step 6: Log the callback for monitoring
        log_entry = {
            "timestamp": datetime.utcnow(),
            "callback_key": callback_key,  # P0.15: Idempotency key for deduplication
            "callback_url": str(request.url),
            "rid_received": rid,
            "decoded_sfwid": decoded_sfwid,
            "status_code": status_code,
            "new_status": new_status,
            "traffic_found": True,
            "traffic_id": traffic_id,
            "vendor_id": vendor_id,
            "respondent_id": original_respondent_id,
            "vendor_found": vendor is not None,
            "vendor_name": vendor.get("vendorName") if vendor else None,
            "redirect_type": redirect_type,
            "vendor_redirect_url": vendor_redirect_url,
            "success": vendor_redirect_url is not None
        }
        
        if cpx_callback_logs_collection is not None:
            try:
                cpx_callback_logs_collection.insert_one(log_entry)
                print(f"📝 Logged CPX callback")
            except Exception as log_error:
                print(f"⚠️ Failed to log callback: {log_error}")
        
        # Step 7: Redirect to vendor or error page
        if vendor_redirect_url:
            print(f"➡️ Redirecting to vendor: {vendor_redirect_url}")
            return RedirectResponse(url=vendor_redirect_url)
        else:
            # Redirect to error page if no vendor URL found
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
            "rid_received": rid,
            "status_code": msg or message_id or "unknown",
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


@router.post("/api/store")
async def store_url_params(request: Request, data: Dict[str, Any] = Body(...)):
    """
    Store URL parameters from survey tracking
    Creates a traffic record with vid, cc, rid if available
    Also attempts to allocate a survey to the respondent
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
        
        # If traffic service is available and we have the required params, use it
        if traffic_service and vendor_id and country_code and respondent_id:
            try:
                traffic_id = traffic_service.create_traffic_record(
                    vendor_id=vendor_id,
                    country_code=country_code,
                    respondent_id=respondent_id,
                    url=data.get('url'),
                    user_agent=data.get('userAgent'),
                    params=params
                )
            except Exception as e:
                print(f"⚠️ Failed to create traffic record, falling back to legacy: {e}")
        
        # Legacy fallback - store as before
        if not traffic_id:
            data['timestamp'] = datetime.utcnow().isoformat()
            data['status'] = 'incomplete'
            data['redirectUrl'] = None
            result = url_parameters_collection.insert_one(data)
            traffic_id = str(result.inserted_id)
        
        # Try to allocate a survey from both CPX and CINT pools
        # Filter by: is_active_in_pool=True AND country code match
        if vendor_id and country_code and respondent_id:
            try:
                from pymongo import MongoClient
                import os
                
                # Get MongoDB connection
                mongo_uri = os.getenv("MONGO_URI")
                if not mongo_uri:
                    print("❌ MONGO_URI not configured")
                else:
                    client = MongoClient(mongo_uri)
                    
                    # Get both CPX and CINT survey collections
                    cpx_collection = client["cpx_research"]["cpx_surveys"]
                    cint_collection = client["cint_research"]["cint_surveys"]
                    
                    # Normalize country code to uppercase
                    cc_upper = country_code.upper()
                    
                    # Query for active CPX surveys (NO country filter - CPX handles routing internally)
                    # CPX surveys have country="ALL" to indicate they accept all countries
                    # The CPX platform handles country-based targeting on their end
                    cpx_query = {
                        "is_active_in_pool": True
                    }
                    cpx_surveys = list(cpx_collection.find(cpx_query).limit(50))
                    print(f"📊 Found {len(cpx_surveys)} active CPX surveys (all countries - CPX handles routing)")
                    
                    # Query for active CINT surveys matching country
                    # CINT uses country_language field - need to map country code
                    # For now, get all active CINT surveys and filter by country_language mapping
                    cint_query = {
                        "is_active_in_pool": True
                    }
                    cint_surveys = list(cint_collection.find(cint_query).limit(50))
                    print(f"📊 Found {len(cint_surveys)} active CINT surveys (before country filter)")
                    
                    # Combine both pools
                    all_surveys = []
                    
                    # Add CPX surveys with source tag
                    for survey in cpx_surveys:
                        survey['_source'] = 'CPX'
                        all_surveys.append(survey)
                    
                    # TEMPORARILY DISABLED: CINT surveys not working correctly
                    # TODO: Re-enable once CINT integration is fixed
                    # for survey in cint_surveys:
                    #     survey['_source'] = 'CINT'
                    #     all_surveys.append(survey)
                    
                    print(f"📊 Total active surveys in pool: {len(all_surveys)} (CPX: {len(cpx_surveys)}, CINT: {len(cint_surveys)} - CINT DISABLED)")
                    
                    if all_surveys:
                        # Randomly select a survey from the combined pool
                        selected_survey = random.choice(all_surveys)
                        source = selected_survey.get('_source')
                        survey_id = selected_survey.get('survey_id') or selected_survey.get('_id')
                        
                        print(f"🎯 Selected {source} survey: {survey_id}")
                        
                        # Generate entry link based on source
                        if source == 'CPX':
                            # Generate CPX entry link with survey_id and SFWID as ext_user_id
                            # Using direct entry URL format per CPX documentation
                            if cpx_service:
                                # Get href from survey (prefer href for click-tracking with subid support)
                                # href format: https://click.cpx-research.com/?k=ENCRYPTED&subid_1=&subid_2=
                                # We populate subid_1 with SFWID for callback tracking
                                survey_href = selected_survey.get('href') or selected_survey.get('href_new') or selected_survey.get('live_link')
                                
                                entry_link = cpx_service.generate_entry_link(
                                    survey_id=str(survey_id),
                                    respondent_id=traffic_id,  # Use SFWID for callback tracking
                                    href=survey_href  # Use CPX's click-tracking URL
                                )
                                allocation_success = True
                                
                                # Update the traffic record
                                if traffic_service:
                                    traffic_service.assign_survey_to_traffic(
                                        traffic_id=traffic_id,
                                        survey_id=str(survey_id),
                                        redirect_url=entry_link
                                    )
                                
                                print(f"✅ Allocated CPX survey {survey_id} to SFWID={traffic_id}")
                                print(f"   Entry link: {entry_link[:100]}...")
                        
                        elif source == 'CINT':
                            # For CINT, try to get entry link from collection first
                            # If not found, use default Samplicio/Fulcrum URL format
                            entry_links_collection = client["cint_research"]["entry_links"]
                            entry_link_doc = entry_links_collection.find_one({"survey_id": str(survey_id)})
                            
                            if entry_link_doc and entry_link_doc.get('link'):
                                entry_link = entry_link_doc['link']
                            else:
                                # Use default Samplicio/Fulcrum format with respondent tracking
                                # Format: https://samplicio.us/s/default.aspx?SID={SurveyID}&PID={PanelistID}
                                entry_link = f"https://samplicio.us/s/default.aspx?SID={survey_id}&PID={traffic_id}"
                                print(f"ℹ️ Using default Samplicio URL for CINT survey {survey_id}")
                            
                            allocation_success = True
                            
                            # Update the traffic record
                            if traffic_service:
                                traffic_service.assign_survey_to_traffic(
                                    traffic_id=traffic_id,
                                    survey_id=str(survey_id),
                                    redirect_url=entry_link
                                )
                            
                            print(f"✅ Allocated CINT survey {survey_id} to SFWID={traffic_id}")
                    else:
                        print(f"⚠️ No active surveys available for country {cc_upper}")
                    
            except Exception as e:
                print(f"⚠️ Survey allocation error: {e}")
                import traceback
                traceback.print_exc()
        
        # Fallback to survey allocation service if CPX failed
        if not allocation_success and survey_allocation_service and vendor_id and country_code and respondent_id:
            try:
                from app.models.survey_allocation import AllocationRequest
                
                allocation_request = AllocationRequest(
                    vid=vendor_id,
                    cc=country_code.upper(),
                    rid=respondent_id,
                    ip_address=request.client.host if request else None,
                    user_agent=data.get('userAgent')
                )
                
                allocation_result = survey_allocation_service.allocate_respondent(allocation_request)
                
                if allocation_result.success and allocation_result.entry_link:
                    entry_link = allocation_result.entry_link
                    survey_id = allocation_result.survey_id
                    allocation_success = True
                    
                    if traffic_service:
                        traffic_service.assign_survey_to_traffic(
                            traffic_id=traffic_id,
                            survey_id=survey_id,
                            redirect_url=entry_link
                        )
                    
                    print(f"✅ Allocated survey {survey_id} via allocation service")
                else:
                    print(f"⚠️ Survey allocation service failed: {allocation_result.message}")
                    
            except Exception as e:
                print(f"⚠️ Survey allocation service error: {e}")
        
        return {
            "id": traffic_id,
            "type": "traffic_record" if traffic_service else "legacy",
            "allocation_success": allocation_success,
            "entry_link": entry_link,
            "survey_id": survey_id
        }
        
    except Exception as e:
        print(f"Error storing URL parameters: {e}")
        raise HTTPException(status_code=500, detail=f"Store error: {str(e)}")


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
        
        result = traffic_service.list_traffic_records(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            survey_id=survey_id,
        )
        
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

