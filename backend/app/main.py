"""
FastAPI application entry point.
- Registers all routers
- Starts/stops the APScheduler background job
- Creates all DB tables on startup (dev convenience; use migrations in prod)
- Configures CORS
"""
from __future__ import annotations
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers import (
    audit, anomalies, exceptions, forecast_router,
    health_router, ingest, kpis, reconcile, seed,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

settings = get_settings()

app = FastAPI(
    title="AI Finance Controller API",
    version="1.0.0",
    description="Real backend for the AI Finance Controller reconciliation dashboard.",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(seed.router)
app.include_router(ingest.router)
app.include_router(reconcile.router)
app.include_router(exceptions.router)
app.include_router(health_router.router)
app.include_router(anomalies.router)
app.include_router(forecast_router.router)
app.include_router(audit.router)
app.include_router(kpis.router)


# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    # Auto-create tables (dev convenience — use SQL migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables ensured.")
    start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()
    await engine.dispose()


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "AI Finance Controller API"}
