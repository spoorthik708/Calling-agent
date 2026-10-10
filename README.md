# YAVURA - Production SaaS Platform

> **Enterprise AI Conversational Voice Agent SaaS Platform**

YAVURA enables businesses to deploy AI-powered conversational voice agents capable of conducting natural, human-like inbound and outbound phone calls across **English, Hindi, Telugu, and Tamil**.

---

## 1. Core Architectural Principle

> **The AI model is responsible for understanding and generating conversation.**  
> **The application and verified business systems are responsible for factual truth.**

The AI model is **never** permitted to invent:
- Prices, discounts, or promotional offers
- Referral conditions or partner agreements
- Product inventory or appointment availability
- Account balances or payment information
- Business policies, deadlines, or guarantees

If verified business knowledge is available, the agent explains it naturally. If verified knowledge is unavailable, the agent is forbidden from guessing and will prompt for clarification or escalate to a human.

---

## 2. Implementation Phases & Architecture Roadmap

For full detailed documentation on all architecture phases, endpoints, and test suites, see [docs/phases-roadmap.md](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/docs/phases-roadmap.md).

| Phase | Module Name | Core Deliverables | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **Production Foundation** | Multi-tenant Async FastAPI, PostgreSQL + `pgvector`, Docker Compose, Security baseline | Completed ✅ |
| **Phase 2** | **Auth, Tenant & RBAC** | Argon2/JWT auth, refresh tokens, role-based authorization (`Admin`, `Manager`, `Operator`), rate limiting | Completed ✅ |
| **Phase 3** | **Knowledge & RAG Engine** | PDF/TXT document ingestion, semantic chunking, embeddings, RAG retrieval & factual verifier | Completed ✅ |
| **Phase 4** | **AI Agent Engine** | Provider-agnostic LLM interface, state machine turn manager, memory truncation & prompt defense | Completed ✅ |
| **Phase 5** | **Secure Action Sandbox** | Tool registry, HTTP integration sandbox, SSRF IP-range protection & execution audit logs | Completed ✅ |
| **Phase 6** | **Real-Time Voice Pipeline** | Streaming STT/TTS (En, Hi, Te, Ta), VAD, barge-in cancellation & latency telemetry | Completed ✅ |
| **Phase 7** | **Telephony & Analytics** | Twilio/SIP inbound/outbound call dispatcher, campaign scheduler & analytics dashboard | Active Roadmap 🚀 |

---

## 3. Technology Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (Async), Alembic, `asyncpg`, `aiosqlite`
- **Frontend**: Next.js 14, React 18, TypeScript, Tailwind CSS
- **Database**: PostgreSQL 16 with `pgvector` extension support
- **Infrastructure**: Docker, Docker Compose, Environment-based configuration
- **AI Layer**: Provider-agnostic abstraction (`AIProviderInterface`) with pluggable adapters

---

## 3. Repository Structure

```
yavura/
│
├── backend/
│   ├── app/
│   │   ├── api/            # API v1 routers & endpoints
│   │   ├── core/           # Config, logging, security, custom exceptions
│   │   ├── auth/           # ContextVar tenant context & auth dependencies
│   │   ├── database/       # Async engine, session, Base, TenantAwareModel mixin
│   │   ├── models/         # Declarative entities (Tenant, User, AuditLog)
│   │   ├── schemas/        # Pydantic schemas (Health, Tenant, User, API envelopes)
│   │   ├── security/       # Tenant isolation filters, input & injection validation
│   │   ├── agents/         # AI provider interface, AgentDecision, BaseAgentRuntime
│   │   ├── conversations/  # Conversation session & turn management interfaces
│   │   ├── knowledge/      # Verified knowledge schemas, grounding verifier interface
│   │   ├── tools/          # BaseTool, ToolRegistry with strict argument validation
│   │   ├── voice/          # Real-time voice session & barge-in handler interfaces
│   │   ├── telephony/      # Pluggable telephony provider contract
│   │   ├── integrations/   # CRM sync and webhook dispatcher interfaces
│   │   ├── observability/  # Latency measurement & structured metrics
│   │   └── main.py         # FastAPI application entrypoint & lifespan
│   │
│   ├── migrations/         # Alembic database migrations
│   ├── tests/              # Pytest test suite (health, isolation, security, runtime)
│   ├── requirements.txt    # Production Python dependencies
│   ├── pyproject.toml      # Build metadata and tool configuration
│   ├── alembic.ini         # Migration configuration
│   └── Dockerfile          # Backend container image
│
├── frontend/
│   ├── src/
│   │   ├── app/            # Next.js App Router (layout, page, globals.css)
│   │   └── components/     # Reusable UI components
│   ├── package.json        # Frontend dependencies
│   ├── tsconfig.json       # TypeScript configuration
│   ├── tailwind.config.ts  # Tailwind CSS configuration
│   └── Dockerfile          # Frontend container image
│
├── infrastructure/
│   └── docker/
│       └── postgres/
│           └── init-pgvector.sql # Database extension setup
│
├── docs/
│   └── architecture.md     # In-depth architectural design specification
│
├── tests/                  # Root placeholder for end-to-end / system test suites
├── .env.example            # Environment variable template
├── .gitignore              # Git ignore rules (secrets, venvs, build artifacts)
├── docker-compose.yml      # Local container orchestration
└── README.md               # Project guide
```

---

## 4. Local Development Requirements

- **Python 3.11+**
- **Node.js 18+** & **npm**
- **Docker** and **Docker Compose** (for containerized stack)

---

## 5. Environment Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Update `.env` with your local settings. Sensitive keys are masked using Pydantic's `SecretStr` and will never appear in logs or error traces.

---

## 6. How to Start the Project

### Option A: Using Docker Compose (Recommended for Full Stack)

```bash
docker compose up --build
```

- Backend API: `http://localhost:8000`
- API Health Check: `http://localhost:8000/health`
- Interactive API Docs: `http://localhost:8000/docs`
- Frontend Console: `http://localhost:3000`

### Option B: Running Backend Locally

1. Create and activate a Python virtual environment:
   ```bash
   python -m venv backend/.venv
   # Windows PowerShell:
   backend/.venv/Scripts/Activate.ps1
   # Linux/macOS:
   source backend/.venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. Start the FastAPI development server:
   ```bash
   cd backend
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

### Option C: Running Frontend Locally

```bash
cd frontend
npm install
npm run dev
```

---

## 7. How to Run Tests

Run the backend test suite with `pytest`:

```bash
cd backend
pytest -v
```

### Test Suite Coverage
- **`test_health.py`**: Verifies infrastructure health check (`GET /health`) and security headers.
- **`test_config.py`**: Verifies settings validation and secret masking.
- **`test_tenant_isolation.py`**: Verifies multi-tenant data boundaries and query isolation.
- **`test_factual_truth_principle.py`**: Verifies Core Product Principle enforcement (preventing AI hallucination of unverified business facts).
- **`test_tool_security.py`**: Verifies that tool arguments are sanitized and arbitrary code/command execution is blocked.
- **`test_ai_provider_abstraction.py`**: Verifies pluggable AI provider contracts.

---

## 8. Development Principles

1. **Multi-Tenancy First**: Never write a query or service without explicit tenant scoping.
2. **Never Blindly Trust External Input**: Always validate with Pydantic schemas.
3. **Decouple Vendors**: Business logic depends on interfaces, never vendor SDKs.
4. **Zero Hardcoded Secrets**: Secrets live exclusively in environment variables or vault systems.
5. **Factual Grounding Over Fluency**: Accuracy is prioritized over sounding confident when information is unknown.
