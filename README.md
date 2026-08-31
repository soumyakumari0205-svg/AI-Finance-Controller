# AI Finance Controller — Autonomous Financial Verification OS

> **Run the books. Control the cash. Verify everything.**  
> An enterprise AI financial operating system that reconciles multi-source ledgers, measures verification accuracy, surfaces priority exceptions, and models real-time cash positions.

[![Live Demo](https://img.shields.io/badge/Live_Demo-GitHub_Pages-00F0FF?style=for-the-badge&logo=github)](https://soumyakumari0205-svg.github.io/AI-Finance-Controller/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI_Async-00E676?style=for-the-badge&logo=fastapi)](https://github.com/soumyakumari0205-svg/AI-Finance-Controller)
[![Database](https://img.shields.io/badge/Database-Postgres_%2B_Supabase-3ECF8E?style=for-the-badge&logo=supabase)](https://github.com/soumyakumari0205-svg/AI-Finance-Controller)
[![Tests](https://img.shields.io/badge/Tests-35_Passing_(100%25)-brightgreen?style=for-the-badge&logo=pytest)](https://github.com/soumyakumari0205-svg/AI-Finance-Controller)

---

## 🌐 Live Application
* **Live Web App**: [https://soumyakumari0205-svg.github.io/AI-Finance-Controller/](https://soumyakumari0205-svg.github.io/AI-Finance-Controller/)
* **Repository**: [https://github.com/soumyakumari0205-svg/AI-Finance-Controller](https://github.com/soumyakumari0205-svg/AI-Finance-Controller)

---

## ✨ Key Features & Architecture

### 1. Zero-Gate Direct Dashboard Entry
* Immediate access to the live dashboard on page load without auth blockers or login gates.
* Seamless unauthenticated demo mode with automatic fallback for static GitHub Pages and production API support.

### 2. Real AI Reconciliation Engine (`rapidfuzz`)
* **Pass 1 (Exact Match 95–100%)**: Matching within ±0.01 amount, ±3 days date proximity, and exact transaction/invoice reference token overlaps.
* **Pass 2 (Fuzzy Match 70–94%)**: Weighted score combining amount proximity (40%), date proximity (30%), and description similarity via `token_set_ratio` (30%).
* **Unmatched / Anomalous Records**: Automatically routed to the **Priority Exception Command Center**.

### 3. Operations Center & Multi-Filter Engine
* **Combined AND Filtering**: Combine **Search** (instant case-insensitive across IDs, vendors, descriptions, amounts, statuses, and sources) + **Source** (`Bank`, `ERP`, `Gateway`) + **Status** (`🟢 Matched`, `🟡 Review Needed`, `🔴 Exception`) + **Confidence Tier** (`High >=90%`, `Medium 70-89%`, `Low <70%`) + **Time Travel Slider** (`Past 30 Days`, `Today`, `Next 7 Days`, `Next 30 Days`).
* **Single-Click Reset**: Instant reset restoring all filters, search query, confidence pills, and date window slider to default.

### 4. Interactive Exception Command Center & Full Lifecycle
* **Action Handlers**: **Approve**, **Reject**, **Resolve**, and **Reopen** actions backed by `POST /api/exceptions/{id}/approve`, `POST /api/exceptions/{id}/reject`, `POST /api/exceptions/{id}/resolve`, `POST /api/exceptions/{id}/reopen`, and `PATCH /api/exceptions/{id}`.
* **Resilience**: Real error handling preventing false success feedback; database updates record `resolved_by`, `resolved_at` timestamps, and emit immutable audit log entries.
* **Live Metric Reactivity**: Approval/rejection dynamically updates open exception counts, auto-resolved metrics, risk radar levels, and system health score.

### 5. Reactive Cash Forecasting & What-If Simulation
* **Scenario Modeling**: Toggle between **Baseline**, **Optimistic**, and **Conservative** cash flow scenarios.
* **What-If Sliders**: Real-time simulation of delayed receivables (0–14 days) and unexpected vendor expenses (+$0 to +$100k) hitting `POST /api/forecast/what-if` with reactive bar chart re-rendering.

### 6. Automated Anomaly Detection & Immutable Audit Logging
* **Anomalies Detected**: Duplicate payouts (same vendor/amount within 24h), fee variance drift (>3% above 90-day trailing baseline), and off-schedule invoices.
* **Immutable Audit Trail**: Append-only `audit_log` table protected by PostgreSQL `REVOKE` and Row Level Security (RLS) policies.
* **Exporting**: Full CSV export for reconciliation records and complete decision audit trails.

---

## 🚀 Quick Start (Docker Compose — Recommended)

```bash
git clone https://github.com/soumyakumari0205-svg/AI-Finance-Controller.git
cd AI-Finance-Controller

# Copy env file
cp backend/.env.example backend/.env

# Build and start all services (Postgres + FastAPI + nginx)
docker-compose up --build
```

Open **http://localhost:8080** in your browser.

---

## 💻 Local Setup Without Docker

### Prerequisites
* **Python 3.11+**
* **PostgreSQL 14+** (or SQLite for dev/testing)

### 1. Backend Setup
```bash
cd backend

# Create & activate virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Run database migrations (Postgres owner/superuser)
psql $DATABASE_URL_OWNER -f migrations/001_initial_schema.sql
psql $DATABASE_URL_OWNER -f migrations/002_indexes.sql
psql $DATABASE_URL_OWNER -f migrations/003_rls_audit_immutability.sql

# Start FastAPI API server on port 8000
python -m uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Access
* Open [`index.html`](index.html) directly in any browser, or serve using any static file server:
  ```bash
  python -m http.server 8080
  ```
* Open **http://localhost:8080** (or **http://127.0.0.1:8080**).

---

## 🧪 Testing

Run the complete test suite:
```bash
python -m pytest backend/tests -v
```

**Results**: 35 passed tests covering:
* Exact & fuzzy matching engine composite scoring
* Anomaly detection algorithms (duplicate payout, fee variance, off-schedule billing)
* Full exception lifecycle transitions (`open` → `approved` / `rejected` / `resolved` / `reopened`)
* Operations Center multi-filter querying with AND logic

---

## 📡 API Reference

Interactive Swagger documentation: **http://localhost:8000/docs**

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/kpis` | Summary KPI metrics computed from live database |
| `GET` | `/api/health-score` | Weighted financial health score and snapshot history |
| `GET` | `/api/reconcile/records` | Multi-filter reconciliation records (`search`, `source`, `status`, `time_window`, `confidence_tier`) |
| `POST` | `/api/reconcile/run` | Execute multi-pass reconciliation engine pipeline |
| `GET` | `/api/exceptions` | List open/resolved exceptions filtered by status and priority |
| `POST` | `/api/exceptions/{id}/approve` | Approve exception and record resolution |
| `POST` | `/api/exceptions/{id}/reject` | Reject exception with note |
| `POST` | `/api/exceptions/{id}/resolve` | Resolve exception |
| `POST` | `/api/exceptions/{id}/reopen` | Reopen exception back to active queue |
| `PATCH` | `/api/exceptions/{id}` | Update exception status (`accepted`, `approved`, `rejected`, `resolved`, `open`) |
| `GET` | `/api/anomalies` | List detected anomalies |
| `GET` | `/api/forecast` | 6-week cash forecast by scenario (`baseline`, `optimistic`, `conservative`) |
| `POST` | `/api/forecast/what-if` | Server-side cash simulation recomputation |
| `GET` | `/api/audit-log` | Immutable decision and reconciliation audit log |
| `POST` | `/api/seed` | Generate synthetic records (dev only, `ENABLE_SEED_ENDPOINT=true`) |
| `GET` | `/health` | API health check |

---

## ⚙️ Environment Variables

| Variable | Description | Default / Example |
|---|---|---|
| `DATABASE_URL` | Async Postgres connection string | `postgresql+asyncpg://finance_app:finance_app_pass@localhost:5432/finance_controller` |
| `SUPABASE_URL` | Supabase project URL | `https://your-project.supabase.co` |
| `SUPABASE_JWT_SECRET` | Supabase JWT secret | `dev-secret-change-me` |
| `ENABLE_SEED_ENDPOINT` | Allow synthetic record generation in dev | `true` |
| `SCHEDULER_INTERVAL_MINUTES`| Background reconciliation job interval | `30` |
| `DATE_WINDOW_DAYS` | ±days for reconciliation date matching | `3` |
| `FUZZY_THRESHOLD` | Composite score threshold for fuzzy matches | `0.70` (70%) |
| `FEE_VARIANCE_THRESHOLD` | Drift threshold for anomaly detection | `0.03` (3%) |

---

## 🏗️ Project Structure

```
AI-Finance-Controller/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI application entry point
│   │   ├── config.py           # Settings and environment variables
│   │   ├── auth.py             # Public demo access & Supabase JWT auth
│   │   ├── database.py         # Async SQLAlchemy engine and session
│   │   ├── models.py           # 9 ORM models
│   │   ├── schemas.py          # Pydantic request & response schemas
│   │   ├── engine/
│   │   │   ├── matcher.py      # Exact + rapidfuzz reconciliation engine
│   │   │   ├── anomaly.py      # Duplicate, variance, and schedule detectors
│   │   │   ├── health.py       # Weighted health score engine
│   │   │   └── forecast.py     # Cash forecast & what-if simulator
│   │   ├── routers/            # 9 FastAPI modular router endpoints
│   │   └── jobs/
│   │       └── scheduler.py    # APScheduler automated reconciliation job
│   ├── migrations/             # SQL schema, indexes, and RLS policies
│   ├── tests/                  # 35 unit & integration tests
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── docker-compose.yml
├── nginx.conf
├── index.html                  # Single-Page App (WebGL mesh, Magic Bento, GSAP)
└── README.md
```

---

## 📜 License
Distributed under the MIT License.

