"""FastAPI entrypoint. Domain routers are mounted as their slices land — see
README.md for what exists so far."""

from fastapi import FastAPI

from app.ai.routers import router as ai_router
from app.crm.routers import router as crm_router
from app.emailai.routers import router as emailai_router
from app.finance.routers import router as finance_router
from app.identity.routers import router as identity_router
from app.leadgen.routers import router as leadgen_router
from app.outreach.routers import router as outreach_router
from app.panel.routers import router as panel_router
from app.scheduler.routers import router as scheduler_router

app = FastAPI(title="Torpedo v2", version="0.1.0")

app.include_router(identity_router, prefix="/api/v1", tags=["identity"])
app.include_router(leadgen_router, prefix="/api/v1", tags=["leadgen"])
app.include_router(outreach_router, prefix="/api/v1", tags=["outreach"])
app.include_router(finance_router, prefix="/api/v1", tags=["finance"])
app.include_router(panel_router, prefix="/api/v1", tags=["panel"])
app.include_router(crm_router, prefix="/api/v1", tags=["crm"])
app.include_router(ai_router, prefix="/api/v1", tags=["ai"])
app.include_router(emailai_router, prefix="/api/v1", tags=["emailai"])
app.include_router(scheduler_router, prefix="/api/v1", tags=["scheduler"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
