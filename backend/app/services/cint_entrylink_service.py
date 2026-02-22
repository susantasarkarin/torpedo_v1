"""
Cint Respondent-Level Entry Link Service

STRICT ISOLATION FROM CPX:
- This service handles ONLY Cint respondent-level entry links
- NO caching of entry links (must be generated per respondent)
- NO project-level entry links
- NO shared code with CPX provider

API Endpoint: POST https://api.samplicio.us/supply/v1/entrylinks
"""

import os
import hmac
import hashlib
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================
# Constants
# ============================================

CINT_API_BASE_URL = "https://api.samplicio.us"
CINT_ENTRYLINKS_ENDPOINT = "/supply/v1/entrylinks"
CINT_SUPPLIER_CODE = "6777"


# ============================================
# Models
# ============================================

class CintEntryLinkRequest(BaseModel):
    """Request body for Cint Entry Link API"""
    survey_id: str = Field(..., description="Cint study/survey ID")
    supplier_code: str = Field(default=CINT_SUPPLIER_CODE, description="Supplier code")
    respondent_id: str = Field(..., description="Internal respondent/user ID")
    secure_hash: str = Field(..., description="HMAC-SHA256 hash for verification")
    return_url: str = Field(..., description="Status callback URL")


class CintEntryLinkResponse(BaseModel):
    """Response from Cint Entry Link API"""
    live_link: str = Field(..., alias="live_link", description="Respondent-specific entry URL")
    survey_id: Optional[str] = None
    respondent_id: Optional[str] = None


class CintStatusCallback(BaseModel):
    """Status callback from Cint after survey completion"""
    status: str = Field(..., description="complete, screenout, quota_full, terminate, overquota")
    respondent_id: str = Field(..., description="Respondent ID we sent")
    survey_id: Optional[str] = None
    transaction_id: Optional[str] = None
    revenue: Optional[float] = None


# ============================================
# Cint Entry Link Service (Isolated)
# ============================================

