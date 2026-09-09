"""FastAPI entrypoint. Domain routers are mounted as their slices land — see
README.md for what exists so far."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.routers import router as ai_router
from app.auth.routers import router as auth_router
from app.crm.routers import router as crm_router
from app.db import get_database
from app.emailai.routers import router as emailai_router
from app.finance.routers import router as finance_router
from app.governance.routers import router as governance_router
from app.identity.routers import router as identity_router
from app.indexes import ensure_indexes
from app.leadgen.routers import router as leadgen_router
from app.outreach.routers import router as outreach_router
from app.panel.routers import router as panel_router
from app.scheduler.routers import router as scheduler_router
from app.tasks.routers import router as tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Real, enforced idempotency (app.indexes) — never fires against
    # TestClient(app) used directly (no `with` block), which is how every
    # test in this codebase uses it, so this only ever runs against the real
    # deployed database.
    await ensure_indexes(get_database())
    yield


app = FastAPI(title="Torpedo v2", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
app.include_router(identity_router, prefix="/api/v1", tags=["identity"])
app.include_router(leadgen_router, prefix="/api/v1", tags=["leadgen"])
app.include_router(outreach_router, prefix="/api/v1", tags=["outreach"])
app.include_router(finance_router, prefix="/api/v1", tags=["finance"])
app.include_router(panel_router, prefix="/api/v1", tags=["panel"])
app.include_router(crm_router, prefix="/api/v1", tags=["crm"])
app.include_router(ai_router, prefix="/api/v1", tags=["ai"])
app.include_router(emailai_router, prefix="/api/v1", tags=["emailai"])
app.include_router(scheduler_router, prefix="/api/v1", tags=["scheduler"])
app.include_router(governance_router, prefix="/api/v1", tags=["governance"])
app.include_router(tasks_router, prefix="/api/v1", tags=["tasks"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
