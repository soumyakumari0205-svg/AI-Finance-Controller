# AI Finance Controller

> **Autonomous Financial Verification OS**  
> Run the books. Control the cash. Verify everything.

Real FastAPI backend replacing all client-side `Math.random()` with:
- A **real fuzzy matching engine** (rapidfuzz) for bank ↔ ERP ↔ gateway reconciliation  
- **Real anomaly detection** (duplicate payouts, fee variance drift, off-schedule billing)  
- A **computed health score** with a documented weighted formula  
- **Server-side cash forecasting** with what-if scenario recomputation  
- **Supabase JWT auth** on every API route  
- **DB-level immutable audit log** (REVOKE + Row Level Security)

---

## Quick Start (Docker Compose — recommended)

```bash
git clone https://github.com/soumyakumari0205-svg/AI-Finance-Controller.git
cd AI-Finance-Controller

# Copy env file and fill in your Supabase credentials (optional for local dev)
cp backend/.env.example backend/.env

# Start everything (Postgres + FastAPI + nginx)
docker-compose up --build
```

Then open **http://localhost:8080** in your browser.

> Log in with your Supabase credentials, then click **"Run AI Reconciliation"**.  
> First run: use the seed endpoint to populate synthetic data (dev only).

---

## Seed Synthetic Data (Dev Only)

```bash
# Requires ENABLE_SEED_ENDPOINT=true in backend/.env (already set in docker-compose)
curl -X POST http://localhost:8000/api/seed \
  -H "Authorization: Bearer <your_supabase_jwt>"
```

Then hit **Run AI Reconciliation** in the dashboard, or:

```bash
curl -X POST http://localhost:8000/api/reconcile/run \
  -H "Authorization: Bearer <your_supabase_jwt>"
```

---

## Run Locally Without Docker

**Prerequisites:** Python 3.12+, PostgreSQL 14+

```bash
cd backend

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set environment variables
copy .env.example .env         # Windows
# cp .env.example .env         # Mac/Linux
# Edit .env: set DATABASE_URL to your local Postgres

# Run database migrations
psql $DATABASE_URL -f migrations/001_initial_schema.sql
psql $DATABASE_URL -f migrations/002_indexes.sql
psql $DATABASE_URL -f migrations/003_rls_audit_immutability.sql

# Start the API server
uvicorn app.main:app --reload --port 8000
```

Open **index.html** in a browser (or serve it at `http://localhost:8080`).

---

## Run Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/test_matcher.py -v      # Unit: matching engine
pytest tests/test_anomaly.py -v      # Unit: anomaly detection
pytest tests/test_integration.py -v  # Integration: seed → reconcile → verify
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Async Postgres connection string | `postgresql+asyncpg://finance:finance@db:5432/finance_controller` |
| `SUPABASE_URL` | Your Supabase project URL | — |
| `SUPABASE_SERVICE_KEY` | Service role key (server-side only, NEVER in browser) | — |
| `SUPABASE_JWT_SECRET` | Shared JWT secret (local dev without JWKS) | `dev-secret-change-me` |
| `SUPABASE_JWKS_URL` | JWKS endpoint for JWT verification (production) | — |
| `ENABLE_SEED_ENDPOINT` | Enable `POST /api/seed` (dev only) | `false` |
| `SCHEDULER_INTERVAL_MINUTES` | Reconciliation background job interval | `30` |
| `DATE_WINDOW_DAYS` | ±days for date matching in reconciliation | `3` |
| `FUZZY_THRESHOLD` | Minimum composite score for fuzzy match | `0.70` |
| `FEE_VARIANCE_THRESHOLD` | Fee drift threshold for anomaly detection | `0.03` (3%) |

---

## API Reference

All routes require `Authorization: Bearer <supabase_jwt>` header.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/seed` | Seed synthetic data (dev only, requires `ENABLE_SEED_ENDPOINT=true`) |
| `POST` | `/api/ingest/{source}` | Ingest batch of bank/erp/gateway records |
| `POST` | `/api/reconcile/run` | Run full reconciliation pipeline |
| `GET` | `/api/reconcile/records` | Paginated, filterable reconciliation records |
| `GET` | `/api/exceptions` | List exceptions (filterable by priority/status) |
| `POST` | `/api/exceptions/{id}/approve` | Approve exception (controller role required) |
| `POST` | `/api/exceptions/{id}/reject` | Reject exception (controller role required) |
| `GET` | `/api/health-score` | Current health score + trend history |
| `GET` | `/api/anomalies` | List AI-detected anomalies |
| `GET` | `/api/forecast` | Cash forecast by scenario |
| `POST` | `/api/forecast/what-if` | Server-side what-if recomputation |
| `GET` | `/api/audit-log` | Immutable audit trail |
| `GET` | `/api/kpis` | Dashboard KPI summary |
| `GET` | `/health` | API health check |

Interactive docs: **http://localhost:8000/docs**

---

## Reconciliation Engine

**Pass 1 — Exact Match** (confidence 95–100%):
- Amount within ±0.01
- Date within ±`DATE_WINDOW_DAYS` days  
- Reference number token overlap ≥ 1

**Pass 2 — Fuzzy Match** (confidence 70–94%):
```
score = amount_score × 0.40
      + date_score   × 0.30
      + desc_score   × 0.30   # rapidfuzz.fuzz.token_set_ratio
```

**Remainder** → `exception` with human-readable match reason.

---

## Health Score Formula

```
health_score = (
    match_rate_score × 0.45    # matched / total
  + exception_score  × 0.25    # 1 - (open_exceptions / total)
  + age_score        × 0.15    # 1 - (avg_age_hours / 48), capped at 0
  + quality_score    × 0.15    # 1 - (null_descriptions / total_bank)
) × 100
```

---

## Deployment (Cloud Run / Railway)

```bash
# Build and push Docker image
docker build -t ai-finance-controller ./backend
docker tag ai-finance-controller gcr.io/YOUR_PROJECT/ai-finance-controller
docker push gcr.io/YOUR_PROJECT/ai-finance-controller

# Set production environment variables:
# DATABASE_URL     → your Supabase Postgres connection string
# SUPABASE_JWKS_URL → https://your-project.supabase.co/auth/v1/jwks
# SUPABASE_SERVICE_KEY → from Supabase dashboard (Settings > API)
# ENABLE_SEED_ENDPOINT → false (do NOT enable in production)
```

---

## Project Structure

```
ai-finance-controller/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app entry point
│   │   ├── config.py         # Settings (pydantic-settings)
│   │   ├── auth.py           # Supabase JWT verification
│   │   ├── database.py       # Async SQLAlchemy
│   │   ├── models.py         # 9 ORM models
│   │   ├── schemas.py        # Pydantic request/response schemas
│   │   ├── engine/
│   │   │   ├── matcher.py    # Exact + fuzzy reconciliation
│   │   │   ├── anomaly.py    # Anomaly detection (3 heuristics)
│   │   │   ├── health.py     # Health score formula
│   │   │   └── forecast.py   # Cash forecasting + what-if
│   │   ├── routers/          # 9 API route files
│   │   └── jobs/
│   │       └── scheduler.py  # APScheduler background job
│   ├── migrations/           # 3 SQL migration files
│   ├── tests/                # pytest unit + integration tests
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── docker-compose.yml
├── nginx.conf
├── index.html                # Frontend (WebGL + real API fetch)
└── README.md
```
