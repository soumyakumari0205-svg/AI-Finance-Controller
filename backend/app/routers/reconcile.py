"""
POST /api/reconcile/run  — Trigger a full reconciliation pass.
GET  /api/reconcile/records — Paginated, filterable records for the frontend table.
"""
from __future__ import annotations
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.engine.anomaly import run_anomaly_detection
from app.engine.forecast import run_all_scenarios
from app.engine.health import compute_health_score
from app.engine.matcher import run_reconciliation
from app.models import (
    AuditLog, BankTransaction, ErpInvoice, GatewaySettlement,
    MatchStatus, ReconciliationMatch,
)
from app.schemas import ReconcileRunResult, ReconciliationRecord

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])


@router.post("/run", response_model=ReconcileRunResult)
async def trigger_reconciliation(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Run the full reconciliation pipeline synchronously and return the summary."""
    summary = await run_reconciliation(db)
    await run_anomaly_detection(db)
    snapshot = await compute_health_score(db)
    await run_all_scenarios(db)

    db.add(AuditLog(
        actor=user.sub,
        action="reconcile:manual_run",
        entity_type="reconciliation",
        entity_id=None,
        detail=summary,
    ))

    run_id = str(uuid.uuid4())
    return ReconcileRunResult(
        total_processed=summary["total_processed"],
        matched=summary["matched"],
        review=summary["review"],
        exceptions=summary["exceptions"],
        match_rate=summary["match_rate"],
        health_score=snapshot.score,
        run_id=run_id,
    )


@router.get("/records", response_model=List[ReconciliationRecord])
async def get_records(
    status: Optional[str] = Query(None, description="matched|review|exception"),
    source: Optional[str] = Query(None, description="bank|erp|gateway"),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Returns a flat list of reconciliation records for the frontend table.
    Each row includes the source record's metadata + the match result.
    """
    # Load matches with their source records
    stmt = select(ReconciliationMatch).limit(limit).offset(offset)
    if status:
        try:
            status_enum = MatchStatus(status.lower())
            stmt = stmt.where(ReconciliationMatch.status == status_enum)
        except ValueError:
            pass

    matches = (await db.execute(stmt)).scalars().all()

    results: List[ReconciliationRecord] = []

    for match in matches:
        # Load source A record
        src_type = match.source_a_type
        if src_type == "bank":
            src = (await db.execute(
                select(BankTransaction).where(BankTransaction.id == match.source_a_id)
            )).scalar_one_or_none()
            if not src:
                continue
            description = src.description or "Bank Transaction"
            ref = src.external_ref
            src_date = src.date
            amount_val = src.amount
            currency = src.currency
        elif src_type == "erp":
            src = (await db.execute(
                select(ErpInvoice).where(ErpInvoice.id == match.source_a_id)
            )).scalar_one_or_none()
            if not src:
                continue
            description = src.vendor or "ERP Invoice"
            ref = src.invoice_number
            src_date = src.due_date
            amount_val = src.amount
            currency = src.currency
        elif src_type == "gateway":
            src = (await db.execute(
                select(GatewaySettlement).where(GatewaySettlement.id == match.source_a_id)
            )).scalar_one_or_none()
            if not src:
                continue
            description = src.vendor or src.gateway_name
            ref = src.settlement_id
            src_date = src.date
            amount_val = src.amount
            currency = src.currency
        else:
            continue

        # Apply search filter
        if search:
            q = search.lower()
            if q not in ref.lower() and q not in description.lower():
                continue

        # Apply source filter
        if source and src_type != source.lower():
            continue

        # Map status to display string
        status_map = {
            MatchStatus.matched: "Matched",
            MatchStatus.review: "Review Needed",
            MatchStatus.exception: "Exception",
        }

        # Format amount
        if currency == "INR":
            amount_str = f"₹{float(amount_val):,.2f}"
        else:
            amount_str = f"${float(amount_val):,.2f}"

        # Matched record label: look up source_b
        if match.status == MatchStatus.exception:
            matched_label = "Unmatched"
        else:
            b_type = match.source_b_type
            if b_type == "erp":
                b = (await db.execute(
                    select(ErpInvoice).where(ErpInvoice.id == match.source_b_id)
                )).scalar_one_or_none()
                matched_label = b.invoice_number if b else "Unknown"
            elif b_type == "gateway":
                b = (await db.execute(
                    select(GatewaySettlement).where(GatewaySettlement.id == match.source_b_id)
                )).scalar_one_or_none()
                matched_label = b.settlement_id if b else "Unknown"
            else:
                matched_label = str(match.source_b_id)[:8]

        results.append(ReconciliationRecord(
            id=ref,
            date=str(src_date),
            source=src_type.capitalize(),
            description=description,
            amount=amount_str,
            matched_record=matched_label,
            status=status_map.get(match.status, match.status.value),
            confidence=f"{float(match.confidence_score):.1f}%",
            match_reason=match.match_reason,
            raw_id=str(match.source_a_id),
        ))

    return results
