"""GET /api/audit-log — Immutable audit trail (read-only)."""
from __future__ import annotations
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.models import AuditLog
from app.schemas import AuditLogEntry

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit-log", response_model=List[AuditLogEntry])
async def get_audit_log(
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        )
    ).scalars().all()

    return [
        AuditLogEntry(
            id=row.id,
            actor=row.actor,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            detail=row.detail,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
