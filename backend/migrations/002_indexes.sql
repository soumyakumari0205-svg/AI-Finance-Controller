-- Migration 002: Indexes on match-critical columns
-- Run with: psql $DATABASE_URL -f migrations/002_indexes.sql

BEGIN;

-- bank_transactions
CREATE INDEX IF NOT EXISTS idx_bank_external_ref ON bank_transactions(external_ref);
CREATE INDEX IF NOT EXISTS idx_bank_date         ON bank_transactions(date);
CREATE INDEX IF NOT EXISTS idx_bank_amount       ON bank_transactions(amount);
CREATE INDEX IF NOT EXISTS idx_bank_currency     ON bank_transactions(currency);

-- erp_invoices
CREATE INDEX IF NOT EXISTS idx_erp_invoice_number ON erp_invoices(invoice_number);
CREATE INDEX IF NOT EXISTS idx_erp_due_date       ON erp_invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_erp_amount         ON erp_invoices(amount);
CREATE INDEX IF NOT EXISTS idx_erp_vendor         ON erp_invoices(vendor);

-- gateway_settlements
CREATE INDEX IF NOT EXISTS idx_gw_settlement_id ON gateway_settlements(settlement_id);
CREATE INDEX IF NOT EXISTS idx_gw_date          ON gateway_settlements(date);
CREATE INDEX IF NOT EXISTS idx_gw_amount        ON gateway_settlements(amount);
CREATE INDEX IF NOT EXISTS idx_gw_vendor        ON gateway_settlements(vendor);
CREATE INDEX IF NOT EXISTS idx_gw_gateway_name  ON gateway_settlements(gateway_name);

-- reconciliation_matches
CREATE INDEX IF NOT EXISTS idx_rm_source_a_id   ON reconciliation_matches(source_a_id);
CREATE INDEX IF NOT EXISTS idx_rm_source_b_id   ON reconciliation_matches(source_b_id);
CREATE INDEX IF NOT EXISTS idx_rm_status        ON reconciliation_matches(status);
CREATE INDEX IF NOT EXISTS idx_rm_matched_by    ON reconciliation_matches(matched_by);

-- exceptions
CREATE INDEX IF NOT EXISTS idx_exc_status   ON exceptions(status);
CREATE INDEX IF NOT EXISTS idx_exc_priority ON exceptions(priority);
CREATE INDEX IF NOT EXISTS idx_exc_match_id ON exceptions(match_id);

-- anomalies
CREATE INDEX IF NOT EXISTS idx_anom_status      ON anomalies(status);
CREATE INDEX IF NOT EXISTS idx_anom_detected_at ON anomalies(detected_at);

-- health_score_snapshots
CREATE INDEX IF NOT EXISTS idx_hss_computed_at ON health_score_snapshots(computed_at DESC);

-- audit_log
CREATE INDEX IF NOT EXISTS idx_audit_created_at   ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity_type  ON audit_log(entity_type);
CREATE INDEX IF NOT EXISTS idx_audit_actor        ON audit_log(actor);

-- cash_forecast_scenarios
CREATE INDEX IF NOT EXISTS idx_cfs_scenario_offset
    ON cash_forecast_scenarios(scenario, week_offset);

COMMIT;
