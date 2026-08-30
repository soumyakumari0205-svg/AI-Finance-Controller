"""
Unit tests for the anomaly detection engine.
Seeds minimal DB data and asserts each heuristic fires correctly.
"""
import pytest
import pytest_asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.engine.anomaly import (
    detect_duplicate_payouts,
    detect_variance_drift,
    detect_off_schedule_billing,
)
from app.models import GatewaySettlement, ErpInvoice


# ─── Duplicate payout ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_duplicate_payout(db):
    """Two settlements to same vendor, same amount, same gateway, same date → anomaly detected."""
    vendor = "Stripe Inc"
    amount = Decimal("12400.00")
    today = date.today()

    db.add(GatewaySettlement(
        settlement_id="GW-001",
        amount=amount,
        currency="INR",
        date=today,
        gateway_name="Stripe",
        vendor=vendor,
        fee_amount=Decimal("372.00"),
    ))
    db.add(GatewaySettlement(
        settlement_id="GW-002",
        amount=amount,
        currency="INR",
        date=today,
        gateway_name="Stripe",
        vendor=vendor,
        fee_amount=Decimal("372.00"),
    ))
    await db.flush()

    detected = await detect_duplicate_payouts(db)
    assert len(detected) >= 1
    assert detected[0].type == "duplicate_payout"
    assert float(detected[0].amount) == float(amount)
    assert "Stripe Inc" in detected[0].description
    assert "GW-001" in str(detected[0].detail) or "GW-002" in str(detected[0].detail)


@pytest.mark.asyncio
async def test_no_duplicate_payout_different_vendor(db):
    """Different vendors → no duplicate payout anomaly."""
    today = date.today()
    db.add(GatewaySettlement(
        settlement_id="GW-A", amount=Decimal("5000"), currency="INR",
        date=today, gateway_name="Stripe", vendor="VendorA",
    ))
    db.add(GatewaySettlement(
        settlement_id="GW-B", amount=Decimal("5000"), currency="INR",
        date=today, gateway_name="Stripe", vendor="VendorB",
    ))
    await db.flush()

    detected = await detect_duplicate_payouts(db)
    assert len(detected) == 0


@pytest.mark.asyncio
async def test_no_duplicate_payout_different_amount(db):
    """Same vendor, different amounts → not a duplicate."""
    today = date.today()
    for sid, amt in [("GW-C", "5000"), ("GW-D", "6000")]:
        db.add(GatewaySettlement(
            settlement_id=sid, amount=Decimal(amt), currency="INR",
            date=today, gateway_name="Stripe", vendor="VendorX",
        ))
    await db.flush()

    detected = await detect_duplicate_payouts(db)
    assert len(detected) == 0


# ─── Variance drift ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_variance_drift(db):
    """Historical fee rate ~2%, current rate 7% → drift exceeds threshold."""
    vendor = "Cloudflare Inc"
    today = date.today()

    # Build history: 5 settlements at ~2% fee
    for i in range(5):
        amt = Decimal("10000.00")
        fee = Decimal("200.00")  # 2%
        db.add(GatewaySettlement(
            settlement_id=f"HIST-{i}",
            amount=amt, currency="INR",
            date=today - timedelta(days=i + 5),
            gateway_name="Stripe",
            vendor=vendor,
            fee_amount=fee,
        ))

    # Latest settlement: 7% fee (significant drift)
    db.add(GatewaySettlement(
        settlement_id="LATEST-HIGH-FEE",
        amount=Decimal("10000.00"), currency="INR",
        date=today,
        gateway_name="Stripe",
        vendor=vendor,
        fee_amount=Decimal("700.00"),  # 7%
    ))
    await db.flush()

    detected = await detect_variance_drift(db)
    assert len(detected) >= 1
    assert detected[0].type == "variance_drift"
    assert "Cloudflare Inc" in detected[0].description
    # The actual drift % should be in the detail
    assert detected[0].detail["drift_pct"] > 3.0


@pytest.mark.asyncio
async def test_no_variance_drift_within_threshold(db):
    """Fee rate stable within 1% → no drift anomaly."""
    vendor = "StableVendor"
    today = date.today()

    for i in range(5):
        db.add(GatewaySettlement(
            settlement_id=f"STABLE-{i}",
            amount=Decimal("10000.00"), currency="INR",
            date=today - timedelta(days=i + 1),
            gateway_name="Stripe", vendor=vendor,
            fee_amount=Decimal("250.00"),  # 2.5% each time
        ))
    # Latest: 2.6% — within threshold
    db.add(GatewaySettlement(
        settlement_id="STABLE-LATEST",
        amount=Decimal("10000.00"), currency="INR",
        date=today,
        gateway_name="Stripe", vendor=vendor,
        fee_amount=Decimal("260.00"),
    ))
    await db.flush()

    detected = await detect_variance_drift(db)
    assert len(detected) == 0


# ─── Off-schedule billing ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_off_schedule_billing(db):
    """Vendor billed monthly for 3 months, then twice in same month → anomaly."""
    vendor = "AWS Cloud Services"
    # Three months with single invoice each (establishes monthly pattern)
    for month in [5, 6, 7]:
        db.add(ErpInvoice(
            invoice_number=f"INV-{vendor}-{month}",
            amount=Decimal("14250.00"), currency="INR",
            due_date=date(2026, month, 15),
            vendor=vendor, status="open",
        ))
    # Same month (August) billed twice — anomalous
    db.add(ErpInvoice(
        invoice_number="INV-AWS-8A",
        amount=Decimal("14250.00"), currency="INR",
        due_date=date(2026, 8, 5),
        vendor=vendor, status="open",
    ))
    db.add(ErpInvoice(
        invoice_number="INV-AWS-8B",
        amount=Decimal("14250.00"), currency="INR",
        due_date=date(2026, 8, 20),
        vendor=vendor, status="open",
    ))
    await db.flush()

    detected = await detect_off_schedule_billing(db)
    assert len(detected) >= 1
    assert detected[0].type == "off_schedule_billing"
    assert "AWS Cloud Services" in detected[0].description
    assert detected[0].detail["invoice_count"] >= 2


@pytest.mark.asyncio
async def test_no_off_schedule_for_irregular_vendor(db):
    """Vendor billed irregularly doesn't trigger off-schedule."""
    vendor = "IrregularVendor"
    for month in [1, 3, 6, 8]:  # non-monthly pattern
        db.add(ErpInvoice(
            invoice_number=f"IRR-{month}",
            amount=Decimal("5000.00"), currency="INR",
            due_date=date(2026, month, 10),
            vendor=vendor, status="open",
        ))
    await db.flush()

    detected = await detect_off_schedule_billing(db)
    # Should not flag this vendor since they're not a monthly biller
    vendor_anoms = [d for d in detected if vendor in d.description]
    assert len(vendor_anoms) == 0
