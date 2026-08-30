"""
APScheduler background job — runs reconciliation + anomaly detection + forecasting
every SCHEDULER_INTERVAL_MINUTES minutes so the dashboard is always fresh
without requiring a manual button click.
"""
from __future__ import annotations
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.engine.matcher import run_reconciliation
from app.engine.anomaly import run_anomaly_detection
from app.engine.health import compute_health_score
from app.engine.forecast import run_all_scenarios

log = logging.getLogger("scheduler")
settings = get_settings()

scheduler = AsyncIOScheduler()


async def _reconciliation_job():
    log.info("Scheduled reconciliation job starting …")
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_reconciliation(db)
            await run_anomaly_detection(db)
            await compute_health_score(db)
            await run_all_scenarios(db)
            await db.commit()
            log.info("Scheduled reconciliation complete: %s", summary)
        except Exception as exc:
            await db.rollback()
            log.error("Scheduled reconciliation failed: %s", exc, exc_info=True)


def start_scheduler():
    scheduler.add_job(
        _reconciliation_job,
        trigger=IntervalTrigger(minutes=settings.scheduler_interval_minutes),
        id="reconciliation_job",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    log.info(
        "Scheduler started — reconciliation every %d minutes.",
        settings.scheduler_interval_minutes,
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
