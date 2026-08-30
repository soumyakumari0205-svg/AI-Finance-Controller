-- Migration 001: Initial schema
-- Run with: psql $DATABASE_URL -f migrations/001_initial_schema.sql

BEGIN;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── bank_transactions ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bank_transactions (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_ref VARCHAR(128) NOT NULL,
    amount       NUMERIC(18, 2) NOT NULL,
    currency     VARCHAR(8)  NOT NULL DEFAULT 'INR',
    date         DATE        NOT NULL,
    description  TEXT,
    raw_payload  JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── erp_invoices ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erp_invoices (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_number VARCHAR(64) NOT NULL UNIQUE,
    amount         NUMERIC(18, 2) NOT NULL,
    currency       VARCHAR(8)  NOT NULL DEFAULT 'INR',
    due_date       DATE        NOT NULL,
    vendor         VARCHAR(256) NOT NULL,
    status         VARCHAR(32) NOT NULL DEFAULT 'open',
    raw_payload    JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── gateway_settlements ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gateway_settlements (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    settlement_id VARCHAR(128) NOT NULL UNIQUE,
    amount        NUMERIC(18, 2) NOT NULL,
    currency      VARCHAR(8)  NOT NULL DEFAULT 'INR',
    date          DATE        NOT NULL,
    gateway_name  VARCHAR(64) NOT NULL,
    vendor        VARCHAR(256),
    fee_amount    NUMERIC(18, 2),
    raw_payload   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── reconciliation_matches ───────────────────────────────────────────────────
CREATE TYPE match_status AS ENUM ('matched', 'review', 'exception');
CREATE TYPE matched_by   AS ENUM ('ai', 'human');

CREATE TABLE IF NOT EXISTS reconciliation_matches (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_a_type    VARCHAR(32)    NOT NULL,
    source_a_id      UUID           NOT NULL,
    source_b_type    VARCHAR(32)    NOT NULL,
    source_b_id      UUID           NOT NULL,
    confidence_score NUMERIC(5, 2)  NOT NULL,
    match_reason     TEXT,
    status           match_status   NOT NULL,
    matched_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    matched_by       matched_by     NOT NULL DEFAULT 'ai'
);

-- ─── exceptions ───────────────────────────────────────────────────────────────
CREATE TYPE exception_priority AS ENUM ('critical', 'high', 'medium', 'low');
CREATE TYPE exception_status   AS ENUM ('open', 'approved', 'rejected', 'resolved');

CREATE TABLE IF NOT EXISTS exceptions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    match_id            UUID REFERENCES reconciliation_matches(id) ON DELETE SET NULL,
    title               VARCHAR(256)        NOT NULL,
    description         TEXT,
    exposure_amount     NUMERIC(18, 2),
    exposure_currency   VARCHAR(8)          DEFAULT 'INR',
    priority            exception_priority  NOT NULL DEFAULT 'medium',
    status              exception_status    NOT NULL DEFAULT 'open',
    resolved_by         VARCHAR(256),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ         NOT NULL DEFAULT NOW()
);

-- ─── anomalies ────────────────────────────────────────────────────────────────
CREATE TYPE anomaly_status AS ENUM ('open', 'dismissed', 'resolved');

CREATE TABLE IF NOT EXISTS anomalies (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type                    VARCHAR(64)    NOT NULL,
    description             TEXT           NOT NULL,
    amount                  NUMERIC(18, 2),
    detected_at             TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    related_transaction_id  UUID,
    status                  anomaly_status NOT NULL DEFAULT 'open',
    detail                  JSONB
);

-- ─── health_score_snapshots ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS health_score_snapshots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    score           INTEGER        NOT NULL,
    match_rate      NUMERIC(5, 4)  NOT NULL,
    exception_count INTEGER        NOT NULL DEFAULT 0,
    total_records   INTEGER        NOT NULL DEFAULT 0,
    quality_score   NUMERIC(5, 4),
    computed_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- ─── audit_log ────────────────────────────────────────────────────────────────
-- Immutability enforced in migration 003 via REVOKE and RLS.
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL   PRIMARY KEY,
    actor       VARCHAR(256) NOT NULL DEFAULT 'ai',
    action      VARCHAR(128) NOT NULL,
    entity_type VARCHAR(64),
    entity_id   VARCHAR(128),
    detail      JSONB,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─── cash_forecast_scenarios ──────────────────────────────────────────────────
CREATE TYPE forecast_scenario AS ENUM ('baseline', 'optimistic', 'conservative');

CREATE TABLE IF NOT EXISTS cash_forecast_scenarios (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scenario          forecast_scenario NOT NULL,
    week_offset       INTEGER           NOT NULL,
    projected_balance NUMERIC(18, 2)    NOT NULL,
    computed_at       TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

COMMIT;
