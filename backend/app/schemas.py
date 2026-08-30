"""
Pydantic schemas for API request/response validation.
Decoupled from ORM models so the DB layer can evolve independently.
"""
from __future__ import annotations
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, List

from pydantic import BaseModel, Field, field_validator


# ─── Shared ──────────────────────────────────────────────────────────────────

class OKResponse(BaseModel):
    ok: bool = True
    message: str = ""


# ─── Ingest schemas ───────────────────────────────────────────────────────────

class BankTransactionIn(BaseModel):
    external_ref: str
    amount: Decimal
    currency: str = "INR"
    date: date
    description: Optional[str] = None
    raw_payload: Optional[dict] = None


class ErpInvoiceIn(BaseModel):
    invoice_number: str
    amount: Decimal
    currency: str = "INR"
    due_date: date
    vendor: str
    status: str = "open"
    raw_payload: Optional[dict] = None


class GatewaySettlementIn(BaseModel):
    settlement_id: str
    amount: Decimal
    currency: str = "INR"
    date: date
    gateway_name: str
    vendor: Optional[str] = None
    fee_amount: Optional[Decimal] = None
    raw_payload: Optional[dict] = None


class IngestBatch(BaseModel):
    records: List[Any]  # discriminated by endpoint path /api/ingest/{source}


class IngestResult(BaseModel):
    inserted: int
    skipped: int
    errors: List[str] = []


# ─── Reconcile schemas ────────────────────────────────────────────────────────

class ReconcileRunResult(BaseModel):
    total_processed: int
    matched: int
    review: int
    exceptions: int
    match_rate: float
    health_score: int
    run_id: str


class ReconciliationRecord(BaseModel):
    """Flattened record returned to the frontend table."""
    id: str
    date: str
    source: str
    description: str
    amount: str
    matched_record: str
    status: str          # "Matched" | "Review Needed" | "Exception"
    confidence: str      # "94.2%"
    match_reason: Optional[str] = None
    raw_id: str          # UUID of the source row


# ─── Exception schemas ────────────────────────────────────────────────────────

class ExceptionOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    exposure_amount: Optional[str]
    exposure_currency: Optional[str]
    priority: str
    status: str
    age_hours: float
    created_at: str


class ExceptionDecision(BaseModel):
    note: Optional[str] = None


# ─── Health score ─────────────────────────────────────────────────────────────

class HealthScoreOut(BaseModel):
    score: int
    match_rate: float
    exception_count: int
    total_records: int
    quality_score: Optional[float]
    computed_at: str
    history: List[dict] = []


# ─── Anomaly schemas ─────────────────────────────────────────────────────────

class AnomalyOut(BaseModel):
    id: str
    type: str
    description: str
    amount: Optional[str]
    detected_at: str
    status: str
    detail: Optional[dict]


# ─── Forecast schemas ─────────────────────────────────────────────────────────

class ForecastBar(BaseModel):
    week_offset: int
    label: str
    projected_balance: float
    height_pct: float     # 0–100, pre-computed for CSS


class ForecastOut(BaseModel):
    scenario: str
    bars: List[ForecastBar]


class WhatIfRequest(BaseModel):
    delay_days: int = Field(default=0, ge=0, le=14)
    unexpected_expense: float = Field(default=0.0, ge=0, le=100_000)


# ─── Audit log ────────────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    actor: str
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    detail: Optional[dict]
    created_at: str


# ─── KPI dashboard ────────────────────────────────────────────────────────────

class KPIOut(BaseModel):
    total_processed: int
    match_rate: float
    auto_resolved: int
    exception_count: int
    explainability_score: float   # % of matches with non-null match_reason
