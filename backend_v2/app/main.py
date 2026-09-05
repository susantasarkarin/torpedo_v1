"""FastAPI entrypoint. Domain routers are mounted as their slices land — see
README.md for what exists so far."""

from fastapi import FastAPI

from app.finance.routers import router as finance_router
from app.identity.routers import router as identity_router
from app.leadgen.routers import router as leadgen_router
from app.outreach.routers import router as outreach_router
from app.panel.routers import router as panel_router

app = FastAPI(title="Torpedo v2", version="0.1.0")

app.include_router(identity_router, prefix="/api/v1", tags=["identity"])
app.include_router(leadgen_router, prefix="/api/v1", tags=["leadgen"])
app.include_router(outreach_router, prefix="/api/v1", tags=["outreach"])
app.include_router(finance_router, prefix="/api/v1", tags=["finance"])
app.include_router(panel_router, prefix="/api/v1", tags=["panel"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
