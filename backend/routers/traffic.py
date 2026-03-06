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
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
import os
import random
import base64
import time
import hashlib
import hmac
import asyncio
import uuid
import httpx
import re
from database import (
    get_async_url_parameters_collection,
    get_async_vendors_collection,
    get_async_cpx_callback_logs_collection,
    get_async_collection,
    DB_EMAIL_AUTOMATION,
    COL_PROJECTS,
    DB_FINANCE,
    COL_CUSTOMERS,
)

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
projects_collection: Optional[Collection] = None
finance_customers_collection: Optional[Collection] = None


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
    if cpx_service and hasattr(cpx_service, '_async_client'):
        cpx_service._async_client = _get_cpx_async_client()


def set_cint_service(service: Any):
    """Set the CINT service instance for survey allocation"""
    global cint_service
    cint_service = service


def set_vendors_collection(collection: Collection):
    """Set the vendors MongoDB collection from main.py"""
    global vendors_collection
    vendors_collection = collection


def set_projects_collection(collection: Collection):
    """Set the projects MongoDB collection from main.py"""
    global projects_collection
    projects_collection = collection


def set_finance_customers_collection(collection: Collection):
    """Set finance customers collection from main.py."""
    global finance_customers_collection
    finance_customers_collection = collection


def set_cpx_callback_logs_collection(collection: Collection):
    """Set the CPX callback logs MongoDB collection from main.py"""
    global cpx_callback_logs_collection
    cpx_callback_logs_collection = collection


def set_cpx_postback_logs_collection(collection: Collection):
    """Set the CPX S2S postback logs collection for verification"""
    global cpx_postback_logs_collection
    cpx_postback_logs_collection = collection


def _normalize_project_status(value: Any) -> str:
    """Normalize stored project status values."""
    return str(value or "").strip().lower()


