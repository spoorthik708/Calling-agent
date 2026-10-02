# YAVURA Platform Architecture

> **Document Version:** 0.1.0  
> **Status:** Production Foundation  
> **Target Audience:** Engineering, Architecture, Security, Product

---

## 1. Product Vision & Architecture Overview

YAVURA is an enterprise multi-tenant SaaS platform enabling businesses to deploy conversational AI voice agents capable of conducting natural, human-like inbound and outbound phone conversations.

### Supported Multi-Language Capabilities
- English
- Hindi
- Telugu
- Tamil

### Primary Target Sectors
- Education companies (student inquiries, admissions counseling)
- Customer support centers (tier-1 triage, FAQs, ticket dispatch)
- Sales & qualification organizations (lead intake, qualification, CRM sync)
- Appointment-based businesses (clinics, salons, service booking)

---

## 2. Core Product Principle: Factual Truth vs. AI Generation

```
                     ┌───────────────────────────────┐
                     │   Verified Business Systems   │
                     │   (DB, CRM, Policies, Docs)   │
                     └───────────────┬───────────────┘
                                     │ Verified Facts Only
                                     ▼
┌──────────────┐     Utterance      ┌───────────────────────────────┐
│              ├───────────────────►│       YAVURA Runtime          │
│   Customer   │                    │ (Intent, Truth Enforcement)   │
│              │◄───────────────────┤                               │
└──────────────┘     Natural Voice  └───────────────┬───────────────┘
                     Speech                         │ Grounded Prompting
                                                    ▼
                                    ┌───────────────────────────────┐
                                    │       AI Language Model       │
                                    │ (Natural phrasing & dialogue) │
                                    └───────────────────────────────┘
```

The platform adheres to a strict architectural invariant:
- **The AI model is responsible for linguistic comprehension and natural conversation generation.**
- **The application runtime and verified business systems are responsible for factual truth.**

### Non-Negotiable Rules
The AI model is **strictly prohibited from inventing or approximating**:
- Prices, fees, and surcharges
- Discounts, coupon codes, and promotional offers
- Referral programs and terms
- Product inventory and stock availability
- Real-time appointment slots
- Customer account balances or personal data
- Payment terms and refund policies
- Deadlines, eligibility criteria, and business guarantees

### Enforcement Mechanism
1. If verified business context exists: The runtime provides the verified facts to the AI context and validates that output claims align with the source knowledge.
2. If verified context is missing or unverified: The agent is forbidden from guessing. It must state that the information cannot be verified and transition either to **clarification** or **human escalation**.

---

## 3. Backend Architecture

Built on modern, asynchronous Python technologies:
- **Python 3.11+**: Type annotations, `dataclasses`, and `asyncio`.
- **FastAPI**: Asynchronous REST framework with automatic OpenAPI documentation.
- **Pydantic v2**: High-performance input/output validation and schema declaration.
- **SQLAlchemy 2.0 (Async)**: Modern async ORM pattern with connection pooling.
- **Alembic**: Zero-downtime database migration engine.
- **PostgreSQL (`asyncpg`)**: Relational storage engine with `aiosqlite` support for unit testing.

### Directory Structure & Modular Boundaries
```
backend/
├── app/
│   ├── api/             # HTTP routing layer (v1 endpoints)
│   ├── core/            # Configuration, logging, security, exception handling
│   ├── auth/            # Auth dependencies, ContextVar-based Tenant/User context
│   ├── database/        # Async session lifecycle, Base model, TenantAwareModel mixin
│   ├── models/          # Declarative entities (Tenant, User, AuditLog)
│   ├── schemas/         # Pydantic schemas (Health, Tenant, User, API envelopes)
│   ├── security/        # Tenant isolation filters, input sanitization, injection guards
│   ├── agents/          # AI provider abstractions, runtime turn engine, decision schemas
│   ├── conversations/   # Conversation session management and message history interfaces
│   ├── knowledge/       # Verified knowledge retrieval, grounding verification, vector storage
│   ├── tools/           # BaseTool, ToolRegistry, schema validator, execution sandbox
│   ├── voice/           # Voice session interfaces, barge-in detection, audio stream frames
│   ├── telephony/       # Telephony provider interfaces (inbound/outbound abstraction)
│   ├── integrations/    # CRM and webhook dispatch interfaces
│   ├── observability/   # Structured metrics, latency timers, audit logging
│   └── main.py          # FastAPI application factory and lifespan manager
├── migrations/          # Alembic migration scripts
├── tests/               # Comprehensive pytest suite
├── requirements.txt     # Locked production dependencies
├── pyproject.toml       # Build and tool configuration
└── Dockerfile           # Multi-stage production container
```

---

## 4. Multi-Tenant SaaS Isolation Model

Tenant isolation is enforced strictly on the backend. Frontend filtering is never relied upon for security.

### 1. Schema-Level Tenant Ownership
All tenant-owned database tables inherit from `TenantAwareModel`:
```python
class TenantAwareModel:
    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            GUID,
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
```

### 2. ContextVar Request Scoping
Each incoming asynchronous request establishes an isolated `TenantContext` stored in Python's `contextvars.ContextVar`. This context is populated from authenticated JWT claims or verified webhook signatures.

### 3. Query Filter Enforcement
All database queries for tenant resources must pass through `enforce_tenant_filter` or `enforce_current_tenant_filter`. If an operation is attempted without an active tenant context, a `TenantIsolationError` is raised immediately.

### 4. Cross-Tenant Barrier
Company A can never read, modify, or query Company B's users, agents, documents, call sessions, or analytics.

---

## 5. Security & Privacy Architecture

