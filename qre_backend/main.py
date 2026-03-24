"""
FastAPI entry point for QRE Health Survey backend.
Supports high-concurrency via async I/O + Motor (async MongoDB driver).
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME, CORS_ORIGINS
from services.quota_service import ensure_quota_doc

# Module-level db reference (set during lifespan)
db = None
_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, _client
    _client = AsyncIOMotorClient(MONGO_URI, maxPoolSize=100)
    db = _client[DB_NAME]
    # Ensure indexes for concurrent performance
    await db.respondents.create_index("status")
    await db.respondents.create_index("started_at")
    await db.respondents.create_index("ip_address")
    await db.respondents.create_index([("ip_address", 1), ("ip_locked", 1)])
    await ensure_quota_doc(db)
    yield
    _client.close()


app = FastAPI(
    title="QRE Health Consumer Survey API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from routes.survey import router as survey_router
from routes.admin import router as admin_router
from routes.studies import router as studies_router
from routes.auth import router as auth_router

app.include_router(auth_router)
app.include_router(survey_router)
app.include_router(admin_router)
app.include_router(studies_router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "QRE Health Consumer Survey API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
