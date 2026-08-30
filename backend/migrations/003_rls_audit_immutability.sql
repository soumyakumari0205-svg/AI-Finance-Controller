-- Migration 003: Enforce audit_log immutability at the database level
-- Run with: psql $DATABASE_URL -f migrations/003_rls_audit_immutability.sql
--
-- This creates a dedicated app role and REVOKES UPDATE + DELETE on audit_log
-- from that role. Even if the application code tries to update/delete a row,
-- Postgres will reject it with a permission error.
-- The service role (superuser used only for migrations) can still read/write for
-- operational recovery — but application runtime must use the restricted role.

BEGIN;

-- Create a restricted application role dynamically using a session config variable
DO $$
DECLARE
    app_pwd text;
BEGIN
    app_pwd := COALESCE(current_setting('app.finance_app_password', true), 'finance_app_pass');
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_app') THEN
        EXECUTE format('CREATE ROLE finance_app LOGIN PASSWORD %L', app_pwd);
    ELSE
        EXECUTE format('ALTER ROLE finance_app WITH PASSWORD %L', app_pwd);
    END IF;
END
$$;

-- Grant full access to all tables to the app role
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO finance_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO finance_app;

-- ── Revoke UPDATE and DELETE on audit_log ─────────────────────────────────────
-- This is the tamper-evidence enforcement. The app role cannot mutate audit rows.
REVOKE UPDATE ON audit_log FROM finance_app;
REVOKE DELETE ON audit_log FROM finance_app;

-- Revoke from the owner/migration user 'finance' for runtime enforcement
REVOKE UPDATE, DELETE ON audit_log FROM finance;

-- Enable Row Level Security on audit_log as an additional layer
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

-- Policy: anyone authenticated can SELECT; only INSERT is allowed (no update/delete)
CREATE POLICY audit_log_select_policy ON audit_log
    FOR SELECT
    USING (true);

CREATE POLICY audit_log_insert_policy ON audit_log
    FOR INSERT
    WITH CHECK (true);

-- Explicitly block UPDATE via RLS policy (belt-and-suspenders with REVOKE above)
CREATE POLICY audit_log_no_update ON audit_log
    FOR UPDATE
    USING (false);

CREATE POLICY audit_log_no_delete ON audit_log
    FOR DELETE
    USING (false);

-- ── Grant future tables automatically ─────────────────────────────────────────
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO finance_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO finance_app;

COMMIT;

-- Verification: run the following as finance_app to confirm immutability:
-- UPDATE audit_log SET action='tampered' WHERE id=1;  → ERROR: permission denied
-- DELETE FROM audit_log WHERE id=1;                   → ERROR: permission denied
