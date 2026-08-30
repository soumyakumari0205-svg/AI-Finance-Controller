"""
GET  /api/exceptions         — List exceptions (filterable by priority)
POST /api/exceptions/{id}/approve — Record human approval (controller only)
POST /api/exceptions/{id}/reject  — Record human rejection (controller only)
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser, require_controller
from app.database import get_db
from app.models import AuditLog, Exception_, ExceptionStatus, MatchedBy, ReconciliationMatch
from app.schemas import ExceptionOut, ExceptionDecision

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


def _format_exception(exc: Exception_) -> ExceptionOut:
    now = datetime.now(timezone.utc)
    created = exc.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_hours = (now - created).total_seconds() / 3600

    return ExceptionOut(
        id=str(exc.id),
        title=exc.title,
        description=exc.description,
        exposure_amount=f"{exc.exposure_currency or 'INR'} {float(exc.exposure_amount or 0):,.2f}" if exc.exposure_amount else None,
        exposure_currency=exc.exposure_currency,
        priority=exc.priority.value,
        status=exc.status.value,
        age_hours=round(age_hours, 1),
        created_at=exc.created_at.isoformat(),
    )


@router.get("", response_model=List[ExceptionOut])
async def list_exceptions(
    priority: Optional[str] = Query(None, description="critical|high|medium|low"),
    status: Optional[str] = Query(None, description="open|approved|rejected|resolved"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    stmt = select(Exception_).order_by(Exception_.created_at.desc()).limit(limit)
    if priority:
        from app.models import ExceptionPriority
        try:
            stmt = stmt.where(Exception_.priority == ExceptionPriority(priority))
        except ValueError:
            raise HTTPException(400, f"Invalid priority: {priority}")
    if status:
        try:
            stmt = stmt.where(Exception_.status == ExceptionStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    rows = (await db.execute(stmt)).scalars().all()
    return [_format_exception(e) for e in rows]


async def _apply_decision(
    exc_id: str,
    decision: ExceptionDecision,
    new_status: ExceptionStatus,
    action: str,
    db: AsyncSession,
    user: CurrentUser,
) -> ExceptionOut:
    try:
        exc_uuid = uuid.UUID(exc_id)
    except ValueError:
        raise HTTPException(400, "Invalid exception ID")

    exc = (
        await db.execute(select(Exception_).where(Exception_.id == exc_uuid))
    ).scalar_one_or_none()

    if exc is None:
        raise HTTPException(404, "Exception not found")
    if exc.status != ExceptionStatus.open:
        raise HTTPException(409, f"Exception is already {exc.status.value}")

    exc.status = new_status
    exc.resolved_by = user.email or user.sub
    exc.resolved_at = datetime.now(timezone.utc)

    # Update related match if present
    if exc.match_id:
        match = (
            await db.execute(
                select(ReconciliationMatch).where(ReconciliationMatch.id == exc.match_id)
            )
        ).scalar_one_or_none()
        if match:
            match.matched_by = MatchedBy.human

    db.add(AuditLog(
        actor=user.email or user.sub,
        action=action,
        entity_type="exception",
        entity_id=exc_id,
        detail={
            "note": decision.note,
            "new_status": new_status.value,
            "resolved_by": exc.resolved_by,
        },
    ))
    await db.flush()
    return _format_exception(exc)


@router.post("/{exc_id}/approve", response_model=ExceptionOut)
async def approve_exception(
    exc_id: str = Path(...),
    body: ExceptionDecision = ExceptionDecision(),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_controller),
):
    return await _apply_decision(exc_id, body, ExceptionStatus.approved, "exception:approved", db, user)


@router.post("/{exc_id}/reject", response_model=ExceptionOut)
async def reject_exception(
    exc_id: str = Path(...),
    body: ExceptionDecision = ExceptionDecision(),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_controller),
):
    return await _apply_decision(exc_id, body, ExceptionStatus.rejected, "exception:rejected", db, user)
