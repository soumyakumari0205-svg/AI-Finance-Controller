"""
SQLAlchemy ORM models for all 9 tables.
The audit_log table intentionally has NO update_at column — rows are immutable by design.
DB-level immutability is enforced via the migration 003_rls_audit_immutability.sql.
"""
import enum
import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, Text, JSON, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class MatchStatus(str, enum.Enum):
    matched = "matched"
    review = "review"
    exception = "exception"


class MatchedBy(str, enum.Enum):
    ai = "ai"
    human = "human"


class ExceptionPriority(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ExceptionStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    rejected = "rejected"
    resolved = "resolved"


class AnomalyStatus(str, enum.Enum):
    open = "open"
    dismissed = "dismissed"
    resolved = "resolved"


class ForecastScenario(str, enum.Enum):
    baseline = "baseline"
    optimistic = "optimistic"
    conservative = "conservative"


# ─── Source tables ────────────────────────────────────────────────────────────

class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_ref = Column(String(128), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    date = Column(Date, nullable=False, index=True)
    description = Column(Text, nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Backref from matches
    matches_as_a = relationship(
        "ReconciliationMatch",
        foreign_keys="ReconciliationMatch.source_a_id",
        back_populates="source_a_bank",
        primaryjoin="and_(ReconciliationMatch.source_a_type=='bank', "
                    "ReconciliationMatch.source_a_id==BankTransaction.id)",
        overlaps="matches_as_a",
    )


class ErpInvoice(Base):
    __tablename__ = "erp_invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number = Column(String(64), nullable=False, unique=True, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    due_date = Column(Date, nullable=False, index=True)
    vendor = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="open")
    raw_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GatewaySettlement(Base):
    __tablename__ = "gateway_settlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_id = Column(String(128), nullable=False, unique=True, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    date = Column(Date, nullable=False, index=True)
    gateway_name = Column(String(64), nullable=False)
    vendor = Column(String(256), nullable=True)
    fee_amount = Column(Numeric(18, 2), nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ─── Reconciliation output ────────────────────────────────────────────────────

class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_a_type = Column(String(32), nullable=False)   # "bank" | "erp" | "gateway"
    source_a_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_b_type = Column(String(32), nullable=False)
    source_b_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    confidence_score = Column(Numeric(5, 2), nullable=False)
    match_reason = Column(Text, nullable=True)
    status = Column(Enum(MatchStatus), nullable=False)
    matched_at = Column(DateTime(timezone=True), server_default=func.now())
    matched_by = Column(Enum(MatchedBy), nullable=False, default=MatchedBy.ai)

    # Convenience relationship — only valid when source_a_type == "bank"
    source_a_bank = relationship(
        "BankTransaction",
        foreign_keys=[source_a_id],
        primaryjoin="and_(ReconciliationMatch.source_a_type=='bank', "
                    "ReconciliationMatch.source_a_id==BankTransaction.id)",
        overlaps="matches_as_a",
        viewonly=True,
    )


class Exception_(Base):
    """Named Exception_ to avoid clash with Python builtin `Exception`."""
    __tablename__ = "exceptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("reconciliation_matches.id"), nullable=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    exposure_amount = Column(Numeric(18, 2), nullable=True)
    exposure_currency = Column(String(8), nullable=True, default="INR")
    priority = Column(Enum(ExceptionPriority), nullable=False, default=ExceptionPriority.medium)
    status = Column(Enum(ExceptionStatus), nullable=False, default=ExceptionStatus.open)
    resolved_by = Column(String(256), nullable=True)       # actor who approved/rejected
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    match = relationship("ReconciliationMatch", foreign_keys=[match_id])


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(String(64), nullable=False)              # "duplicate_payout" | "variance_drift" | "off_schedule"
    description = Column(Text, nullable=False)
    amount = Column(Numeric(18, 2), nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    related_transaction_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(Enum(AnomalyStatus), nullable=False, default=AnomalyStatus.open)
    detail = Column(JSONB, nullable=True)                  # stores the raw numbers that triggered it


class HealthScoreSnapshot(Base):
    __tablename__ = "health_score_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    score = Column(Integer, nullable=False)
    match_rate = Column(Numeric(5, 4), nullable=False)
    exception_count = Column(Integer, nullable=False, default=0)
    total_records = Column(Integer, nullable=False, default=0)
    quality_score = Column(Numeric(5, 4), nullable=True)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """
    INSERT-ONLY. Never updated or deleted.
    DB-level enforcement via migration 003_rls_audit_immutability.sql (REVOKE UPDATE, DELETE).
    """
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor = Column(String(256), nullable=False, default="ai")
    action = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=True)
    entity_id = Column(String(128), nullable=True)
    detail = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class CashForecastScenario(Base):
    __tablename__ = "cash_forecast_scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario = Column(Enum(ForecastScenario), nullable=False)
    week_offset = Column(Integer, nullable=False)          # 0 = current week, 1 = +7 days, …
    projected_balance = Column(Numeric(18, 2), nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
