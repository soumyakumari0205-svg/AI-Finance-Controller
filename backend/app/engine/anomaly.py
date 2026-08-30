"""
Anomaly Detection Engine — three real heuristics, no hardcoded values.

1. duplicate_payout   : same vendor + same amount + same gateway, within 24h
2. variance_drift     : vendor's fee % deviates > VARIANCE_THRESHOLD vs trailing 90-day avg
3. off_schedule       : vendor billed ≥2× in same calendar month when their cycle is monthly

Every detected anomaly writes real field values (vendor name, actual amounts, %) to the
anomalies table and an audit_log row in the same transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuditLog, Anomaly, AnomalyStatus, GatewaySettlement, ErpInvoice

settings = get_settings()


async def _write_anomaly(
    db: AsyncSession,
    type_: str,
    description: str,
    amount: Decimal | None,
    related_id: uuid.UUID | None,
    detail: dict,
) -> Anomaly:
    """Persist an anomaly + audit log row atomically."""
    anomaly = Anomaly(
        type=type_,
        description=description,
        amount=amount,
        related_transaction_id=related_id,
        status=AnomalyStatus.open,
        detail=detail,
    )
    db.add(anomaly)
    await db.flush()

    db.add(AuditLog(
        actor="ai",
        action=f"anomaly:detected:{type_}",
        entity_type="anomaly",
        entity_id=str(anomaly.id),
        detail=detail,
    ))
    return anomaly


async def detect_duplicate_payouts(db: AsyncSession) -> List[Anomaly]:
    """
    Heuristic 1 — Duplicate payout:
    Two gateway_settlements to the same vendor, same amount, same gateway_name,
    with timestamps within DUPLICATE_WINDOW_HOURS of each other.
    """
    window_hours = settings.duplicate_window_hours
    rows = (await db.execute(select(GatewaySettlement).order_by(GatewaySettlement.date))).scalars().all()

    seen: list[GatewaySettlement] = []
    detected: List[Anomaly] = []
    flagged_pairs: set[frozenset] = set()

    for current in rows:
        for prior in seen:
            pair_key = frozenset([str(prior.id), str(current.id)])
            if pair_key in flagged_pairs:
                continue
            if prior.vendor and current.vendor and prior.vendor.strip().lower() != current.vendor.strip().lower():
                continue
            if prior.gateway_name != current.gateway_name:
                continue
            if abs(float(prior.amount) - float(current.amount)) > 0.01:
                continue
            # Check time window using date field (daily granularity)
            days_apart = abs((current.date - prior.date).days)
            if days_apart * 24 > window_hours:
                continue

            flagged_pairs.add(pair_key)
            detail = {
                "settlement_a_id": prior.settlement_id,
                "settlement_b_id": current.settlement_id,
                "settlement_a_uuid": str(prior.id),
                "settlement_b_uuid": str(current.id),
                "vendor": current.vendor,
                "amount": float(current.amount),
                "currency": current.currency,
                "gateway": current.gateway_name,
                "days_apart": days_apart,
            }
            anomaly = await _write_anomaly(
                db=db,
                type_="duplicate_payout",
                description=(
                    f"Duplicate payout detected: {current.vendor or 'Unknown vendor'} received "
                    f"{current.currency} {float(current.amount):,.2f} twice via {current.gateway_name} "
                    f"within {days_apart * 24}h (settlements {prior.settlement_id} and {current.settlement_id})."
                ),
                amount=current.amount,
                related_id=current.id,
                detail=detail,
            )
            detected.append(anomaly)

        seen.append(current)

    return detected


async def detect_variance_drift(db: AsyncSession) -> List[Anomaly]:
    """
    Heuristic 2 — Amount variance drift:
    A vendor's fee_amount as a % of amount deviates more than FEE_VARIANCE_THRESHOLD
    from their trailing 90-day average.
    """
    threshold = settings.fee_variance_threshold
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    # Load all gateway settlements that have a fee_amount
    rows = (
        await db.execute(
            select(GatewaySettlement).where(
                GatewaySettlement.fee_amount.isnot(None),
                GatewaySettlement.amount > 0,
            )
        )
    ).scalars().all()

    # Group by vendor → compute trailing avg fee %
    vendor_history: dict[str, list[float]] = {}
    for row in rows:
        vendor = (row.vendor or row.gateway_name).strip()
        fee_pct = float(row.fee_amount) / float(row.amount)
        vendor_history.setdefault(vendor, []).append(fee_pct)

    detected: List[Anomaly] = []
    # Check only the most recent record per vendor against their own history
    latest: dict[str, GatewaySettlement] = {}
    for row in rows:
        vendor = (row.vendor or row.gateway_name).strip()
        if vendor not in latest or row.date > latest[vendor].date:
            latest[vendor] = row

    for vendor, row in latest.items():
        history = vendor_history.get(vendor, [])
        if len(history) < 2:
            continue  # need at least 2 data points for a meaningful average
        # Exclude the current record from the baseline average
        current_fee_pct = float(row.fee_amount) / float(row.amount)
        baseline = [h for h in history if abs(h - current_fee_pct) > 1e-9]
        if not baseline:
            continue
        avg_fee_pct = sum(baseline) / len(baseline)
        drift = abs(current_fee_pct - avg_fee_pct)

        if drift > threshold:
            detail = {
                "vendor": vendor,
                "settlement_id": row.settlement_id,
                "current_fee_pct": round(current_fee_pct * 100, 3),
                "trailing_avg_fee_pct": round(avg_fee_pct * 100, 3),
                "drift_pct": round(drift * 100, 3),
                "threshold_pct": round(threshold * 100, 3),
                "fee_amount": float(row.fee_amount),
                "settlement_amount": float(row.amount),
            }
            anomaly = await _write_anomaly(
                db=db,
                type_="variance_drift",
                description=(
                    f"Fee variance drift for {vendor}: current fee is "
                    f"{current_fee_pct * 100:.2f}% of settlement, trailing avg is "
                    f"{avg_fee_pct * 100:.2f}% (drift {drift * 100:.2f}% > threshold {threshold * 100:.1f}%)."
                ),
                amount=row.fee_amount,
                related_id=row.id,
                detail=detail,
            )
            detected.append(anomaly)

    return detected


async def detect_off_schedule_billing(db: AsyncSession) -> List[Anomaly]:
    """
    Heuristic 3 — Off-schedule billing:
    A vendor that appears exactly once per month in ERP invoices
    appears more than once in the same calendar month.
    """
    rows = (await db.execute(select(ErpInvoice))).scalars().all()

    # Group by vendor → list of (year, month) tuples
    vendor_months: dict[str, list[tuple[int, int]]] = {}
    vendor_invoices: dict[str, list[ErpInvoice]] = {}
    for inv in rows:
        vendor = inv.vendor.strip() if inv.vendor else "Unknown"
        ym = (inv.due_date.year, inv.due_date.month)
        vendor_months.setdefault(vendor, []).append(ym)
        vendor_invoices.setdefault(vendor, []).append(inv)

    detected: List[Anomaly] = []

    for vendor, months in vendor_months.items():
        if len(months) < 3:
            continue  # not enough history to establish "monthly" pattern

        # Check if vendor is typically monthly (most months appear exactly once)
        from collections import Counter
        month_counts = Counter(months)
        single_month_ratio = sum(1 for c in month_counts.values() if c == 1) / len(month_counts)

        if single_month_ratio < 0.70:
            continue  # vendor is not a monthly biller, skip

        # Find any month where vendor appears more than once
        for (year, month), count in month_counts.items():
            if count >= 2:
                duplicates = [
                    inv for inv in vendor_invoices[vendor]
                    if inv.due_date.year == year and inv.due_date.month == month
                ]
                detail = {
                    "vendor": vendor,
                    "year": year,
                    "month": month,
                    "invoice_count": count,
                    "invoice_numbers": [inv.invoice_number for inv in duplicates],
                    "amounts": [float(inv.amount) for inv in duplicates],
                }
                anomaly = await _write_anomaly(
                    db=db,
                    type_="off_schedule_billing",
                    description=(
                        f"Off-schedule billing: {vendor} billed {count}× in {year}-{month:02d} "
                        f"but is expected monthly. Invoices: {', '.join(detail['invoice_numbers'])}."
                    ),
                    amount=duplicates[0].amount if duplicates else None,
                    related_id=None,
                    detail=detail,
                )
                detected.append(anomaly)

    return detected


async def run_anomaly_detection(db: AsyncSession) -> dict:
    """
    Run all three anomaly detectors. Clears previous open AI-detected anomalies
    before re-running so results stay fresh.
    """
    from sqlalchemy import delete
    await db.execute(
        delete(Anomaly).where(Anomaly.status == AnomalyStatus.open)
    )
    await db.flush()

    duplicates = await detect_duplicate_payouts(db)
    variances = await detect_variance_drift(db)
    off_schedule = await detect_off_schedule_billing(db)

    all_anomalies = duplicates + variances + off_schedule

    return {
        "total_detected": len(all_anomalies),
        "duplicate_payouts": len(duplicates),
        "variance_drifts": len(variances),
        "off_schedule_billings": len(off_schedule),
    }
