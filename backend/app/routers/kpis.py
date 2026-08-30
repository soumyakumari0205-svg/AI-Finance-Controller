"""
GET /api/kpis — Dashboard KPI summary.
Explainability score = % of matches with a non-null match_reason.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.models import (
    BankTransaction, ErpInvoice, Exception_, ExceptionStatus,
    GatewaySettlement, MatchStatus, ReconciliationMatch,
)
from app.schemas import KPIOut

router = APIRouter(prefix="/api", tags=["kpis"])


@router.get("/kpis", response_model=KPIOut)
async def get_kpis(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Total source records (all three tables)
    bank_count = (await db.execute(select(func.count()).select_from(BankTransaction))).scalar_one()
    erp_count = (await db.execute(select(func.count()).select_from(ErpInvoice))).scalar_one()
    gw_count = (await db.execute(select(func.count()).select_from(GatewaySettlement))).scalar_one()
    total_processed = bank_count + erp_count + gw_count

    # Match stats from reconciliation_matches
    total_matches = (await db.execute(select(func.count()).select_from(ReconciliationMatch))).scalar_one()
    matched_count = (
        await db.execute(
            select(func.count()).select_from(ReconciliationMatch).where(
                ReconciliationMatch.status == MatchStatus.matched
            )
        )
    ).scalar_one()

    match_rate = matched_count / total_matches if total_matches > 0 else 0.0

    # Auto-resolved = high-confidence (>=90%) matched records
    auto_resolved = (
        await db.execute(
            select(func.count()).select_from(ReconciliationMatch).where(
                ReconciliationMatch.status == MatchStatus.matched,
                ReconciliationMatch.confidence_score >= 90,
            )
        )
    ).scalar_one()

    # Open exceptions
    exception_count = (
        await db.execute(
            select(func.count()).select_from(Exception_).where(
                Exception_.status == ExceptionStatus.open
            )
        )
    ).scalar_one()

    # Explainability = % of matches where match_reason is not null
    with_reason = (
        await db.execute(
            select(func.count()).select_from(ReconciliationMatch).where(
                ReconciliationMatch.match_reason.isnot(None)
            )
        )
    ).scalar_one()
    explainability = (with_reason / total_matches * 100) if total_matches > 0 else 0.0

    return KPIOut(
        total_processed=total_processed,
        match_rate=round(match_rate * 100, 1),
        auto_resolved=auto_resolved,
        exception_count=exception_count,
        explainability_score=round(explainability, 1),
    )
