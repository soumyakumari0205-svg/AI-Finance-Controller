"""
GET  /api/forecast?scenario=baseline|optimistic|conservative
POST /api/forecast/what-if  — body: { delay_days, unexpected_expense }
"""
from __future__ import annotations
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.database import get_db
from app.engine.forecast import compute_what_if, _height_pct
from app.models import CashForecastScenario, ForecastScenario
from app.schemas import ForecastBar, ForecastOut, WhatIfRequest

router = APIRouter(prefix="/api/forecast", tags=["forecast"])

WEEK_LABELS = ["Aug 26", "Sep 02", "Sep 09", "Sep 16", "Sep 23", "Sep 30"]


@router.get("", response_model=ForecastOut)
async def get_forecast(
    scenario: str = Query("baseline", description="baseline|optimistic|conservative"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        scenario_enum = ForecastScenario(scenario)
    except ValueError:
        scenario_enum = ForecastScenario.baseline

    rows = (
        await db.execute(
            select(CashForecastScenario)
            .where(CashForecastScenario.scenario == scenario_enum)
            .order_by(CashForecastScenario.week_offset)
        )
    ).scalars().all()

    if not rows:
        # No data yet — return empty bars
        return ForecastOut(scenario=scenario, bars=[])

    balances = [float(r.projected_balance) for r in rows]
    heights = _height_pct(balances)

    bars = [
        ForecastBar(
            week_offset=rows[i].week_offset,
            label=WEEK_LABELS[i] if i < len(WEEK_LABELS) else f"Week {i+1}",
            projected_balance=balances[i],
            height_pct=heights[i],
        )
        for i in range(len(rows))
    ]

    return ForecastOut(scenario=scenario, bars=bars)


@router.post("/what-if", response_model=ForecastOut)
async def what_if_forecast(
    body: WhatIfRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Server-side recomputation of the what-if scenario — no client-side fake math."""
    bars_data = await compute_what_if(db, body.delay_days, body.unexpected_expense)

    bars = [
        ForecastBar(
            week_offset=d["week_offset"],
            label=d["label"],
            projected_balance=d["projected_balance"],
            height_pct=d["height_pct"],
        )
        for d in bars_data
    ]

    return ForecastOut(scenario="what-if", bars=bars)