def _normalize_client_variable(raw_value: Any) -> str:
    """
    Extract and normalize a client variable key name.

    Accepts strict key values like `rid`, and compact key:value forms like `rid: respondent id`.
    """
    raw = str(raw_value or "").strip()
    if not raw:
        return ""

    # Direct variable key.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", raw):
        return raw

    # Key with annotation.
    for sep in ("=", ":"):
        if sep in raw:
            key = raw.split(sep, 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
                return key

    return ""


def _extract_client_variable_from_customer(customer_doc: Optional[Dict[str, Any]]) -> str:
    """Resolve client variable from customer record fields."""
    if not customer_doc:
        return ""

    for field in ("clientVariable", "client_variable", "notes"):
        normalized = _normalize_client_variable(customer_doc.get(field))
        if normalized:
            return normalized
    return ""


async def _resolve_live_project_async(project_number: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a live project from the study pool by project number (surveyNo).

    Accepts exact surveyNo; if numeric, also tries zero-padded variants.
    """
    normalized_number = str(project_number or "").strip()
    if not normalized_number:
        return None

    candidates = {normalized_number}
    if normalized_number.isdigit():
        candidates.add(str(int(normalized_number)))
        candidates.add(normalized_number.zfill(5))

    async_projects_col = get_async_collection(DB_EMAIL_AUTOMATION, COL_PROJECTS)
    project_doc = await async_projects_col.find_one(
        {
            "is_deleted": {"$ne": True},
            "surveyNo": {"$in": list(candidates)},
        }
    )
    if not project_doc:
        return None

    if _normalize_project_status(project_doc.get("projectStatus")) != "live":
        return None

    return project_doc


async def _resolve_project_client_variable_async(project_doc: Optional[Dict[str, Any]]) -> str:
    """Resolve client variable for a project by matching finance customer record."""
    if not project_doc:
        return ""

    client_name = str(project_doc.get("client") or "").strip()
    if not client_name:
        return ""

    escaped_client = re.escape(client_name)
    async_customers_col = get_async_collection(DB_FINANCE, COL_CUSTOMERS)
    customer_doc = await async_customers_col.find_one(
        {
            "$or": [
                {"company_name": {"$regex": f"^{escaped_client}$", "$options": "i"}},
                {"name": {"$regex": f"^{escaped_client}$", "$options": "i"}},
            ]
        }
    )
    return _extract_client_variable_from_customer(customer_doc)


def _replace_live_link_respondent(live_link: str, sfwid: str, client_variable: str = "") -> str:
    """
    Replace the respondent placeholder in project live link with SFWID.

    Priority:
    1) Replace value of the configured client variable query param.
    2) Replace known placeholder tokens in URL text.
    3) If no client variable and common RID/PID param exists, replace that value.
    """
    link = str(live_link or "").strip()
    if not link or not sfwid:
        return link

    parsed = urlparse(link)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    normalized_var = _normalize_client_variable(client_variable)

    if normalized_var:
        updated_pairs = []
        for key, value in query_pairs:
            if key.lower() == normalized_var.lower():
                updated_pairs.append((key, sfwid))
                replaced = True
            else:
                updated_pairs.append((key, value))

        if not replaced:
            updated_pairs.append((normalized_var, sfwid))
            replaced = True

        query_pairs = updated_pairs
    else:
        fallback_keys = {"rid", "respondent_id", "respondentid", "pid"}
        updated_pairs = []
        for key, value in query_pairs:
            if key.lower() in fallback_keys and not replaced:
                updated_pairs.append((key, sfwid))
                replaced = True
            else:
                updated_pairs.append((key, value))
        query_pairs = updated_pairs

    rebuilt = urlunparse(parsed._replace(query=urlencode(query_pairs, doseq=True)))

    placeholder_tokens = (
        "{RID}",
        "{rid}",
        "{{RID}}",
        "{{rid}}",
        "[RID]",
        "[rid]",
        "{PID}",
        "{pid}",
        "[%PID%]",
        "{RESPONDENT_ID}",
        "{respondent_id}",
        "{respondentId}",
        "{SFWID}",
        "{sfwid}",
    )

    for token in placeholder_tokens:
        if token in rebuilt:
            rebuilt = rebuilt.replace(token, sfwid)
            replaced = True

    return rebuilt if replaced else link


async def _resolve_vendor_async(vendor_id: Any) -> Optional[Dict[str, Any]]:
    """Resolve vendor by ID with int/string fallback."""
    if vendor_id is None:
        return None

    async_vendors_col = get_async_vendors_collection()
    vendor = await async_vendors_col.find_one({"vid": vendor_id})
    if vendor:
        return vendor

    if isinstance(vendor_id, str) and vendor_id.isdigit():
        return await async_vendors_col.find_one({"vid": int(vendor_id)})
    if isinstance(vendor_id, int):
        return await async_vendors_col.find_one({"vid": str(vendor_id)})
    return None


def _build_vendor_redirect_url(
    vendor_doc: Optional[Dict[str, Any]],
    redirect_fields: List[str],
    fallback_url: str,
    respondent_id: str,
) -> str:
    """Build vendor redirect URL and append respondent ID using vendor variable."""
    base_url = ""
    vendor_variable = "id"

    if vendor_doc:
        vendor_variable = str(vendor_doc.get("vendorVariable") or "id").strip() or "id"
        for field in redirect_fields:
            urls = vendor_doc.get(field, [])
            if isinstance(urls, list):
                candidate = next((u.strip() for u in urls if u and str(u).strip()), "")
            elif isinstance(urls, str):
                candidate = urls.strip()
            else:
                candidate = ""
            if candidate:
                base_url = candidate
                break

    if not base_url:
        base_url = fallback_url

    if not respondent_id:
        return base_url

    if base_url.endswith(f"&{vendor_variable}=") or base_url.endswith(f"?{vendor_variable}="):
        return f"{base_url}{respondent_id}"
    if f"&{vendor_variable}=" in base_url or f"?{vendor_variable}=" in base_url:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{vendor_variable}={respondent_id}"
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{vendor_variable}={respondent_id}"


# ============================================
# CINT FALLBACK HELPERS (module-level)
# ============================================
# Map 2-letter country code to CINT CountryLanguageID
CINT_COUNTRY_LANGUAGE_MAP = {
    "us": 9, "gb": 8, "uk": 8, "in": 7, "au": 5, "ca": 6,
    "de": 4, "fr": 5, "es": 6, "mx": 115, "br": 108, "it": 11,
    "nl": 10, "za": 49, "sg": 50, "nz": 57, "ph": 58, "ie": 43,
}

CINT_API_BASE = "https://api.samplicio.us"
CINT_CALLBACK_BASE = "https://torpedo.cogentixresearch.com"

# ============== SHARED HTTP CLIENT (Connection Pooling) ==============
# Reuse connections across requests instead of creating new client per call
_cint_http_client: Optional[httpx.Client] = None

_cint_async_client: Optional[httpx.AsyncClient] = None
_cpx_async_client: Optional[httpx.AsyncClient] = None

def _get_cint_async_client() -> httpx.AsyncClient:
    """Get or create a shared httpx.AsyncClient for CINT with connection pooling."""
    global _cint_async_client
    if _cint_async_client is None or _cint_async_client.is_closed:
        _cint_async_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(
                max_connections=1000,       # High connection limit for 10k users
                max_keepalive_connections=200,
                keepalive_expiry=60
            ),
            follow_redirects=False
        )
    return _cint_async_client


def _get_cpx_async_client() -> httpx.AsyncClient:
    """Get or create a shared httpx.AsyncClient for CPX with connection pooling."""
    global _cpx_async_client
    if _cpx_async_client is None or _cpx_async_client.is_closed:
        _cpx_async_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(
                max_connections=1000,
                max_keepalive_connections=200,
                keepalive_expiry=60
            ),
            follow_redirects=False
        )
    return _cpx_async_client


def _get_cint_client() -> httpx.Client:
    """Get or create a shared httpx.Client with connection pooling."""
    global _cint_http_client
    if _cint_http_client is None or _cint_http_client.is_closed:
        _cint_http_client = httpx.Client(
            timeout=5.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30
            ),
            follow_redirects=False
        )
    return _cint_http_client


def _apply_cint_quality_filter(surveys: list, respondent_age: Optional[int] = None) -> list:
    """
    Filter an offerwall survey list by IR/conversion quality floors and optional age qualification.

    Uses env vars MIN_CINT_IR (default 20, percent) and MIN_CINT_CONVERSION (default 0.15).
    Age pre-screening works against survey_qualifications[question_id==42].precodes — this data
    is only available once a Feed Opportunities webhook subscription is active; if absent the
    age filter is skipped (no penalty for surveys without qualification data).

    Falls back gracefully: strict(quality+age) → age-only → quality-only → unfiltered.
    """
    min_ir = int(os.getenv("MIN_CINT_IR", "20"))
    min_conv = float(os.getenv("MIN_CINT_CONVERSION", "0.15"))

    def _passes_quality(s: dict) -> bool:
        ir = float(s.get("IR") or s.get("BidIncidence") or 0)
        conv = float(s.get("Conversion") or 1.0)  # default 1.0 when absent — no conversion penalty
        return ir >= min_ir and conv >= min_conv

    def _passes_age(s: dict) -> bool:
        """Filter by survey_qualifications age precode (question_id 42). Skip if no qual data."""
        if respondent_age is None:
            return True
        for q in (s.get("survey_qualifications") or []):
            qid = q.get("question_id") or q.get("QuestionID")
            if qid == 42:
                precodes = q.get("precodes") or q.get("PreCodes") or []
                if precodes and str(respondent_age) not in [str(p) for p in precodes]:
                    return False
        return True

    # Pass 1 — strict: quality + age
    strict = [s for s in surveys if _passes_quality(s) and _passes_age(s)]
    if strict:
        return strict

    # Pass 2 — relax quality floor, keep age constraint
    if respondent_age is not None:
        age_only = [s for s in surveys if _passes_age(s)]
        if age_only:
            print(f"   ⚠️ CINT quality filter: relaxed IR/conv floors — {len(age_only)} candidates (age constraint kept)")
            return age_only

    # Pass 3 — keep quality floor, drop age constraint
    quality_only = [s for s in surveys if _passes_quality(s)]
    if quality_only:
        print(f"   ⚠️ CINT quality filter: no age-qualified surveys, quality-only — {len(quality_only)} candidates")
        return quality_only

    # Pass 4 — unfiltered fallback
    print(f"   ⚠️ CINT quality filter: all {len(surveys)} candidates below floors — using unfiltered pool")
    return surveys


def _score_cint_survey(survey: dict, respondent_age: Optional[int] = None) -> float:
    """Score a CINT survey for smart ordering (higher = better completion chance)."""
    conv = float(survey.get("Conversion") or 0)
    ir = float(survey.get("IR") or survey.get("BidIncidence") or 0)
    rpc = float(survey.get("RevenuePerClick") or survey.get("RPC") or 0)
    remaining = int(survey.get("TotalRemaining") or 0)
    loi = float(survey.get("LengthOfInterview") or survey.get("LOI") or survey.get("BidLengthOfInterview") or 10)

    w_conv = float(os.getenv("CINT_SCORE_W_CONV", "40"))
    w_ir = float(os.getenv("CINT_SCORE_W_IR", "25"))
    w_rpc = float(os.getenv("CINT_SCORE_W_RPC", "15"))
    w_remaining = float(os.getenv("CINT_SCORE_W_REMAINING", "10"))
    w_loi = float(os.getenv("CINT_SCORE_W_LOI", "10"))

    conv_score = min(conv, 1.0)
    ir_score = min(ir / 100.0, 1.0)
    rpc_score = min(rpc / 2.0, 1.0)
    remaining_score = min(remaining / 500.0, 1.0)
    loi_penalty = min(loi / 30.0, 1.0)

    score = (
        w_conv * conv_score
        + w_ir * ir_score
        + w_rpc * rpc_score
        + w_remaining * remaining_score
        - w_loi * loi_penalty
    )

    if respondent_age is not None:
        for q in (survey.get("survey_qualifications") or []):
            qid = q.get("question_id") or q.get("QuestionID")
            if qid == 42:
                precodes = q.get("precodes") or q.get("PreCodes") or []
                if precodes and str(respondent_age) in [str(p) for p in precodes]:
                    score += 5.0
                break

    return score


async def fetch_cint_offerwall_candidates(country_code: str, limit: int = 50, respondent_age: Optional[int] = None) -> list:
    """
    Fetch live survey candidates for a country (Asynchronous).
    
    Uses the in-memory offerwall cache. Returns list of survey number strings.
    Applies IR/conversion quality floors and optional age pre-screening via
    _apply_cint_quality_filter before returning candidates.
    """
    import httpx
    
    cc = (country_code or "").lower()
    country_lang_id = CINT_COUNTRY_LANGUAGE_MAP.get(cc)
    
    # --- Try cache first (zero latency) ---
    try:
        try:
            from tasks.cint_survey_cleanup import get_cached_surveys_for_country, get_cached_offerwall
        except ImportError:
            from .tasks.cint_survey_cleanup import get_cached_surveys_for_country, get_cached_offerwall
        
        cache_info = get_cached_offerwall()
        
        if cache_info.get("last_updated") and country_lang_id:
            cached = get_cached_surveys_for_country(country_lang_id)
            if cached:
                cached = _apply_cint_quality_filter(cached, respondent_age)
                cached.sort(key=lambda s: _score_cint_survey(s, respondent_age), reverse=True)
                candidates = [str(s.get("SurveyNumber")) for s in cached[:limit] if s.get("SurveyNumber")]
                print(f"   📡 CINT offerwall (CACHED): {len(candidates)} candidates for country={cc} (cache age: {(datetime.utcnow() - cache_info['last_updated']).seconds}s)")
                return candidates
            else:
                print(f"   ⚠️ CINT cache: No surveys for CountryLanguageID={country_lang_id}, falling back to API")
        elif cache_info.get("last_updated") and not country_lang_id:
            # No country mapping — use all cached surveys
            all_surveys = cache_info.get("surveys", [])
            if all_surveys:
                all_surveys = _apply_cint_quality_filter(all_surveys, respondent_age)
                all_surveys.sort(key=lambda s: _score_cint_survey(s, respondent_age), reverse=True)
                candidates = [str(s.get("SurveyNumber")) for s in all_surveys[:limit] if s.get("SurveyNumber")]
                print(f"   📡 CINT offerwall (CACHED, all countries): {len(candidates)} candidates")
                return candidates
        else:
            print(f"   ⚠️ CINT cache empty/stale, falling back to direct API call")
    except Exception as cache_err:
        print(f"   ⚠️ Cache read error: {cache_err}, falling back to API")
    
    # --- Fallback: Direct API call ---
    api_key = os.getenv("CINT_API_KEY")
    supplier_code = os.getenv("CINT_SUPPLIER_CODE", "6777")
    
    if not api_key or not supplier_code:
        print("   ❌ CINT offerwall: Missing API_KEY or SUPPLIER_CODE")
        return []
    
    if not country_lang_id:
        print(f"   ⚠️ CINT offerwall: No CountryLanguageID mapping for '{cc}'")
    
    try:
        headers = {
            "Authorization": api_key,
            "Accept": "application/json",
        }
        url = f"{CINT_API_BASE}/Supply/v1/Surveys/AllOfferwall/{supplier_code}"
        
        client = _get_cint_async_client()
        resp = await client.get(url, headers=headers, timeout=10.0)
        
        if resp.status_code != 200:
            print(f"   ❌ CINT offerwall API: status={resp.status_code}")
            return []
        
        surveys = resp.json().get("Surveys", [])
        print(f"   📡 CINT offerwall (API): {len(surveys)} total surveys")
        
        # Filter by country
        if country_lang_id:
            filtered = [s for s in surveys if s.get("CountryLanguageID") == country_lang_id]
            print(f"   📡 CINT offerwall: {len(filtered)} surveys for CountryLanguageID={country_lang_id} (country={cc})")
        else:
            filtered = surveys
        
        if not filtered and country_lang_id:
            print(f"   WARNING: CINT offerwall has no surveys for country={cc}, falling back to all-country pool")
            filtered = surveys

        if not filtered:
            print("   WARNING: CINT offerwall has no surveys available in response")
            return []
        
        filtered = _apply_cint_quality_filter(filtered, respondent_age)
        filtered.sort(key=lambda s: _score_cint_survey(s, respondent_age), reverse=True)
        candidates = [str(s.get("SurveyNumber")) for s in filtered[:limit] if s.get("SurveyNumber")]
        print(f"   📡 CINT offerwall: Selected {len(candidates)} candidates")
        return candidates
        
    except Exception as e:
        print(f"   ❌ CINT offerwall error: {e}")
        return []


def _derive_cint_profiling_params(
    birthday_day: Optional[int] = None,
    birthday_month: Optional[int] = None,
    birthday_year: Optional[int] = None,
    gender: str = "",
    extra_profile_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Build CINT profile variable parameters from respondent profile data.

    Known CINT/Lucid profile IDs:
    - 42: Age
    - 43: Gender (1=Male, 2=Female, 3=Other/NA)
    """
    params: Dict[str, str] = {}

    if isinstance(extra_profile_params, dict):
        for raw_key, raw_value in extra_profile_params.items():
            key = str(raw_key).strip() if raw_key is not None else ""
            value = str(raw_value).strip() if raw_value is not None else ""
            if key and value:
                params[key] = value

    if "42" not in params and birthday_day and birthday_month and birthday_year:
        try:
            today = datetime.utcnow().date()
            age = today.year - birthday_year - (
                (today.month, today.day) < (birthday_month, birthday_day)
            )
            if 13 <= age <= 100:
                params["42"] = str(age)
        except Exception:
            pass

    if "43" not in params and gender:
        gender_norm = str(gender).strip().lower()
        gender_map = {
            "m": "1",
            "male": "1",
            "1": "1",
            "f": "2",
            "female": "2",
            "2": "2",
            "o": "3",
            "other": "3",
            "non-binary": "3",
            "nonbinary": "3",
            "3": "3",
        }
        mapped = gender_map.get(gender_norm)
        if mapped:
            params["43"] = mapped

    return params


