"""
HTTP surface for the AI Gateway, plus (Slice 18) one cross-cutting diagnostics
endpoint. `/ai/gpu/status` and `/ai/gpu/shutdown` predate this; `/integrations/status`
is new — a single read-only view of which external boundaries are actually
configured versus credential-blocked, for every `Protocol` this codebase has built
so far. It reports presence/absence of a credential, never the credential itself,
and never claims a boundary is "connected" merely because code exists behind it —
"configured" here means "the env var this provider's `api_key()`-style guard checks
is non-empty," nothing more.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from app.ai.gpu_broker import GpuBroker
from app.auth.dependencies import require_permission
from app.db import get_database
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import AI_ADMIN, AI_READ, INTEGRATIONS_STATUS_READ

router = APIRouter()


def get_gpu_broker() -> GpuBroker:
    return GpuBroker(get_database()["ai_gpu_leases"])


@router.get("/ai/gpu/status")
async def gpu_status(identity: ResolvedIdentity = Depends(require_permission(AI_READ)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    return await broker.status()


@router.post("/ai/gpu/shutdown")
async def gpu_shutdown_now(identity: ResolvedIdentity = Depends(require_permission(AI_ADMIN)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    return await broker.shutdown_now()


def _configured(*env_vars: str) -> str:
    return "CONFIGURED" if all((os.getenv(v) or "").strip() for v in env_vars) else "NOT_CONFIGURED"


@router.get("/integrations/status")
async def integrations_status(identity: ResolvedIdentity = Depends(require_permission(INTEGRATIONS_STATUS_READ)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    gpu_broker_status = await broker.status()
    return {
        "ai_gateway": "READY",  # the gateway code path itself always exists; whether a model answers depends on the GPU broker below
        "gpu_broker": "READY" if gpu_broker_status["state"] == "ready" else ("DISABLED" if not (os.getenv("GPU_BROKER_ENABLED") or "").strip() else "UNAVAILABLE"),
        "gpu_credential": _configured("RUNPOD_API_KEY"),
        "gsc": "NOT_CONFIGURED",  # no GSC credential scheme has been designed yet — see app.leadgen.gsc's module docstring
        "cint": _configured("CINT_API_KEY", "CINT_SUPPLIER_CODE"),
        "email_send_provider": "NOT_CONFIGURED",  # app.outreach.providers.SendProvider — StubSendProvider is the only implementation that exists
        "email_ingestion_provider": "NOT_CONFIGURED",  # app.emailai.providers.EmailIngestionProvider — no implementation exists yet, stub or real
    }
