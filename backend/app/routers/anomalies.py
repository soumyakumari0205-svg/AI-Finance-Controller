"""GET /api/anomalies — List AI-detected anomalies."""
from __future__ import annotations
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.models import Anomaly, AnomalyStatus
from app.schemas import AnomalyOut

router = APIRouter(prefix="/api", tags=["anomalies"])


@router.get("/anomalies", response_model=List[AnomalyOut])
async def list_anomalies(
    status: Optional[str] = Query(None, description="open|dismissed|resolved"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    stmt = select(Anomaly).order_by(Anomaly.detected_at.desc()).limit(limit)
    if status:
        try:
            stmt = stmt.where(Anomaly.status == AnomalyStatus(status))
        except ValueError:
            pass

    rows = (await db.execute(stmt)).scalars().all()

    return [
        AnomalyOut(
            id=str(a.id),
            type=a.type,
            description=a.description,
            amount=f"{float(a.amount):,.2f}" if a.amount else None,
            detected_at=a.detected_at.isoformat(),
            status=a.status.value,
            detail=a.detail,
        )
        for a in rows
    ]
