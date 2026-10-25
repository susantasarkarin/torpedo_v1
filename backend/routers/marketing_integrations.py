"""Admin > Marketing > Integrations (MARKETING_PLAN working rules: "Secrets").

GET shows which credentials are set (never their values). PUT / DELETE need
the approve capability and are audit-logged. Secrets are encrypted at rest
by marketing.credentials.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.security import require
from marketing import credentials
from session_state import verify_session

router = APIRouter(prefix="/api/marketing/integrations", tags=["Marketing"])
require_approve = require("approve")


@router.get("")
async def list_integrations(user: str = Depends(verify_session)) -> Dict[str, Any]:
    return credentials.status()


@router.put("/{platform}")
async def save_integration(platform: str, body: Dict[str, Any] = Body(...), user: str = Depends(require_approve)):
    try:
        return credentials.save(platform, secrets=body.get("secrets"), settings=body.get("settings"), actor=user)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except credentials.CredentialsUnavailable as e:
        raise HTTPException(503, str(e))


@router.delete("/{platform}")
async def clear_integration(platform: str, field: Optional[str] = Query(None), user: str = Depends(require_approve)):
    try:
        return credentials.clear(platform, field, actor=user)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, f"unknown secret field {e}")