### Credential & Secret Management
- **Zero Hardcoded Secrets**: Secrets, database credentials, and API keys are strictly forbidden in code.
- **Pydantic `SecretStr`**: All sensitive settings use `SecretStr` to prevent accidental serialization into logs or responses.
- **`.env.example`**: Standardized environment template provided without live credentials. `.env` is ignored by Git.

### Sensitive Data Scrubbing
Structured logging uses `JsonFormatter` coupled with recursive dictionary sanitization (`sanitize_dict`). The following keys are automatically redacted:
- Passwords and hashes
- Bearer tokens and JWTs
- API keys
- Credit card / CVV numbers
- Telephony webhook signing secrets

### Tool Execution Safety Boundary
Future AI tool execution is locked down by `validate_tool_arguments`:
- Execution of arbitrary Python (`eval`, `exec`, `__import__`) is rejected.
- Shell command execution (`os.system`, `subprocess`, `powershell`, `bash`) is rejected.
- Arbitrary SQL injections (`DROP TABLE`, `UNION SELECT`) are blocked.
- Access to local file-system paths (`/etc/passwd`, `C:\Windows`) is blocked.
- Tools are executed strictly within the caller's `ToolExecutionContext` (tenant-scoped).

---

## 6. Modular AI Provider Abstraction

YAVURA does not couple business logic to any single AI vendor (OpenAI, Anthropic, Google, etc.).

```
┌────────────────────────────────────────────────────────┐
│                   YAVURA Runtime                       │
└───────────────────────────┬────────────────────────────┘
                            │ AIProviderInterface
             ┌──────────────┼──────────────┬─────────────┐
             ▼              ▼              ▼             ▼
       ┌───────────┐  ┌───────────┐  ┌───────────┐ ┌───────────┐
       │  OpenAI   │  │ Anthropic │  │  Gemini   │ │   Mock    │
       │  Adapter  │  │  Adapter  │  │  Adapter  │ │  Adapter  │
       └───────────┘  └───────────┘  └───────────┘ └───────────┘
```

- **`AIProviderInterface`**: Defines standard contracts for `generate_response()`, `stream_response()`, and `generate_embedding()`.
- **`AIProviderFactory`**: Dynamically provisions provider implementations based on configuration.
- **`MockAIProvider`**: Default provider for local development and unit tests, avoiding external costs and network dependencies.

---

## 7. Future Voice & Telephony Architecture

Real phone calling is intentionally NOT implemented in this initial foundation. Clean interfaces are established for future phases:

```
Customer 
   ↓
Telephony Provider (Twilio / LiveKit / Telnyx / SIP)
   ↓ TelephonyProviderInterface
Real-Time Voice Layer (AudioStreamInterface, BargeInHandler)
   ↓
YAVURA Agent Runtime (AgentRuntimeInterface)
   ↓
Knowledge + Tools + CRM (Tenant Isolated)
   ↓
Agent Decision (AgentDecision: SPEAK | CALL_TOOL | ESCALATE)
   ↓ Audio Synthesis
Telephony Provider
   ↓
Customer
```

### Components
- **`TelephonyProviderInterface`**: Pluggable provider adapter (handles inbound/outbound calls, webhook authentication).
- **`VoiceSessionInterface`**: Manages bi-directional audio frames (`AudioChunk`).
- **`BargeInHandlerInterface`**: Voice activity detection (VAD) enabling immediate interruption handling when the customer speaks during an agent response.

---

## 8. Future RAG & Verified Knowledge Architecture

```
Document Upload ─► Parsing & Sanitization ─► Chunking ─► Embedding
                                                            │
                                                            ▼
User Query ─► Retrieval (Tenant Filtered) ◄── Vector Store (pgvector)
                   │
                   ▼
       Verified Knowledge Items
                   │
                   ▼
        Grounding Verification ──► [Fail: Missing Fact] ──► Clarify / Escalate
                   │
             [Pass: Grounded]
                   │
                   ▼
            Natural Response
```

- **pgvector Extension**: Pre-configured in PostgreSQL container (`init-pgvector.sql`).
- **`VerifiedKnowledgeItem`**: Atomic, verified unit of knowledge with `VerificationStatus` (`verified`, `unverified`, `conflicting`).
- **`GroundingVerifierInterface`**: Validates candidate answers against verified knowledge items before synthesis.

---

## 9. Future Tool Architecture

All business tools callable by AI agents are governed by `ToolRegistry`:
- Tools must declare a strict Pydantic `input_schema` and `output_schema`.
- Every tool call receives a `ToolExecutionContext` containing `tenant_id`, `session_id`, and `user_id`.
- Arguments are validated before execution; unauthorized operations or arguments that do not conform to schema are rejected.
- Every invocation generates an audit trail entry.

---

## 10. Database Foundation & Entities

Initialized with SQLAlchemy 2.0 Declarative Models and Alembic migrations:
- **`tenants`**: Enterprise tenant account entity (`id`, `name`, `slug`, `is_active`, `tier`, timestamps).
- **`users`**: Tenant-scoped user accounts with bcrypt hashed passwords and RBAC roles.
- **`audit_logs`**: Immutable security and audit logging tracking tenant actions and tool executions.

---

## 11. Testing & Quality Assurance Philosophy

Testing is built into the foundation from day one:
- **`test_health.py`**: Validates infrastructure health check endpoint and security headers.
- **`test_config.py`**: Verifies configuration loading and secret masking.
- **`test_tenant_isolation.py`**: Verifies strict multi-tenant database filtering and isolation.
- **`test_factual_truth_principle.py`**: Validates that unverified business inquiries transition to clarification/escalation rather than hallucinated facts.
- **`test_tool_security.py`**: Validates tool input sanitization and prevention of command/code injection.
- **`test_ai_provider_abstraction.py`**: Validates modular AI provider contracts.