def _build_cint_entry_link(
    live_link: str,
    hashed_pid: str,
    mid: str,
    user_email: str = "",
    profiling_params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a complete, correctly signed CINT entry link.

    Per Cint documentation the entry link must include:
      - SID   : returned in live_link from the Create-Link API
      - PID   : unique respondent identifier (we use SHA-256 of traffic_id)
      - MID   : unique session identifier (new UUID per session)
      - profile variables (optional): e.g. 42=AGE, 43=GENDER
      - cint_email : respondent email, hex-encoded SHA-256 hash (required)
      - hash  : HMAC-SHA1 of the full URL (minus &hash=…) signed with the
                Encryption Secret Key, then base64-url-safe encoded.

    The hash MUST be the last query parameter.
    """
    secret_key = os.getenv("CINT_WEBHOOK_SECRET", "")
    if not secret_key:
        print("   ⚠️ CINT_WEBHOOK_SECRET not set — entry link will be missing hash")

    # live_link already ends with "&PID=" or "?SID=…&PID="
    # We strip any trailing "&PID=" suffix that the API may have appended so
    # we can build the complete param string ourselves.
    base = live_link
    for suffix in ("&PID=", "?PID="):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    # Determine right separator after existing base
    sep = "&" if "?" in base else "?"

    # --- Required parameters ---
    # PID may only contain alphanumeric, underscore, dash (max 128 chars)
    # We truncate the 64-char hex SHA-256 to 64 chars (always safe)
    pid_value = hashed_pid[:64]

    # MID: unique per session, alphanumeric/underscore/dash, max 128 chars
    mid_value = mid[:128]

    # cint_email: SHA-256 of the lowercase email, 64-char hex string
    if user_email:
        email_hash = hashlib.sha256(user_email.lower().strip().encode("utf-8")).hexdigest()
    else:
        # Cint requires a real email — if missing, omit the parameter
        # rather than sending a dummy/invalid hash.
        email_hash = ""

    query_items: List[tuple[str, str]] = [
        ("PID", pid_value),
        ("MID", mid_value),
    ]

    if email_hash:
        query_items.append(("cint_email", email_hash))

    if profiling_params:
        reserved = {"pid", "mid", "cint_email", "hash"}
        for raw_key, raw_value in sorted(profiling_params.items(), key=lambda kv: str(kv[0])):
            key = str(raw_key).strip() if raw_key is not None else ""
            value = str(raw_value).strip() if raw_value is not None else ""
            if not key or not value:
                continue
            if key.lower() in reserved:
                continue
            query_items.append((key, value))

    url_no_hash = f"{base}{sep}{urlencode(query_items)}"

    # Add trailing & before hashing as per Cint requirements
    url_to_hash = url_no_hash + "&"

    # --- Hash signature (REQUIRED, must be last) ---
    if secret_key:
        sig = hmac.new(
            secret_key.encode("utf-8"),
            url_to_hash.encode("utf-8"),
            hashlib.sha1
        ).digest()
        # Use URL-safe Base64 without padding as per Cint documentation
        hash_value = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
        entry_url = f"{url_to_hash}hash={hash_value}"
    else:
        entry_url = url_no_hash

    # Safety guard: redirect URL limit per CINT docs is 2999 chars
    if len(entry_url) > 2999:
        print(f"   ⚠️ CINT entry link exceeds 2999 chars ({len(entry_url)}) — truncation risk!")

    return entry_url


async def create_cint_entry_link(
    survey_id: str,
    traffic_id: str,
    user_email: str = "",
    profiling_params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Create a respondent-specific CINT entry link (Asynchronous).

    Builds a fully-compliant Cint Exchange entry link that includes:
      PID, MID, optional profile vars (42/43/etc), cint_email,
      and the mandatory HMAC-SHA1 hash signature.

    Returns the full respondent-specific URL, or empty string on failure.
    """
    
    # Quick cache check — skip surveys that dropped from the offerwall
    try:
        try:
            from tasks.cint_survey_cleanup import is_survey_live
        except ImportError:
            from .tasks.cint_survey_cleanup import is_survey_live
        
        if not is_survey_live(str(survey_id)):
            print(f"   WARNING: CINT survey {survey_id} not in offerwall cache - proceeding with API create attempt")
    except Exception:
        pass  # Cache unavailable — proceed anyway
    
    api_key = os.getenv("CINT_API_KEY")
    supplier_code = os.getenv("CINT_SUPPLIER_CODE", "6777")
    
    if not api_key or not supplier_code:
        print(f"   ❌ CINT entry link: Missing credentials (API_KEY={'set' if api_key else 'MISSING'}, SUPPLIER_CODE={supplier_code})")
        return ""
    
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Callback URLs with [%PID%] placeholder — CINT replaces with our hashed PID
    # DefaultLink: where CINT sends respondent on survey error/closed — terminates back to us
    callback_base = CINT_CALLBACK_BASE
    create_payload = {
        "SupplierLinkTypeCode": "OWS",
        "TrackingTypeCode": "NONE",
        "DefaultLink": f"{callback_base}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]&reason=default_link",
        "SuccessLink": f"{callback_base}/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]",
        "FailureLink": f"{callback_base}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]",
        "OverQuotaLink": f"{callback_base}/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]",
        "QualityTerminationLink": f"{callback_base}/cint-response?status=quality_terminate&pid=[%PID%]&mid=[%MID%]",
    }
    
    live_link = ""
    
    try:
        client = _get_cint_async_client()
        # Step 1: Try to create SupplierLink (10s timeout for speed)
        create_url = f"{CINT_API_BASE}/Supply/v1/SupplierLinks/Create/{survey_id}/{supplier_code}"
        
        # Log full request payload
        print(f"   📤 CINT SupplierLinks/Create REQUEST (ASYNC):")
        print(f"      URL: {create_url}")
        
        resp = await client.post(create_url, json=create_payload, headers=headers, timeout=10.0)
        
        # Log full response
        print(f"   📥 CINT SupplierLinks/Create RESPONSE:")
        print(f"      Status: {resp.status_code}")
        try:
            resp_body = resp.json()
            print(f"      Body: {resp_body}")
        except:
            print(f"      Body (raw): {resp.text[:500]}")
            resp_body = {}
        
        if resp.status_code in (200, 201):
            sl = resp_body.get("SupplierLink", {})
            live_link = sl.get("LiveLink", "")
            print(f"   ✅ CINT SupplierLink CREATED for survey {survey_id}")
            print(f"      LiveLink: {live_link}")
            print(f"      CPI: {sl.get('CPI')}")
        
        elif resp.status_code == 409:
            # Already exists — GET existing link
            get_url = f"{CINT_API_BASE}/Supply/v1/SupplierLinks/BySurveyNumber/{survey_id}/{supplier_code}"
            print(f"   📤 CINT SupplierLink already exists (409), fetching: GET {get_url}")
            get_resp = await client.get(get_url, headers=headers, timeout=10.0)
            
            print(f"   📥 CINT GET SupplierLink RESPONSE: Status={get_resp.status_code}")
            try:
                get_body = get_resp.json()
                print(f"      Body: {get_body}")
            except:
                get_body = {}
                print(f"      Body (raw): {get_resp.text[:500]}")
            
            if get_resp.status_code == 200:
                sl = get_body.get("SupplierLink", {})
                live_link = sl.get("LiveLink", "")
                
                # Check if existing link has wrong DefaultLink — update if needed
                existing_default = sl.get("DefaultLink", "")
                if existing_default and "cint-response" not in existing_default:
                    print(f"   ⚠️ Existing SupplierLink has wrong DefaultLink: {existing_default}")
                    print(f"   🔄 Updating SupplierLink with correct redirect URLs...")
                    update_url = f"{CINT_API_BASE}/Supply/v1/SupplierLinks/Update/{survey_id}/{supplier_code}"
                    update_resp = await client.put(update_url, json=create_payload, headers=headers, timeout=10.0)
                    print(f"   📥 CINT SupplierLink UPDATE: Status={update_resp.status_code}")
                
                print(f"   ✅ CINT SupplierLink EXISTS for survey {survey_id}")
                print(f"      LiveLink: {live_link}")
            else:
                print(f"   ❌ CINT GET SupplierLink failed: status={get_resp.status_code}")
        
        elif resp.status_code == 404:
            print(f"   ❌ CINT survey {survey_id} not found (404) — survey closed")
        else:
            print(f"   ❌ CINT SupplierLink Create failed: status={resp.status_code}")
        
        if live_link:
            # PID: SHA-256 of traffic_id (unique, persistent respondent identifier)
            hashed_pid = hashlib.sha256(traffic_id.encode()).hexdigest()

            # MID: unique per-session identifier (new UUID each time)
            mid = uuid.uuid4().hex

            # Build the complete, signed entry link
            entry_url = _build_cint_entry_link(
                live_link,
                hashed_pid,
                mid,
                user_email,
                profiling_params=profiling_params,
            )
            if profiling_params:
                print(f"   CINT profiling params passed: {profiling_params}")
            print(f"   🔗 CINT entry link (signed): {entry_url}")
            
            # CRITICAL: Store the hashed PID in the traffic record so /cint-response
            # can look up the record when CINT sends [%PID%] back in the callback URL.
            # Without this, all respondents stay INCOMPLETE forever.
            try:
                async_url_collection = get_async_url_parameters_collection()
                await async_url_collection.update_one(
                    {"_id": ObjectId(traffic_id)},
                    {"$set": {
                        "cint_hashed_pid": hashed_pid,
                        "cint_mid": mid,
                        "cint_profiling_params": profiling_params or {},
                        "updatedAt": datetime.utcnow().isoformat()
                    }}
                )
                print(f"   💾 Stored cint_hashed_pid={hashed_pid[:16]}... mid={mid[:8]}... for traffic_id={traffic_id}")
            except Exception as store_err:
                print(f"   ⚠️ Failed to store cint_hashed_pid (non-fatal): {store_err}")
            
            return entry_url
        
        return ""
        
    except Exception as e:
        print(f"   ❌ CINT entry link error for survey {survey_id}: {e}")
        return ""


def _get_respondent_geo_country(traffic_record: dict) -> str:
    """Return GeoIP-verified country code, falling back to declared countryCode."""
    return traffic_record.get("geoIpCountry") or traffic_record.get("countryCode", "")


async def get_random_cint_fallback_link(traffic_record: dict, traffic_id: str) -> dict:
    """
    Pick ONE random CINT survey that fits the respondent's country and create an entry link.
    
    This replaces the old waterfall logic (which tried up to 5 surveys sequentially).
    Now we simply pick a random survey from the offerwall, create an entry link,
    and if it fails we give up and redirect to the vendor terminate URL.
    
    Returns: {"survey_id": str, "entry_link": str} or None
    """
    # Use GeoIP-verified country to avoid CINT GeoIP mismatch terminations
    country_code = _get_respondent_geo_country(traffic_record)
    declared_country = traffic_record.get("countryCode", "")
    if country_code != declared_country and declared_country:
        print(f"   🌍 CINT fallback: using geoIpCountry={country_code!r} (declared countryCode={declared_country!r})")

    user_email = traffic_record.get("email", "")
    profiling_data = traffic_record.get("profilingData", {}) or {}

    cint_profiling_params = (
        traffic_record.get("cint_profiling_params")
        or profiling_data.get("cint_profile_params")
        or {}
    )
    if not cint_profiling_params:
        cint_profiling_params = _derive_cint_profiling_params(
            birthday_day=profiling_data.get("birthday_day"),
            birthday_month=profiling_data.get("birthday_month"),
            birthday_year=profiling_data.get("birthday_year"),
            gender=profiling_data.get("gender", ""),
        )

    # Extract respondent age for demographic pre-screening
    respondent_age = None
    age_str = cint_profiling_params.get("42", "")
    if age_str:
        try:
            respondent_age = int(age_str)
        except (ValueError, TypeError):
            pass

    try:
        # Fetch live candidates from the CINT offerwall (uses cache when available)
        candidates = await fetch_cint_offerwall_candidates(country_code, limit=50, respondent_age=respondent_age)
        
        if not candidates:
            print(f"   ⚠️ CINT fallback: No candidates available for country={country_code}")
            return None
        
        # Try top-3 scored surveys (candidates are sorted by _score_cint_survey)
        top_candidates = candidates[:3]
        survey_id = None
        entry_link = None
        for sid in top_candidates:
            print(f"   🎯 CINT fallback: Trying scored survey {sid} (top {top_candidates.index(sid)+1} of {len(top_candidates)})")
            link = await create_cint_entry_link(
                sid,
                traffic_id,
                user_email=user_email,
                profiling_params=cint_profiling_params,
            )
            if link:
                survey_id = sid
                entry_link = link
                break
            print(f"   ⚠️ CINT fallback: Entry link failed for survey {sid}, trying next")
        
        if not entry_link:
            print(f"   ❌ CINT fallback: Failed to create entry link for top-{len(top_candidates)} surveys")
            return None
        
        # Update traffic record with CINT fallback info
        async_url_collection = get_async_url_parameters_collection()
        hashed_pid = hashlib.sha256(traffic_id.encode()).hexdigest()
        await async_url_collection.update_one(
            {"_id": ObjectId(traffic_id)},
            {
                "$set": {
                    "currentCintSurveyId": survey_id,
                    "currentCintLink": entry_link,
                    "cint_hashed_pid": hashed_pid,
                    "cint_profiling_params": cint_profiling_params,
                    "status": "CPX_TERMINATED_CINT_FALLBACK",
                    "surveySource": "CINT_FALLBACK",
                    "updatedAt": datetime.utcnow().isoformat(),
                },
            }
        )
        
        print(f"   ✅ CINT fallback SUCCESS: survey {survey_id}")
        return {
            "survey_id": survey_id,
            "entry_link": entry_link,
        }
        
    except Exception as e:
        print(f"   ❌ CINT fallback error: {e}")
        import traceback
        traceback.print_exc()
        return None


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
    revenue: str = Query(None, description="Revenue/payout amount"),
    rpi: str = Query(None, description="Revenue per interview (appended by Cint)"),
    survey_id: str = Query(None, description="Cint survey number [%RSFN%]"),
    marketplace_status: str = Query(None, description="Cint marketplace status [%InitialStatus%]"),
    client_status: str = Query(None, description="Cint client status [%ClientStatus%]"),
    termed_qualification_id: str = Query(None, description="Qualification ID that caused termination"),
    termed_quota_id: str = Query(None, description="Quota ID that caused termination"),
    reason: str = Query(None, description="Termination reason (e.g. default_link)"),
):
    """
    Cint Survey Callback Handler
    
    URL format: /cint-response?status={status}&pid={pid}&mid={mid}&revenue={revenue}
    
    Cint appends additional tracking parameters via Supplier Redirect template:
    - survey_id: [%RSFN%] — Cint survey number
    - marketplace_status: [%InitialStatus%] — Cint's initial marketplace status
    - client_status: [%ClientStatus%] — Client-side status
    - termed_qualification_id: [%TermedQualificationID%] — Qual that caused term
    - termed_quota_id: [%TermedQuotaID%] — Quota that caused term
    - rpi: [%REVENUE%] — Revenue per interview (duplicate of revenue)
    - Demographic data (42=AGE, 43=GENDER, etc.) — captured in full query string
    """
    try:
        print(f"📥 Cint Callback received: status={status}, pid={pid}, mid={mid}, revenue={revenue}")
        print(f"   📊 Cint extras: survey_id={survey_id}, marketplace_status={marketplace_status}, client_status={client_status}")
        if termed_qualification_id or termed_quota_id:
            print(f"   🚫 Termination reason: qual_id={termed_qualification_id}, quota_id={termed_quota_id}")
        
        # Map Cint status to internal status
        status_mapping = {
            "complete": "COMPLETE",
            "terminate": "TERMINATED",
            "quota_full": "OVERQUOTA",
            "quality_terminate": "QUALITY_TERM"
        }
        new_status = status_mapping.get(status.lower(), "TERMINATED")
        redirect_type = "completeRD" if new_status == "COMPLETE" else "terminateRD"
        
        # Primary lookup key is PID (traffic record ID)
        lookup_id = pid or mid
        if not lookup_id:
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=missing_id")
        
        # Find traffic record asynchronously
        async_url_collection = get_async_url_parameters_collection()
        traffic_record = None
        
        # CINT always sends back the SHA256 hashed PID in [%PID%] placeholder.
        # So lookup by cint_hashed_pid is the PRIMARY path - try it first.
        if lookup_id:
            traffic_record = await async_url_collection.find_one({"cint_hashed_pid": lookup_id})
            if traffic_record:
                print(f"✅ Found traffic record by cint_hashed_pid: {lookup_id[:16]}...")
        
        # Fallback: try as raw ObjectId (legacy, before hashed PID was used)
        if not traffic_record:
            try:
                traffic_record = await async_url_collection.find_one({"_id": ObjectId(lookup_id)})
                if traffic_record:
                    print(f"✅ Found traffic record by ObjectId: {lookup_id}")
            except:
                pass
        
        # Fallback: try by respondentId
        if not traffic_record:
            traffic_record = await async_url_collection.find_one({"respondentId": lookup_id})
        
        # Fallback: try by MID
        if not traffic_record and mid:
            traffic_record = await async_url_collection.find_one({"cint_mid": mid})
        
        if not traffic_record:
            print(f"⚠️ Traffic record not found for pid={pid}, mid={mid}")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=not_found")
        
        # Get vendor info
        vendor_id = traffic_record.get("vendorId")
        respondent_id = traffic_record.get("respondentId", "")
        
        # Build update with core fields + Cint-appended tracking data
        update_fields = {
            "status": new_status,
            "cint_mid": mid,
            "cint_revenue": revenue or rpi,  # Use rpi as fallback
            "cintCallbackUrl": str(request.url),
            "updatedAt": datetime.utcnow(),
            "completedAt": datetime.utcnow() if new_status == "COMPLETE" else None,
        }
        
        # Store Cint-appended tracking data (from Supplier Redirect template)
        if survey_id:
            update_fields["cint_survey_id"] = survey_id
        if marketplace_status:
            update_fields["cint_marketplace_status"] = marketplace_status
        if client_status:
            update_fields["cint_client_status"] = client_status
        if termed_qualification_id:
            update_fields["cint_termed_qualification_id"] = termed_qualification_id
        if termed_quota_id:
            update_fields["cint_termed_quota_id"] = termed_quota_id
        if reason:
            update_fields["cint_termination_reason"] = reason
        
        # Update traffic status asynchronously
        await async_url_collection.update_one(
            {"_id": traffic_record["_id"]},
            {"$set": update_fields}
        )
        
        # Helper: resolve vendor from vendor_id (try int and string variants)
        async def _get_vendor(vid):
            async_vendors_col = get_async_vendors_collection()
            v = await async_vendors_col.find_one({"vid": vid})
            if not v and isinstance(vid, str) and vid.isdigit():
                v = await async_vendors_col.find_one({"vid": int(vid)})
            if not v and isinstance(vid, int):
                v = await async_vendors_col.find_one({"vid": str(vid)})
            return v

        def _extract_redirect_url(vendor_doc, field: str, fallback: str, respondent_id_val: str) -> str:
            """Extract redirect URL from a vendor's list field and append respondent ID."""
            urls = vendor_doc.get(field, [])
            vendor_variable = vendor_doc.get("vendorVariable", "id")
            # completeRD / terminateRD are stored as lists; take first non-empty entry
            if isinstance(urls, list):
                base_url = next((u.strip() for u in urls if u and u.strip()), None)
            elif isinstance(urls, str) and urls.strip():
                base_url = urls.strip()
            else:
                base_url = None

            if not base_url:
                base_url = fallback

            if respondent_id_val:
                if base_url.endswith(f"&{vendor_variable}=") or base_url.endswith(f"?{vendor_variable}="):
                    return f"{base_url}{respondent_id_val}"
                elif f"&{vendor_variable}=" in base_url or f"?{vendor_variable}=" in base_url:
                    separator = "&" if "?" in base_url else "?"
                    return f"{base_url}{separator}{vendor_variable}={respondent_id_val}"
                else:
                    separator = "&" if "?" in base_url else "?"
                    return f"{base_url}{separator}{vendor_variable}={respondent_id_val}"
            return base_url

        # If COMPLETE, redirect to vendor complete URL
        if new_status == "COMPLETE":
            redirect_url = f"{FRONTEND_URL}/thankyou"
            if vendor_id:
                vendor = await _get_vendor(vendor_id)
                if vendor:
                    redirect_url = _extract_redirect_url(vendor, "completeRD", redirect_url, respondent_id)
                else:
                    # No vendor found — still append respondent ID to fallback
                    if respondent_id:
                        separator = "&" if "?" in redirect_url else "?"
                        redirect_url = f"{redirect_url}{separator}id={respondent_id}"
            elif respondent_id:
                separator = "&" if "?" in redirect_url else "?"
                redirect_url = f"{redirect_url}{separator}id={respondent_id}"

            print(f"✅ Cint COMPLETE (ASYNC): Redirecting to {redirect_url}")
            return RedirectResponse(url=redirect_url)

        # TERMINATED / OVERQUOTA / QUALITY_TERM from Cint: redirect to vendor terminate URL
        redirect_url = f"{FRONTEND_URL}/survey-error"
        if vendor_id:
            vendor = await _get_vendor(vendor_id)
            if vendor:
                redirect_url = _extract_redirect_url(vendor, "terminateRD", redirect_url, respondent_id)
            else:
                if respondent_id:
                    separator = "&" if "?" in redirect_url else "?"
                    redirect_url = f"{redirect_url}{separator}id={respondent_id}"
        elif respondent_id:
            separator = "&" if "?" in redirect_url else "?"
            redirect_url = f"{redirect_url}{separator}id={respondent_id}"

        print(f"✅ Cint {new_status}, redirecting to {redirect_url}")
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
        if status:
            status_code = status
        elif msg and msg.lower() in ["complete", "out", "terminate", "quotafull", "quality_terminate"]:
            status_code = msg
        else:
            status_code = "out"
        
        resolved_sfwid = sfwid or subid_1 or subid
        print(f"📥 CPX Callback received: msg={msg}, resolved_status={status_code}, sfwid={resolved_sfwid}")
        
        if not resolved_sfwid:
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        decoded_sfwid = resolved_sfwid
        
        if status_code.lower() == "complete":
            new_status = "COMPLETE"
            redirect_type = "completeRD"
        else: 
            new_status = "TERMINATED"
            redirect_type = "terminateRD"
        
        # Async DB collections
        async_url_collection = get_async_url_parameters_collection()
        async_vendors_col = get_async_vendors_collection()
        async_logs_col = get_async_cpx_callback_logs_collection()
        
        # Immediate callback logging (Async)
        initial_log_id = None
        try:
            initial_log_entry = {
                "timestamp": datetime.utcnow(),
                "callback_url": str(request.url),
                "msg_param": msg,
                "status_code": status_code,
                "new_status": new_status,
                "decoded_sfwid": decoded_sfwid,
                "rid_received": rid,
                "trans_id": trans_id,
                "processing_status": "pending",
                "success": False
            }
            log_result = await async_logs_col.insert_one(initial_log_entry)
            initial_log_id = log_result.inserted_id
        except Exception as log_error:
            print(f"⚠️ Failed to log callback: {log_error}")
        
        # Idempotency Check (Async)
        hour_bucket = datetime.utcnow().strftime("%Y%m%d%H")
        callback_key = f"{decoded_sfwid}:{new_status}:{hour_bucket}"
        
        existing_callback = await async_logs_col.find_one({
            "callback_key": callback_key,
            "success": True
        })
        if existing_callback:
            print(f"⚠️ Duplicate CPX callback: {callback_key}")
            existing_redirect = existing_callback.get("vendor_redirect_url")
            if existing_redirect:
                return RedirectResponse(url=existing_redirect)
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        # Find traffic record asynchronously
        traffic_record = None
        try:
            traffic_record = await async_url_collection.find_one({"_id": ObjectId(decoded_sfwid)})
        except:
            pass
        
        if not traffic_record:
            traffic_record = await async_url_collection.find_one({"_id": decoded_sfwid})
        
        if not traffic_record:
            print(f"❌ No traffic record found for SFWID: {decoded_sfwid}")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error")
        
        traffic_id = str(traffic_record["_id"])
        vendor_id = traffic_record.get("vendorId")
        original_respondent_id = traffic_record.get("respondentId")
        
        # Look up vendor asynchronously
        vendor = None
        vendor_redirect_url = None
        
        if vendor_id:
            vendor = await async_vendors_col.find_one({"vid": vendor_id})
            if not vendor and str(vendor_id).isdigit():
                vendor = await async_vendors_col.find_one({"vid": int(vendor_id)})
                
            if vendor:
                redirect_urls = vendor.get(redirect_type, [])
                vendor_variable = vendor.get("vendorVariable", "rid")
                
                if redirect_urls and len(redirect_urls) > 0:
                    base_url = redirect_urls[0].strip()
                    if base_url:
                        # Smarter URL construction to avoid double RID=
                        if base_url.endswith(f"&{vendor_variable}=") or base_url.endswith(f"?{vendor_variable}="):
                            vendor_redirect_url = f"{base_url}{original_respondent_id}"
                        elif f"&{vendor_variable}=" in base_url or f"?{vendor_variable}=" in base_url:
                            # If it's already there but has no value, we might have RID=&RID=
                            # Best to just append if not clearly at the end
                            if base_url.endswith(f"{vendor_variable}="):
                                vendor_redirect_url = f"{base_url}{original_respondent_id}"
                            else:
                                separator = "&" if "?" in base_url else "?"
                                vendor_redirect_url = f"{base_url}{separator}{vendor_variable}={original_respondent_id}"
                        else:
                            separator = "&" if "?" in base_url else "?"
                            vendor_redirect_url = f"{base_url}{separator}{vendor_variable}={original_respondent_id}"

        # Update traffic record asynchronously
        update_data = {
            "status": new_status,
            "updatedAt": datetime.utcnow(),
            "cpxCallbackUrl": str(request.url)
        }
        if vendor_redirect_url:
            update_data["outUrl"] = vendor_redirect_url
        if new_status == "COMPLETE":
            update_data["completedAt"] = datetime.utcnow()
        
        await async_url_collection.update_one(
            {"_id": ObjectId(traffic_id)},
            {"$set": update_data}
        )
        
        # Update callback log asynchronously
        if initial_log_id:
            try:
                await async_logs_col.update_one(
                    {"_id": initial_log_id},
                    {"$set": {
                        "callback_key": callback_key,
                        "processing_status": "completed",
                        "traffic_id": traffic_id,
                        "traffic_found": traffic_record is not None,
                        "vendor_id": vendor_id,
                        "vendor_found": vendor is not None,
                        "vendor_name": vendor.get("name") if vendor else None,
                        "respondent_id": original_respondent_id,
                        "redirect_type": redirect_type,
                        "vendor_redirect_url": vendor_redirect_url,
                        "success": vendor_redirect_url is not None,
                        "completed_at": datetime.utcnow()
                    }}
                )
            except Exception as log_error:
                print(f"⚠️ Failed to update CPX log: {log_error}")
        
        # Handle final redirect
        if new_status == "COMPLETE":
            if vendor_redirect_url:
                print(f"➡️ CPX Complete (ASYNC): Redirecting to vendor: {vendor_redirect_url}")
                return RedirectResponse(url=vendor_redirect_url)
            else:
                return RedirectResponse(url=f"{FRONTEND_URL}/thankyou")
        else:
            # CPX TERMINATED: Try to redirect to a random CINT survey as fallback
            try:
                cint_result = await get_random_cint_fallback_link(traffic_record, traffic_id)
                if cint_result:
                    print(f"✅ CINT fallback: Redirecting CPX-terminated user to Cint survey {cint_result['survey_id']}")
                    return RedirectResponse(url=cint_result["entry_link"])
            except Exception as cint_err:
                print(f"⚠️ CINT fallback failed: {cint_err}")
            
            # CINT fallback failed — redirect to vendor terminate URL
            if vendor_redirect_url:
                print(f"➡️ CPX terminated, CINT fallback failed: Redirecting to vendor terminate: {vendor_redirect_url}")
                return RedirectResponse(url=vendor_redirect_url)
            else:
                return RedirectResponse(url=ZOHO_TERMINATE_URL)
        
    except Exception as e:
        print(f"❌ Error in CPX callback: {e}")
        import traceback
        traceback.print_exc()
        
        error_log = {
            "timestamp": datetime.utcnow(),
            "callback_url": str(request.url),
            "msg_param": msg,
            "status_param": status,
            "sfwid_param": decoded_sfwid if 'decoded_sfwid' in locals() else resolved_sfwid,
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        
        if get_async_cpx_callback_logs_collection() is not None:
            try:
                # Use await for async collection
                await get_async_cpx_callback_logs_collection().insert_one(error_log)
                print(f"📝 Logged error to callback logs")
            except Exception as log_err:
                print(f"⚠️ Failed to log error: {log_err}")
        
        # Always redirect to terminate page on error
        return RedirectResponse(url=ZOHO_TERMINATE_URL)


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
        geo_country = request.headers.get("CF-IPCountry", "").lower().strip()
        print(f"📍 Prefetch IP: {client_ip} (source: {ip_source}, geo_country: {geo_country or 'unknown'})")
        
        return JSONResponse(content={
            "ip": client_ip,
            "source": ip_source,
            "geoCountry": geo_country,
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
        project_number = str(params.get('pid', '') or '').strip()
        api_flag = str(params.get('api', '') or '').strip().lower()
        is_project_adhoc_flow = api_flag == "false" and bool(project_number)
        enable_cint_primary_fallback = os.getenv("ENABLE_CINT_PRIMARY_FALLBACK", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        
        traffic_id = None
        entry_link = None
        survey_id = None
        actual_provider = None
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
        geo_ip_country = (data.get('geoCountry') or "").lower().strip()

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
        raw_day = data.get('birthday_day')
        raw_month = data.get('birthday_month')
        raw_year = data.get('birthday_year')
        
        # Safely convert to integers for formatting and provider use
        def to_safe_int(val, default=None):
            try:
                if val is None or val == "": return default
                return int(val)
            except (ValueError, TypeError):
                return default

        birthday_day = to_safe_int(raw_day)
        birthday_month = to_safe_int(raw_month)
        birthday_year = to_safe_int(raw_year)
        
        gender = data.get('gender', '').strip().lower()
        zip_code = data.get('zip_code', '').strip()

        cint_profiling_params = _derive_cint_profiling_params(
            birthday_day=birthday_day,
            birthday_month=birthday_month,
            birthday_year=birthday_year,
            gender=gender,
        )
        profiling_data = {
            "birthday_day": birthday_day,
            "birthday_month": birthday_month,
            "birthday_year": birthday_year,
            "gender": gender,
            "zip_code": zip_code,
            "cint_profile_params": cint_profiling_params,
        }

        # Log profiling data if provided
        if birthday_day is not None and birthday_month is not None and birthday_year is not None:
            try:
                print(f"📅 User DOB: {birthday_year}-{birthday_month:02d}-{birthday_day:02d}")
            except Exception as e:
                print(f"📅 User DOB: {birthday_year}-{birthday_month}-{birthday_day} (format error: {e})")
        if gender:
            print(f"⚧ User gender: {gender}")
        if zip_code:
            print(f"📮 User zip/postal code: {zip_code}")

        if cint_profiling_params:
            print(f"CINT profiling params prepared: {cint_profiling_params}")

        # Log IP extraction for debugging
        if not client_ip:
            print("⚠️ WARNING: No valid IP could be extracted! CPX API targeting may fail.")
        
        # ===================================================================================
        # STEP 1: CREATE TRAFFIC RECORD (SFWID) - ASYNCHRONOUS
        # ===================================================================================
        async_url_collection = get_async_url_parameters_collection()
        
        # If traffic service is available, use its async method
        if traffic_service and vendor_id and country_code and respondent_id:
            try:
                # Check if traffic_service has the async method we just added
                if hasattr(traffic_service, 'async_create_traffic_record'):
                    traffic_id = await traffic_service.async_create_traffic_record(
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
                        email=user_email,
                        profiling_data=profiling_data,
                    )
                else:
                    # Fallback to direct async insertion if service not updated yet
                    data['timestamp'] = datetime.utcnow().isoformat()
                    data['status'] = 'INCOMPLETE'
                    data['createdAt'] = datetime.utcnow()
                    data['respondentId'] = respondent_id
                    data['vendorId'] = vendor_id
                    data['countryCode'] = country_code
                    result = await async_url_collection.insert_one(data)
                    traffic_id = str(result.inserted_id)
                
                print(f"✅ Created traffic record (ASYNC SFWID): {traffic_id}")
            except Exception as e:
                print(f"⚠️ Failed to create async traffic record: {e}")
        
        # Legacy fallback - store as before but async
        if not traffic_id:
            try:
                # Build a clean record instead of inserting raw request data
                # (raw data may contain non-BSON-serializable values)
                fallback_record = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'status': 'INCOMPLETE',
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                    'respondentId': respondent_id,
                    'vendorId': vendor_id,
                    'countryCode': country_code,
                    'geoIpCountry': geo_ip_country,
                    'clientIp': client_ip,
                    'ipSource': client_ip_source,
                    'userAgent': client_user_agent,
                    'deviceFingerprint': device_fingerprint,
                    'params': params or {},
                    'email': user_email,
                    'profilingData': profiling_data,
                }
                result = await async_url_collection.insert_one(fallback_record)
                traffic_id = str(result.inserted_id)
                result = await async_url_collection.insert_one(fallback_record)
                traffic_id = str(result.inserted_id)
                print(f"✅ Created traffic record (LEGACY FALLBACK): {traffic_id}")
            except Exception as fallback_err:
                print(f"⚠️ Legacy fallback traffic record creation also failed: {fallback_err}")
                # traffic_id remains None; allocation block will be skipped gracefully
        
        # ===============================================================================
        # CASE 1: PROJECT-BASED (ADHOC) FLOW (api=false & pid=<project_number>)
        # ===============================================================================
        if is_project_adhoc_flow and traffic_id:
            print(f"🔀 Strategy: PROJECT-BASED (ADHOC). PID={project_number}, SFWID={traffic_id}")
            
            project_doc = await _resolve_live_project_async(project_number)
            if project_doc:
                client_variable = await _resolve_project_client_variable_async(project_doc)
                base_live_link = project_doc.get("liveLink") or project_doc.get("clientLink") or ""
                
                if base_live_link:
                    entry_link = _replace_live_link_respondent(base_live_link, traffic_id, client_variable)
                    survey_id = project_doc.get("surveyNo") or project_number
                    allocation_success = True
                    actual_provider = "PROJECT"
                    
                    # Update traffic record with project info
                    await async_url_collection.update_one(
                        {"_id": ObjectId(traffic_id)},
                        {"$set": {
                            "status": "INCOMPLETE",
                            "assignedSurveyId": str(survey_id),
                            "redirectUrl": entry_link,
                            "surveySource": "PROJECT",
                            "projectId": str(project_doc.get("_id")),
                            "client_variable": client_variable,
                            "updatedAt": datetime.utcnow().isoformat(),
                        }}
                    )
                    print(f"✅ PROJECT allocation success: survey {survey_id}")
                else:
                    allocation_error = "Project has no live link configured."
            else:
                allocation_error = f"Live project not found for number: {project_number}"
            
            if not allocation_success:
                print(f"❌ PROJECT allocation failed: {allocation_error}")

        # ===============================================================================
        # CASE 2: CPX/CINT FLOW (Standard API flow)
        # ===============================================================================
        elif not allocation_success and vendor_id and country_code and traffic_id:
            print(f"🔀 Strategy: CPX ONLY at start. SFWID={traffic_id}")
        
        # ============================================
        # HELPER FUNCTION: CPX Allocation (ASYNCHRONOUS)
        # ============================================
        async def try_cpx_allocation():
            nonlocal allocation_success, entry_link, survey_id, actual_provider, allocation_error
            
            try:
                # Log CPX routing attempt
                print(f"📍 CPX ASYNC: IP={client_ip}, SFWID={traffic_id}")
                
                # Check if CPX service is available
                if cpx_service is None:
                    print("⚠️ CPX ASYNC: CPX service not available")
                    allocation_error = "CPX service not available"
                    return False
                
                # Use internal mid context for tracking
                import uuid
                cpx_mid = uuid.uuid4().hex[:16]
                
                # CPX IDENTITY CHANGE: Use SFWID (traffic_id) as vendor_user_id (ext_user_id for CPX)
                # as requested by the user ("RID is changed to SFWID")
                cpx_vendor_user_id = traffic_id
                
                # Select the correct method based on service capabilities
                if hasattr(cpx_service, 'async_fetch_and_allocate_for_respondent'):
                    result = await cpx_service.async_fetch_and_allocate_for_respondent(
                        vendor_user_id=cpx_vendor_user_id,
                        internal_tracking_id=traffic_id,
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
                else:
                    # Fallback to thread if async version not yet fully ready
                    result = await asyncio.to_thread(
                        cpx_service.fetch_and_allocate_for_respondent,
                        vendor_user_id=cpx_vendor_user_id,
                        internal_tracking_id=traffic_id,
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
                    actual_provider = "CPX"
                    allocation_error = None
                    
                    # Update traffic record asynchronously (only if we have a valid traffic_id)
                    if traffic_id:
                        async_url_collection = get_async_url_parameters_collection()
                        await async_url_collection.update_one(
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
                    else:
                        print("⚠️ CPX allocation succeeded but no traffic_id to update record")
                    return True
                cpx_error = (
                    result.get("error")
                    or result.get("message")
                    or "No CPX survey available for this respondent"
                )
                allocation_error = f"CPX allocation failed: {cpx_error}"
                return False
                    
            except Exception as e:
                print(f"⚠️ CPX async allocation error: {e}")
                allocation_error = f"CPX allocation exception: {str(e)}"
                return False

        
        # ============================================
        # HELPER FUNCTION: CINT Allocation (ASYNCHRONOUS)
        # ============================================
        async def try_cint_allocation():
            nonlocal allocation_success, entry_link, survey_id, actual_provider, allocation_error
            
            try:
                # Fetch fresh candidates from CINT offerwall API (Async)
                # Use GeoIP-verified country to avoid mismatch terminations
                effective_country = geo_ip_country or country_code
                respondent_age_for_cint = None
                age_str_for_cint = cint_profiling_params.get("42", "")
                if age_str_for_cint:
                    try:
                        respondent_age_for_cint = int(age_str_for_cint)
                    except (ValueError, TypeError):
                        pass
                if effective_country != country_code and country_code:
                    print(f"   🌍 CINT allocation: using geoIpCountry={effective_country!r} (declared: {country_code!r})")
                candidates = await fetch_cint_offerwall_candidates(effective_country, limit=50, respondent_age=respondent_age_for_cint)
                
                if not candidates:
                    allocation_error = "CINT fallback has no candidates for this country"
                    return False
                
                # Try candidates one by one until we get a working entry link
                # user_email is accessible from the enclosing /api/store scope
                for sid in candidates[:15]:
                    link = await create_cint_entry_link(
                        sid,
                        traffic_id,
                        user_email=user_email,
                        profiling_params=cint_profiling_params,
                    )
                    if link:
                        entry_link = link
                        survey_id = sid
                        allocation_success = True
                        actual_provider = "CINT"
                        allocation_error = None
                        
                        # Update traffic record asynchronously
                        async_url_collection = get_async_url_parameters_collection()
                        hashed_pid = hashlib.sha256(traffic_id.encode()).hexdigest()
                        await async_url_collection.update_one(
                            {"_id": ObjectId(traffic_id)},
                            {"$set": {
                                "status": "INCOMPLETE",
                                "assignedSurveyId": survey_id,
                                "redirectUrl": entry_link,
                                "surveySource": "CINT",
                                "currentCintSurveyId": survey_id,
                                "cint_hashed_pid": hashed_pid,
                                "cint_profiling_params": cint_profiling_params,
                                "geoIpCountry": geo_ip_country,
                                "updatedAt": datetime.utcnow().isoformat(),
                            }}
                        )
                        return True
                return False
                    
            except Exception as e:
                print(f"⚠️ CINT async allocation error: {e}")
                allocation_error = f"CINT allocation exception: {str(e)}"
                return False
        
        # ===============================================================================
        # EXECUTE ALLOCATION STRATEGY
        # ===============================================================================
        if not allocation_success and vendor_id and country_code and traffic_id:
            # Try CPX allocation first
            await try_cpx_allocation()
            
            # If CPX fails and we have country code, fallback to CINT
            if not allocation_success and country_code:
                if enable_cint_primary_fallback:
                    print("📌 CPX allocation failed, attempting CINT fallback (enabled via env)...")
                    await try_cint_allocation()
                else:
                    print("📌 CPX allocation failed; CINT primary fallback is disabled")
                    if not allocation_error:
                        allocation_error = "No CPX survey available for this respondent"
        
        # ===============================================================================
        # BUILD RESPONSE
        # ===============================================================================
        response_data = {
            "id": str(traffic_id) if traffic_id else None,
            "type": actual_provider.lower() if actual_provider else "unknown",
            "entry_link": entry_link or "",
            "survey_id": survey_id or "",
            "traffic_id": str(traffic_id) if traffic_id else "",
            "allocation_success": allocation_success,
            "allocation_error": allocation_error,
            "source": actual_provider or "UNKNOWN",
            "debug_info": {
                "provider": actual_provider,
                "ip": client_ip,
                "country_code": country_code,
                "vendor_id": vendor_id,
            }
        }
        
        if not allocation_success:
            print(f"⚠️ No allocation achieved. Error: {allocation_error}")
        
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in /api/store: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Traffic store error: {str(e)}")


@router.get("/cpx/redirect")
async def cpx_redirect(request: Request, id: str = Query(..., description="Traffic record ID")):
    """
    Redirect to CPX survey entry link.
    
    The frontend calls this endpoint after successfully storing traffic data and allocating a survey.
    This endpoint:
    1. Retrieves the traffic record by ID
    2. Extracts the CPX entry link from redirectUrl
    3. Performs a 302 HTTP redirect to the survey
    
    The HTTP redirect (not JS redirect) is CRITICAL because:
    - CPX needs the request origin to match expectations
    - JS redirects can expose parameters in different ways
    - Server-side 302 redirect preserves CPX URL integrity
    """
    try:
        if url_parameters_collection is None:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        # Get traffic record
        try:
            traffic_id = ObjectId(id)
            record = await get_async_url_parameters_collection().find_one({"_id": traffic_id})
        except Exception:
            # If ID is not a valid ObjectId, try as string match
            record = await get_async_url_parameters_collection().find_one({"_id": id})
        
        if not record:
            print(f"❌ CPX Redirect: Traffic record not found: {id}")
            raise HTTPException(status_code=404, detail=f"Traffic record not found: {id}")
        
        # Get the entry link from the record
        entry_link = (record.get("redirectUrl") or record.get("entry_link") or "").strip()
        
        if not entry_link:
            print(f"❌ CPX Redirect: No entry link in traffic record {id}")
            raise HTTPException(status_code=400, detail="No survey entry link available")
        
        # Validate redirect URL for safety while allowing CPX, CINT, and project links.
        parsed_entry_link = urlparse(entry_link)
        entry_host = (parsed_entry_link.hostname or "").lower()
        survey_source = str(record.get("surveySource") or "").upper()

        if not entry_host:
            print(f"❌ CPX Redirect: Invalid entry link host for traffic record {id}: {entry_link[:80]}...")
            raise HTTPException(status_code=400, detail="Invalid survey entry link")

        is_local_dev = entry_host in {"localhost", "127.0.0.1", "::1"}
        if is_local_dev:
            if parsed_entry_link.scheme not in ("http", "https"):
                print(f"❌ CPX Redirect: Invalid localhost scheme: {parsed_entry_link.scheme}")
                raise HTTPException(status_code=400, detail="Invalid survey entry link")
        else:
            is_valid, error_msg = validate_redirect_url(entry_link, require_https=False)
            if not is_valid:
                print(f"❌ CPX Redirect: Invalid entry link ({error_msg}): {entry_link[:80]}...")
                raise HTTPException(status_code=400, detail="Invalid survey entry link")

        # CPX allocations must always redirect to a CPX-owned HTTPS host.
        if survey_source == "CPX":
            if parsed_entry_link.scheme != "https" or not entry_host.endswith("cpx-research.com"):
                print(
                    f"❌ CPX Redirect: Invalid CPX host '{entry_host}' "
                    f"(source={survey_source}, id={id})"
                )
                raise HTTPException(status_code=400, detail="Invalid CPX entry link domain")
        
        # Perform HTTP 302 redirect (preserves CPX parameters and request integrity)
        print(f"✅ CPX Redirect: Redirecting SFWID {id} to survey")
        return RedirectResponse(url=entry_link, status_code=302)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in /cpx/redirect: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"CPX redirect error: {str(e)}")


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


@router.get("/api/traffic/dashboard-stats")
async def get_dashboard_traffic_stats(
    request: Request,
    days: int = Query(7, ge=1, le=30, description="Number of days for daily trend"),
    survey_id: str = Query(None, description="Optional survey ID to filter stats"),
    bypass_cache: bool = Query(False, description="Force fresh stats"),
):
    """
    Get dashboard-oriented traffic stats:
    totals, status split, daily trend, top countries, and completes by source.
    Requires authentication.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")

        if traffic_service is None:
            raise HTTPException(status_code=503, detail="Traffic service not initialized")

        cache_key = _get_traffic_cache_key("dashboard_stats", days=days, survey_id=survey_id)
        if not bypass_cache:
            cached = _get_traffic_cached(cache_key)
            if cached is not None:
                return cached

        stats = traffic_service.get_dashboard_traffic_stats(days=days, survey_id=survey_id)
        _set_traffic_cached(cache_key, stats, ttl=15)
        return stats
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting dashboard traffic stats: {e}")
        raise HTTPException(status_code=500, detail=f"Dashboard stats error: {str(e)}")


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
        "survey_url": "https://click.cpx-research.com/index.php",
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
                # Cint Fields
                "survey_source": record.get("surveySource", ""),
                "cint_entry_link": record.get("currentCintLink", ""),
                "cint_callback_url": record.get("cintCallbackUrl", ""),
                "cint_survey_id": record.get("currentCintSurveyId", ""),
                "cint_hashed_pid": record.get("cint_hashed_pid", ""),
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
            "Survey Source",
            "Redirect URL",
            "Client URL (Out URL)",
            "CPX Callback URL",
            "Cint Entry Link",
            "Cint Callback URL",
            "Cint Survey ID",
            "Cint Hashed PID",
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
                record.get("surveySource", ""),
                record.get("redirectUrl", ""),
                record.get("outUrl", ""),
                record.get("cpxCallbackUrl", ""),
                record.get("currentCintLink", ""),
                record.get("cintCallbackUrl", ""),
                record.get("currentCintSurveyId", ""),
                record.get("cint_hashed_pid", ""),
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


# ============================================================================
# VENDOR TRAFFIC INTEGRATION
# ============================================================================
# Flow: Vendor → /takesurvey (parsing page) → Client live link
#        → Client returns via /vendor-response → Vendor redirect URL
# ============================================================================


@router.get("/takesurvey")
async def vendor_takesurvey(
    request: Request,
    api: str = Query(None, description="Use 'false' with pid for project-based flow"),
    pid: str = Query(None, description="Project number (surveyNo) from study pool"),
    vid: str = Query(None, description="Vendor ID"),
    cc: str = Query(None, description="Country code (ISO2)"),
    rid: str = Query(None, description="Respondent ID from vendor — stored, replaced with SFWID"),
):
    """
    Vendor Traffic Parsing Page

    Receives vendor traffic, creates a traffic record (SFWID), resolves the live
    project from the study pool, injects SFWID into the client's live link, and
    immediately redirects the respondent to the client survey.

    URL format:
        /takesurvey?api=false&pid=<project_no>&vid=<vendor_id>&cc=<country_code>&rid=<respondent_id>

    Traffic flow:
        Vendor → /takesurvey → Client live link (SFWID injected)
            → /vendor-response?status=<status>&sfwid=<SFWID>
                → Vendor redirect URL (original RID appended)
    """
    try:
        print(f"📥 /takesurvey hit: api={api}, pid={pid}, vid={vid}, cc={cc}, rid={rid}")

        api_flag = str(api or "").strip().lower()
        is_project_flow = api_flag == "false" and bool(pid)

        # Standard CPX/CINT flow (for links like api=dalse) should land on the
        # frontend parser page, which then calls /api/store.
        if not is_project_flow:
            if not vid or not cc or not rid:
                print("❌ /takesurvey: Missing required params (vid, cc, rid)")
                return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=missing_params")

            forwarded_query = request.url.query or ""
            parser_url = f"{FRONTEND_URL}/survey-start"
            if forwarded_query:
                parser_url = f"{parser_url}?{forwarded_query}"

            print(f"↪️ /takesurvey: Forwarding standard flow to parser page: {parser_url}")
            return RedirectResponse(url=parser_url)

        if not vid or not cc or not rid:
            print("❌ /takesurvey: Missing required params (vid, cc, rid)")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=missing_params")

        project_number = str(pid).strip()
        vendor_id_raw = str(vid).strip()
        country_code = str(cc).strip().lower()
        respondent_id = str(rid).strip()

        # Try to coerce vendor_id to int; keep as string otherwise
        try:
            vendor_id = int(vendor_id_raw)
        except (ValueError, TypeError):
            vendor_id = vendor_id_raw

        # --- Step 1: Resolve vendor (for later use in /vendor-response) ---
        vendor_doc = await _resolve_vendor_async(vendor_id)
        if not vendor_doc:
            print(f"⚠️ /takesurvey: Vendor {vendor_id} not found — proceeding without vendor record")

        # --- Step 2: Resolve project from study pool ---
        project_doc = await _resolve_live_project_async(project_number)
        if not project_doc:
            print(f"❌ /takesurvey: Live project not found for pid={project_number}")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/survey-error?error=project_not_found&pid={project_number}"
            )

        base_live_link = (
            project_doc.get("liveLink")
            or project_doc.get("clientLink")
            or ""
        ).strip()

        if not base_live_link:
            print(f"❌ /takesurvey: Project {project_number} has no live link configured")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/survey-error?error=no_live_link&pid={project_number}"
            )

        # --- Step 3: Create traffic record ---
        ip_source = "CF-Connecting-IP"
        client_ip = (
            request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.headers.get("X-Real-IP")
            or (request.client.host if request.client else "")
        )
        user_agent = request.headers.get("User-Agent", "")

        traffic_record = {
            "source": "VENDOR_DIRECT",
            "status": "INCOMPLETE",
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
            "respondentId": respondent_id,
            "vendorId": vendor_id,
            "countryCode": country_code,
            "projectNumber": project_number,
            "clientIp": client_ip,
            "ipSource": ip_source,
            "userAgent": user_agent,
            "params": {
                "api": api,
                "pid": project_number,
                "vid": vendor_id_raw,
                "cc": country_code,
                "rid": respondent_id,
            },
        }

        async_url_collection = get_async_url_parameters_collection()
        result = await async_url_collection.insert_one(traffic_record)
        sfwid = str(result.inserted_id)
        print(f"✅ /takesurvey: Traffic record created — SFWID={sfwid}")

        # --- Step 4: Resolve client variable from finance customer record ---
        client_variable = await _resolve_project_client_variable_async(project_doc)
        print(f"   Client variable: '{client_variable or '(auto-detect)'}'")

        # --- Step 5: Build entry link — replace respondent placeholder with SFWID ---
        entry_link = _replace_live_link_respondent(base_live_link, sfwid, client_variable)
        survey_id = project_doc.get("surveyNo") or project_number

        print(f"   Live link (original) : {base_live_link}")
        print(f"   Entry link (SFWID in): {entry_link}")

        # --- Step 6: Update traffic record with allocation info ---
        await async_url_collection.update_one(
            {"_id": result.inserted_id},
            {
                "$set": {
                    "assignedSurveyId": str(survey_id),
                    "redirectUrl": entry_link,
                    "surveySource": "PROJECT",
                    "projectId": str(project_doc.get("_id", "")),
                    "client_variable": client_variable,
                    "updatedAt": datetime.utcnow(),
                }
            },
        )

        print(f"✅ /takesurvey: Redirecting SFWID={sfwid} → {entry_link[:80]}...")
        return RedirectResponse(url=entry_link)

    except Exception as e:
        print(f"❌ /takesurvey error: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=internal")


@router.get("/vendor-response")
async def vendor_response_callback(
    request: Request,
    status: str = Query(..., description="Survey outcome: complete, terminate, quota_full"),
    sfwid: str = Query(None, description="SFWID — our traffic record ID (set as client variable)"),
    rid: str = Query(None, description="Respondent ID (optional fallback)"),
):
    """
    Vendor Traffic Return Redirect Handler

    Called by client when respondent finishes/exits the survey.
    Looks up the traffic record by SFWID, updates status, and redirects
    to the vendor's completeRD or terminateRD URL with the original RID appended.

    URL format (client tredirects):
        Complete : /vendor-response?status=complete&sfwid=<SFWID>
        Terminate: /vendor-response?status=terminate&sfwid=<SFWID>
        Quota    : /vendor-response?status=quota_full&sfwid=<SFWID>
    """
    try:
        print(f"📥 /vendor-response hit: status={status}, sfwid={sfwid}")

        # --- Map status ---
        status_mapping = {
            "complete": "COMPLETE",
            "terminate": "TERMINATED",
            "quota_full": "OVERQUOTA",
            "quotafull": "OVERQUOTA",
        }
        new_status = status_mapping.get((status or "").lower(), "TERMINATED")
        is_complete = new_status == "COMPLETE"

        if not sfwid:
            print("❌ /vendor-response: No sfwid provided")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=missing_sfwid")

        # --- Look up traffic record ---
        async_url_collection = get_async_url_parameters_collection()
        traffic_record = None

        # Primary: by ObjectId
        try:
            traffic_record = await async_url_collection.find_one({"_id": ObjectId(sfwid)})
            if traffic_record:
                print(f"✅ /vendor-response: Found traffic record by ObjectId: {sfwid}")
        except Exception:
            pass

        # Fallback: string _id
        if not traffic_record:
            traffic_record = await async_url_collection.find_one({"_id": sfwid})

        if not traffic_record:
            print(f"⚠️ /vendor-response: Traffic record not found for sfwid={sfwid}")
            return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=not_found")

        vendor_id = traffic_record.get("vendorId")
        respondent_id = traffic_record.get("respondentId", rid or "")
        print(f"   vendorId={vendor_id}, respondentId={respondent_id}, new_status={new_status}")

        # --- Update traffic record ---
        update_fields = {
            "status": new_status,
            "vendorCallbackUrl": str(request.url),
            "updatedAt": datetime.utcnow(),
        }
        if is_complete:
            update_fields["completedAt"] = datetime.utcnow()

        await async_url_collection.update_one(
            {"_id": traffic_record["_id"]},
            {"$set": update_fields},
        )

        # --- Resolve vendor and build redirect URL ---
        fallback_url = f"{FRONTEND_URL}/thankyou" if is_complete else f"{FRONTEND_URL}/survey-error"

        if vendor_id:
            vendor_doc = await _resolve_vendor_async(vendor_id)
            redirect_fields = ["completeRD"] if is_complete else ["terminateRD"]
            redirect_url = _build_vendor_redirect_url(
                vendor_doc, redirect_fields, fallback_url, respondent_id
            )
        else:
            redirect_url = fallback_url
            if respondent_id:
                sep = "&" if "?" in redirect_url else "?"
                redirect_url = f"{redirect_url}{sep}rid={respondent_id}"

        print(f"✅ /vendor-response: {new_status} → {redirect_url}")
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        print(f"❌ /vendor-response error: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url=f"{FRONTEND_URL}/survey-error?error=internal")

