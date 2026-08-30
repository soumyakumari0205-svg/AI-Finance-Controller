"""
Health Score Formula (documented here as per spec).

health_score = (
    match_rate_score × 0.45
  + exception_score  × 0.25
  + age_score        × 0.15
  + quality_score    × 0.15
) × 100

Definitions:
  match_rate_score = matched_count / total_records
  exception_score  = 1 - (open_exception_count / total_records), floored at 0
  age_score        = 1 - (avg_open_exception_age_hours / 48), floored at 0
                     → exceptions under 48h old don't drag the score too hard
  quality_score    = 1 - (records_with_null_description / total_source_records)

A HealthScoreSnapshot is persisted on every reconciliation run so the
frontend can show trend history (not just a live random number).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    BankTransaction,
    ErpInvoice,
    Exception_,
    ExceptionStatus,
    GatewaySettlement,
    HealthScoreSnapshot,
    MatchStatus,
    ReconciliationMatch,
)


async def compute_health_score(db: AsyncSession) -> HealthScoreSnapshot:
    """
    Compute all sub-scores, combine them, persist a snapshot, and return it.
    """
    # ── match_rate_score ─────────────────────────────────────────────────────
    total_matches = (
        await db.execute(select(func.count()).select_from(ReconciliationMatch))
    ).scalar_one()

    matched_count = (
        await db.execute(
            select(func.count()).select_from(ReconciliationMatch).where(
                ReconciliationMatch.status == MatchStatus.matched
            )
        )
    ).scalar_one()

    total_records = max(total_matches, 1)
    match_rate_score = matched_count / total_records

    # ── exception_score ──────────────────────────────────────────────────────
    open_exceptions = (
        await db.execute(
            select(func.count()).select_from(Exception_).where(
                Exception_.status == ExceptionStatus.open
            )
        )
    ).scalar_one()

    exception_score = max(0.0, 1.0 - open_exceptions / total_records)

    # ── age_score ─────────────────────────────────────────────────────────────
    # Average age in hours of all open exceptions
    now = datetime.now(timezone.utc)
    open_exc_rows = (
        await db.execute(
            select(Exception_.created_at).where(Exception_.status == ExceptionStatus.open)
        )
    ).scalars().all()

    if open_exc_rows:
        ages_hours = []
        for created_at in open_exc_rows:
            # Handle both tz-aware and tz-naive timestamps
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_h = (now - created_at).total_seconds() / 3600
            ages_hours.append(age_h)
        avg_age_hours = sum(ages_hours) / len(ages_hours)
    else:
        avg_age_hours = 0.0

    age_score = max(0.0, 1.0 - avg_age_hours / 48.0)

    # ── quality_score ─────────────────────────────────────────────────────────
    # % of bank transactions with a non-null description
    bank_total = (
        await db.execute(select(func.count()).select_from(BankTransaction))
    ).scalar_one()

    bank_missing_desc = (
        await db.execute(
            select(func.count()).select_from(BankTransaction).where(
                BankTransaction.description.is_(None)
            )
        )
    ).scalar_one()

    if bank_total > 0:
        quality_score = 1.0 - (bank_missing_desc / bank_total)
    else:
        quality_score = 1.0

    # ── Composite score ───────────────────────────────────────────────────────
    raw_score = (
        match_rate_score * 0.45
        + exception_score  * 0.25
        + age_score        * 0.15
        + quality_score    * 0.15
    )
    final_score = max(0, min(100, round(raw_score * 100)))

    # ── Persist snapshot ──────────────────────────────────────────────────────
    snapshot = HealthScoreSnapshot(
        score=final_score,
        match_rate=Decimal(str(round(match_rate_score, 4))),
        exception_count=open_exceptions,
        total_records=total_records,
        quality_score=Decimal(str(round(quality_score, 4))),
    )
    db.add(snapshot)
    await db.flush()

    # Audit log
    db.add(AuditLog(
        actor="ai",
        action="health_score:computed",
        entity_type="health_score_snapshot",
        entity_id=str(snapshot.id),
        detail={
            "score": final_score,
            "match_rate_score": round(match_rate_score, 4),
            "exception_score": round(exception_score, 4),
            "age_score": round(age_score, 4),
            "quality_score": round(quality_score, 4),
            "avg_exception_age_hours": round(avg_age_hours, 2),
        },
    ))

    return snapshot
