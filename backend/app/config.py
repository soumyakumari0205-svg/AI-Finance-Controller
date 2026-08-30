"""
Central settings loaded from environment variables.
All secrets stay server-side — the browser never sees DATABASE_URL or SUPABASE_SERVICE_KEY.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://finance:finance@db:5432/finance_controller"

    # ── Supabase (server-side only) ───────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""           # Never expose to client
    supabase_jwt_secret: str = ""            # Used for local JWT verification fallback
    supabase_jwks_url: str = ""              # e.g. https://<project>.supabase.co/auth/v1/jwks

    # ── Reconciliation engine knobs ───────────────────────────────────────────
    date_window_days: int = 3                # ±days for date matching
    exact_match_ref_min_tokens: int = 1      # min shared reference tokens for exact pass
    fuzzy_threshold: float = 0.70            # minimum composite score to reach "review"
    duplicate_tie_threshold: float = 0.80    # score above which two candidates = duplicate risk

    # ── Anomaly detection thresholds ─────────────────────────────────────────
    fee_variance_threshold: float = 0.03     # 3% deviation triggers amount-variance anomaly
    duplicate_window_hours: int = 24         # hours window for duplicate payout check

    # ── Cash forecasting ─────────────────────────────────────────────────────
    forecast_weeks: int = 6
    optimistic_receivable_multiplier: float = 1.05
    optimistic_expense_multiplier: float = 0.95
    conservative_receivable_multiplier: float = 0.90
    conservative_expense_multiplier: float = 1.10

    # ── Feature flags ─────────────────────────────────────────────────────────
    enable_seed_endpoint: bool = False       # Must be True only in dev; NEVER in prod
    scheduler_interval_minutes: int = 30

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:8080", "http://127.0.0.1:8080", "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
