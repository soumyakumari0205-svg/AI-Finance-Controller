"""
POST /api/ingest/{source}  — Accept a batch of bank / ERP / gateway records.
Idempotent: skips rows with duplicate external references.
"""
from __future__ import annotations
from typing import List, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.models import AuditLog, BankTransaction, ErpInvoice, GatewaySettlement
from app.schemas import (
    BankTransactionIn, ErpInvoiceIn, GatewaySettlementIn, IngestResult
)

router = APIRouter(prefix="/api", tags=["ingest"])

SOURCE_TYPES = {"bank", "erp", "gateway"}


@router.post("/ingest/{source}", response_model=IngestResult)
async def ingest_records(
    source: str = Path(..., description="One of: bank, erp, gateway"),
    payload: dict = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if source not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Use: bank, erp, gateway")

    records: List[Any] = (payload or {}).get("records", [])
    inserted = 0
    skipped = 0
    errors: List[str] = []

    for raw in records:
        try:
            if source == "bank":
                data = BankTransactionIn(**raw)
                # Idempotency check
                exists = (
                    await db.execute(
                        select(BankTransaction).where(BankTransaction.external_ref == data.external_ref)
                    )
                ).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
                db.add(BankTransaction(**data.model_dump()))

            elif source == "erp":
                data = ErpInvoiceIn(**raw)
                exists = (
                    await db.execute(
                        select(ErpInvoice).where(ErpInvoice.invoice_number == data.invoice_number)
                    )
                ).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
                db.add(ErpInvoice(**data.model_dump()))

            elif source == "gateway":
                data = GatewaySettlementIn(**raw)
                exists = (
                    await db.execute(
                        select(GatewaySettlement).where(
                            GatewaySettlement.settlement_id == data.settlement_id
                        )
                    )
                ).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
                db.add(GatewaySettlement(**data.model_dump()))

            inserted += 1

        except Exception as exc:
            errors.append(str(exc))

    await db.flush()
    db.add(AuditLog(
        actor=user.sub,
        action=f"ingest:{source}",
        entity_type=source,
        entity_id=None,
        detail={"inserted": inserted, "skipped": skipped, "errors": len(errors)},
    ))

    return IngestResult(inserted=inserted, skipped=skipped, errors=errors)
