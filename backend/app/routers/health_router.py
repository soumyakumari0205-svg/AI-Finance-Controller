"""GET /api/health-score — Current health score + recent history."""
from __future__ import annotations
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.models import HealthScoreSnapshot
from app.schemas import HealthScoreOut

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health-score", response_model=HealthScoreOut)
async def get_health_score(
    history_limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Latest snapshot
    latest = (
        await db.execute(
            select(HealthScoreSnapshot).order_by(HealthScoreSnapshot.computed_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if latest is None:
        return HealthScoreOut(
            score=0, match_rate=0.0, exception_count=0, total_records=0,
            quality_score=None, computed_at="N/A", history=[],
        )

    # History for trend
    history_rows = (
        await db.execute(
            select(HealthScoreSnapshot)
            .order_by(HealthScoreSnapshot.computed_at.desc())
            .limit(history_limit)
        )
    ).scalars().all()

    history = [
        {
            "score": h.score,
            "match_rate": float(h.match_rate),
            "computed_at": h.computed_at.isoformat(),
        }
        for h in reversed(history_rows)
    ]

    return HealthScoreOut(
        score=latest.score,
        match_rate=float(latest.match_rate),
        exception_count=latest.exception_count,
        total_records=latest.total_records,
        quality_score=float(latest.quality_score) if latest.quality_score else None,
        computed_at=latest.computed_at.isoformat(),
        history=history,
    )
