"""
HTTP surface for the AI Gateway. Deliberately minimal in this slice: a status read
and a kill switch. Wiring `DecisionEngine.decide()` into real callers (email
classification, survey ranking, AR follow-up, ...) is Slices 12-16's job — those
domains own the context each decision needs, this package only owns the plumbing to
reach a model at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.ai.gpu_broker import GpuBroker
from app.auth.dependencies import require_permission
from app.db import get_database
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import AI_ADMIN, AI_READ

router = APIRouter()


def get_gpu_broker() -> GpuBroker:
    return GpuBroker(get_database()["ai_gpu_leases"])


@router.get("/ai/gpu/status")
async def gpu_status(identity: ResolvedIdentity = Depends(require_permission(AI_READ)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    return await broker.status()


@router.post("/ai/gpu/shutdown")
async def gpu_shutdown_now(identity: ResolvedIdentity = Depends(require_permission(AI_ADMIN)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    return await broker.shutdown_now()
