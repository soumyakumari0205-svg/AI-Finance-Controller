"""
POST /api/seed — DEV ONLY. Gated by ENABLE_SEED_ENDPOINT env flag.
Generates realistic synthetic records across all three source tables.
Never callable in production.
"""
from __future__ import annotations
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.config import get_settings
from app.database import get_db
from app.models import (
    AuditLog, BankTransaction, ErpInvoice, GatewaySettlement
)

router = APIRouter(prefix="/api", tags=["seed"])
settings = get_settings()
fake = Faker()

VENDORS = [
    "Stripe Inc", "AWS Cloud Services", "Acme Corp", "CloudFlare Inc",
    "Salesforce Inc", "HubSpot Technologies", "Plaid Technologies",
    "Twilio Inc", "SendGrid", "Datadog Inc", "MongoDB Atlas",
    "Vercel Inc", "Netlify", "GitHub Inc", "Atlassian Corp",
]
GATEWAYS = ["Stripe", "Razorpay", "PayU", "Cashfree", "PayPal"]
CURRENCIES = ["INR", "INR", "INR", "USD", "USD"]  # INR-weighted


def _rand_date(days_back: int = 60) -> date:
    return date.today() - timedelta(days=random.randint(0, days_back))


def _rand_amount(low: float = 500, high: float = 150_000) -> Decimal:
    return Decimal(str(round(random.uniform(low, high), 2)))


@router.post("/seed")
async def seed_data(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if not settings.enable_seed_endpoint:
        raise HTTPException(
            status_code=403,
            detail="Seed endpoint is disabled. Set ENABLE_SEED_ENDPOINT=true in dev only.",
        )

    # Clear existing source data
    from sqlalchemy import delete, text
    for table in [
        "reconciliation_matches", "exceptions", "anomalies",
        "cash_forecast_scenarios", "health_score_snapshots",
        "gateway_settlements", "erp_invoices", "bank_transactions",
    ]:
        await db.execute(text(f"DELETE FROM {table}"))
    await db.flush()

    bank_rows = []
    erp_rows = []
    gw_rows = []

    # Generate 20 bank transactions
    for i in range(1, 21):
        vendor = random.choice(VENDORS)
        amount = _rand_amount()
        txn_date = _rand_date(45)
        currency = random.choice(CURRENCIES)
        row = BankTransaction(
            external_ref=f"TXN-{2000 + i}",
            amount=amount,
            currency=currency,
            date=txn_date,
            description=f"{vendor} payment",
            raw_payload={"source": "bank_feed", "vendor": vendor},
        )
        db.add(row)
        bank_rows.append((row, vendor, amount, txn_date, currency))

    await db.flush()

    # Generate matching ERP invoices for ~75% of bank transactions (creates real matches)
    for idx, (bank_row, vendor, amount, txn_date, currency) in enumerate(bank_rows):
        if idx % 4 == 3:
            continue  # ~25% left unmatched → will become exceptions
        # Slight amount variance for fuzzy matching tests
        erp_amount = amount + Decimal(str(round(random.uniform(-50, 50), 2)))
        # Date close but not identical (triggers fuzzy date scoring)
        erp_date = txn_date + timedelta(days=random.randint(-2, 2))
        inv_num = f"INV-{9000 + idx}"
        row = ErpInvoice(
            invoice_number=inv_num,
            amount=erp_amount,
            currency=currency,
            due_date=erp_date,
            vendor=vendor,
            status="open",
            raw_payload={"po_ref": bank_row.external_ref, "vendor": vendor},
        )
        db.add(row)
        erp_rows.append(row)

    # Generate 15 gateway settlements
    for i in range(1, 16):
        vendor = random.choice(VENDORS)
        amount = _rand_amount(1000, 80_000)
        gw_date = _rand_date(30)
        currency = random.choice(CURRENCIES)
        fee = Decimal(str(round(float(amount) * random.uniform(0.015, 0.035), 2)))
        row = GatewaySettlement(
            settlement_id=f"GW-{3000 + i}",
            amount=amount,
            currency=currency,
            date=gw_date,
            gateway_name=random.choice(GATEWAYS),
            vendor=vendor,
            fee_amount=fee,
            raw_payload={"payout_ref": f"PO-{i}", "vendor": vendor},
        )
        db.add(row)
        gw_rows.append(row)

    # Add a deliberate duplicate payout (same vendor, amount, gateway, same date)
    if gw_rows:
        original = gw_rows[0]
        db.add(GatewaySettlement(
            settlement_id=f"GW-DUPE-{original.settlement_id}",
            amount=original.amount,
            currency=original.currency,
            date=original.date,
            gateway_name=original.gateway_name,
            vendor=original.vendor,
            fee_amount=original.fee_amount,
            raw_payload={"note": "DUPLICATE_TEST"},
        ))

    db.add(AuditLog(
        actor=user.sub,
        action="seed:created",
        entity_type="seed",
        entity_id=None,
        detail={
            "bank_transactions": len(bank_rows),
            "erp_invoices": len(erp_rows),
            "gateway_settlements": len(gw_rows) + 1,
        },
    ))

    return {
        "ok": True,
        "bank_transactions": len(bank_rows),
        "erp_invoices": len(erp_rows),
        "gateway_settlements": len(gw_rows) + 1,
    }
