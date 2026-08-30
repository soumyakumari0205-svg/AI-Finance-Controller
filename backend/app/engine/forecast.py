"""
Cash Forecasting Engine.

Baseline: Weekly average of bank inflows (last 30 days) projected forward N weeks,
          minus ERP invoices due in each week window.
Optimistic / Conservative: Apply configurable multipliers to receivables and expenses.
What-If: Delay receivables by delayDays and add unexpected_expense to week-1 outflow.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AuditLog, BankTransaction, CashForecastScenario, ErpInvoice, ForecastScenario
)

settings = get_settings()

WEEK_LABELS = ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"]


def _week_start(offset: int) -> date:
    today = date.today()
    return today + timedelta(weeks=offset)


def _height_pct(values: List[float]) -> List[float]:
    """Normalise list of values to 0–100 percentage heights for bar chart display."""
    max_val = max(abs(v) for v in values) if values else 1.0
    if max_val == 0:
        return [50.0] * len(values)
    return [max(10.0, min(98.0, (v / max_val) * 85 + 10)) for v in values]


async def _baseline_weekly_inflow(db: AsyncSession) -> float:
    """Compute average weekly bank inflow over the last 30 days."""
    cutoff = date.today() - timedelta(days=30)
    total_inflow = (
        await db.execute(
            select(func.coalesce(func.sum(BankTransaction.amount), 0)).where(
                BankTransaction.amount > 0,
                BankTransaction.date >= cutoff,
            )
        )
    ).scalar_one()
    return float(total_inflow) / 4.0  # approximate 4 weeks in 30 days


async def _erp_outflow_by_week(db: AsyncSession, n_weeks: int) -> List[float]:
    """Sum ERP invoice amounts due in each of the next n_weeks weeks."""
    result = []
    for offset in range(n_weeks):
        week_start = _week_start(offset)
        week_end = week_start + timedelta(days=6)
        total = (
            await db.execute(
                select(func.coalesce(func.sum(ErpInvoice.amount), 0)).where(
                    ErpInvoice.due_date >= week_start,
                    ErpInvoice.due_date <= week_end,
                )
            )
        ).scalar_one()
        result.append(float(total))
    return result


async def compute_forecast(
    db: AsyncSession,
    scenario: ForecastScenario = ForecastScenario.baseline,
    delay_days: int = 0,
    unexpected_expense: float = 0.0,
) -> List[CashForecastScenario]:
    """
    Compute projected balances for each week offset.
    Multipliers per scenario:
      baseline:     receivable_mult=1.00, expense_mult=1.00
      optimistic:   receivable_mult=1.05, expense_mult=0.95
      conservative: receivable_mult=0.90, expense_mult=1.10
    """
    n = settings.forecast_weeks

    # Determine multipliers
    if scenario == ForecastScenario.optimistic:
        recv_mult = settings.optimistic_receivable_multiplier
        exp_mult = settings.optimistic_expense_multiplier
    elif scenario == ForecastScenario.conservative:
        recv_mult = settings.conservative_receivable_multiplier
        exp_mult = settings.conservative_expense_multiplier
    else:
        recv_mult = 1.0
        exp_mult = 1.0

    weekly_inflow = await _baseline_weekly_inflow(db)
    erp_outflows = await _erp_outflow_by_week(db, n)

    # Apply delay: shift inflows right by delay_days/7 weeks
    delay_weeks = delay_days / 7.0
    rows: List[CashForecastScenario] = []

    running_balance = 0.0
    for offset in range(n):
        # Receivable delayed: reduce inflow proportionally for early weeks
        delay_factor = max(0.0, 1.0 - (delay_weeks / n))
        inflow = weekly_inflow * recv_mult * (delay_factor if offset < int(delay_weeks) + 1 else 1.0)
        outflow = erp_outflows[offset] * exp_mult
        # Add unexpected expense to week 0 only
        if offset == 0:
            outflow += unexpected_expense
        running_balance += inflow - outflow

        row = CashForecastScenario(
            scenario=scenario,
            week_offset=offset,
            projected_balance=Decimal(str(round(running_balance, 2))),
        )
        db.add(row)
        rows.append(row)

    await db.flush()
    return rows


async def run_all_scenarios(db: AsyncSession) -> dict:
    """
    Compute and persist all three scenarios. Called as part of reconciliation job.
    Clears old forecast rows first.
    """
    from sqlalchemy import delete
    await db.execute(delete(CashForecastScenario))
    await db.flush()

    for scenario in ForecastScenario:
        await compute_forecast(db, scenario)

    db.add(AuditLog(
        actor="ai",
        action="forecast:computed_all_scenarios",
        entity_type="cash_forecast_scenarios",
        entity_id=None,
        detail={"scenarios": ["baseline", "optimistic", "conservative"]},
    ))

    return {"status": "ok", "scenarios_computed": 3}


async def compute_what_if(
    db: AsyncSession,
    delay_days: int,
    unexpected_expense: float,
) -> List[dict]:
    """
    Recompute baseline scenario with what-if parameters server-side.
    Returns pre-computed bar data for the frontend.
    """
    n = settings.forecast_weeks
    weekly_inflow = await _baseline_weekly_inflow(db)
    erp_outflows = await _erp_outflow_by_week(db, n)

    delay_weeks = delay_days / 7.0
    balances = []
    running_balance = 0.0

    for offset in range(n):
        delay_factor = max(0.0, 1.0 - (delay_weeks / n)) if delay_weeks > 0 else 1.0
        inflow = weekly_inflow * (delay_factor if offset < int(delay_weeks) + 1 else 1.0)
        outflow = erp_outflows[offset]
        if offset == 0:
            outflow += unexpected_expense
        running_balance += inflow - outflow
        balances.append(running_balance)

    heights = _height_pct(balances)

    return [
        {
            "week_offset": i,
            "label": WEEK_LABELS[i],
            "projected_balance": round(balances[i], 2),
            "height_pct": round(heights[i], 1),
        }
        for i in range(n)
    ]