class CintEntryLinkService:
    """
    Cint Respondent-Level Entry Link Service
    
    CRITICAL RULES:
    - Entry links are created PER RESPONDENT
    - Never pre-generate
    - Never cache globally
    - Never reuse
    
    This is COMPLETELY SEPARATE from CPX logic.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        encryption_key: Optional[str] = None,
        supplier_code: str = CINT_SUPPLIER_CODE,
        base_url: str = CINT_API_BASE_URL,
        status_callback_url: str = "https://torpedo.cogentixresearch.com/api/cint/status",
    ):
        self.api_key = api_key or os.getenv("CINT_API_KEY")
        self.encryption_key = encryption_key or os.getenv("CINT_ENCRYPTION_KEY") or os.getenv("CINT_WEBHOOK_SECRET")
        self.supplier_code = supplier_code
        self.base_url = base_url
        self.status_callback_url = status_callback_url
        
        if not self.api_key:
            raise ValueError("CINT_API_KEY is required")
        if not self.encryption_key:
            raise ValueError("CINT_ENCRYPTION_KEY or CINT_WEBHOOK_SECRET is required for HMAC")
            
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for Cint API"""
        return {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def generate_secure_hash(
        self,
        survey_id: str,
        respondent_id: str,
    ) -> str:
        """
        Generate HMAC-SHA256 secure hash for entry link request.
        
        Hash = HMAC_SHA256(supplier_code + survey_id + respondent_id, encryption_key)
        
        Args:
            survey_id: Cint survey/study ID
            respondent_id: Internal respondent ID
        
        Returns:
            Hex-encoded HMAC-SHA256 hash
        """
        message = f"{self.supplier_code}{survey_id}{respondent_id}"
        
        hash_bytes = hmac.new(
            self.encryption_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hash_bytes
    
    async def create_entry_link(
        self,
        survey_id: str,
        respondent_id: str,
        return_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create respondent-level entry link for Cint survey.
        
        CRITICAL: This creates a FRESH link for EACH respondent.
        Entry links are NOT cached and must NOT be reused.
        
        Args:
            survey_id: Cint survey/study ID (from webhook)
            respondent_id: Internal respondent/user ID
            return_url: Status callback URL (optional, uses default)
        
        Returns:
            Dict with live_link or error
        
        Raises:
            ValueError: If parameters are invalid
        """
        if not survey_id:
            raise ValueError("survey_id is required")
        if not respondent_id:
            raise ValueError("respondent_id is required")
        
        # Task: PID should be the SHA256 hash of respondent id
        hashed_id = hashlib.sha256(respondent_id.encode()).hexdigest()
        
        # Generate secure hash (must use the same ID as in payload)
        secure_hash = self.generate_secure_hash(str(survey_id), hashed_id)
        
        # Build request
        callback_url = return_url or self.status_callback_url
        
        payload = {
            "survey_id": str(survey_id),
            "supplier_code": self.supplier_code,
            "respondent_id": hashed_id,
            "secure_hash": secure_hash,
            "return_url": callback_url,
        }
        
        url = f"{self.base_url}{CINT_ENTRYLINKS_ENDPOINT}"
        
        logger.info(f"[CINT] Creating respondent entry link: survey={survey_id}, respondent={respondent_id}")
        
        try:
            response = await self.client.post(
                url,
                json=payload,
                headers=self._get_headers(),
            )
            
            if response.status_code == 200 or response.status_code == 201:
                data = response.json()
                live_link = data.get("live_link") or data.get("LiveLink")
                
                if live_link:
                    logger.info(f"[CINT] Entry link created for respondent {respondent_id}")
                    return {
                        "success": True,
                        "live_link": live_link,
                        "survey_id": survey_id,
                        "respondent_id": respondent_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    logger.error(f"[CINT] No live_link in response: {data}")
                    return {
                        "success": False,
                        "error": "No live_link in response",
                        "response": data,
                    }
            
            elif response.status_code == 404:
                # Survey not found / inactive
                logger.warning(f"[CINT] Survey {survey_id} not found (404)")
                return {
                    "success": False,
                    "error": "Survey not found or inactive",
                    "status_code": 404,
                    "should_mark_inactive": True,
                }
            
            elif response.status_code == 403:
                # Authentication failure
                logger.error(f"[CINT] Authentication failed (403)")
                return {
                    "success": False,
                    "error": "Authentication failed - check API key",
                    "status_code": 403,
                    "should_alert_admin": True,
                }
            
            elif response.status_code == 408:
                # Timeout - can retry
                logger.warning(f"[CINT] Request timeout (408) for survey {survey_id}")
                return {
                    "success": False,
                    "error": "Request timeout",
                    "status_code": 408,
                    "should_retry": True,
                }
            
            else:
                error_body = response.text
                logger.error(f"[CINT] Entry link failed: {response.status_code} - {error_body}")
                return {
                    "success": False,
                    "error": f"API error: {response.status_code}",
                    "status_code": response.status_code,
                    "response": error_body,
                }
        
        except httpx.TimeoutException as e:
            logger.error(f"[CINT] Timeout creating entry link: {e}")
            return {
                "success": False,
                "error": "Request timeout",
                "should_retry": True,
            }
        
        except Exception as e:
            logger.error(f"[CINT] Error creating entry link: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    def validate_provider(self, provider: str) -> bool:
        """
        Validate that this service is only used for CINT provider.
        
        Hard isolation rule: This service must NEVER be called for CPX surveys.
        
        Args:
            provider: Survey provider enum/string
        
        Returns:
            True if provider is CINT
        
        Raises:
            ValueError: If provider is not CINT
        """
        if provider.upper() != "CINT":
            raise ValueError(f"CintEntryLinkService can only be used for CINT provider, got: {provider}")
        return True


# ============================================
# Status Mapping
# ============================================

CINT_STATUS_MAP = {
    "complete": "COMPLETE",
    "screenout": "SCREEN_OUT",
    "quota_full": "QUOTA_FULL",
    "terminate": "TERMINATED",
    "overquota": "OVERQUOTA",
    "quality_terminate": "QUALITY_TERM",
}


def map_cint_status(cint_status: str) -> str:
    """Map Cint status to internal status"""
    return CINT_STATUS_MAP.get(cint_status.lower(), "UNKNOWN")


def get_internal_action(cint_status: str) -> str:
    """
    Get internal action for Cint status.
    
    complete → CREDIT USER
    screenout → MARK SOFT_FAIL
    quota_full → BLOCK SURVEY
    terminate → MARK FAIL
    """
    actions = {
        "complete": "CREDIT_USER",
        "screenout": "MARK_SOFT_FAIL",
        "quota_full": "BLOCK_SURVEY",
        "terminate": "MARK_FAIL",
        "overquota": "BLOCK_SURVEY",
        "quality_terminate": "MARK_FAIL",
    }
    return actions.get(cint_status.lower(), "UNKNOWN")


# ============================================
# Factory Function
# ============================================

_cint_entrylink_service: Optional[CintEntryLinkService] = None


def get_cint_entrylink_service() -> CintEntryLinkService:
    """
    Get singleton instance of Cint Entry Link Service.
    
    This is ISOLATED from the main CintService to ensure
    no cross-contamination with CPX logic.
    """
    global _cint_entrylink_service
    
    if _cint_entrylink_service is None:
        _cint_entrylink_service = CintEntryLinkService()
    
    return _cint_entrylink_service


async def create_cint_respondent_link(
    survey_id: str,
    respondent_id: str,
    provider: str = "CINT",
) -> Dict[str, Any]:
    """
    Convenience function to create Cint respondent entry link.
    
    Args:
        survey_id: Cint survey ID
        respondent_id: Internal respondent ID
        provider: Must be "CINT"
    
    Returns:
        Dict with live_link or error
    """
    service = get_cint_entrylink_service()
    
    # Hard provider check
    service.validate_provider(provider)
    
    return await service.create_entry_link(survey_id, respondent_id)
