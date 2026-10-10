# Implementation Phases & Development Roadmap

> **Platform:** YAVURA / Calling-agent  
> **Repository:** `spoorthik708/Calling-agent`  
> **Core Objective:** Enterprise Multi-Tenant AI Conversational Voice Agent SaaS Platform

---

## Overview of Development Phases

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: Production Foundation & Multi-Tenant Infrastructure                           │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 2: Authentication, Tenant Onboarding & RBAC System                               │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 3: Knowledge Management, Embeddings & RAG Grounding Engine                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 4: Conversational AI Agent Engine & State Machine Runtime                         │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 5: Secure Tool Execution Sandbox & Action Integration Layer                      │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 6: Real-Time Voice Pipeline (STT, TTS, VAD, Barge-In & Telemetry)                │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 7: Telephony Routing, Call Dispatcher & Analytics Dashboard (Roadmap)             │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Production Foundation & Multi-Tenant Infrastructure (Completed ✅)

### Objective
Establish the foundational asynchronous web application, database schema, multi-tenant isolation primitives, containerization, and baseline security.

### Deliverables & Modules
- **Async Backend Stack**: FastAPI, SQLAlchemy 2.0 (Async), `asyncpg`, Alembic migrations.
- **Database Schema**: PostgreSQL 16 with `pgvector` extension setup (`infrastructure/docker/postgres/init-pgvector.sql`).
- **Multi-Tenant Isolation**: `TenantAwareModel` SQLAlchemy mixin enforcing tenant ID constraints on all query paths.
- **Configuration & Security**: Pydantic `SecretStr` masking, custom exception hierarchy (`YavuraException`), CORS & security headers middleware.
- **Frontend Stack**: Next.js 14 App Router, Tailwind CSS, TypeScript setup (`frontend/`).
- **Containerization**: `docker-compose.yml` orchestrating backend, frontend, and PostgreSQL container instances.

### Key Files
- [`backend/app/database/base.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/database/base.py)
- [`backend/app/core/config.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/core/config.py)
- [`backend/app/core/exceptions.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/core/exceptions.py)
- [`docker-compose.yml`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/docker-compose.yml)

---

## Phase 2: Authentication, Tenant Onboarding & RBAC (Completed ✅)

### Objective
Provide enterprise-grade identity, onboarding flows, token management, role-based authorization, and rate limiting.

### Deliverables & Modules
- **Identity & Password Security**: Argon2 password hashing, JWT access token generation, and secure refresh token rotation.
- **Tenant Onboarding API**: Self-serve & admin tenant registration endpoints with audit logging.
- **Role-Based Access Control (RBAC)**: Roles (`Admin`, `Manager`, `Operator`) with fine-grained endpoint authorization guards.
- **Rate Limiting & Throttling**: Memory and Redis-backed request rate limiters to prevent API abuse and brute-force attacks.

### Key Files & Endpoints
- Endpoints: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `GET /api/v1/tenants/me`
- [`backend/app/auth/rbac.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/auth/rbac.py)
- [`backend/app/auth/service.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/auth/service.py)
- [`backend/app/auth/throttling.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/auth/throttling.py)
- Migration: `0002_auth_and_rbac.py`

---

## Phase 3: Knowledge Management, Embeddings & RAG Engine (Completed ✅)

### Objective
Implement verified business knowledge storage, document extraction, vector indexing, and factual grounding to eliminate AI hallucination.

### Deliverables & Modules
- **Document Ingestion**: Support for text, PDF, and Markdown ingestion into structured knowledge bases.
- **Chunking & Vector Embeddings**: Semantic text chunker and embedding pipeline stored using `pgvector`.
- **RAG Retrieval Engine**: Top-k similarity vector retrieval with source citation tracking.
- **Factual Grounding Verifier**: Strict rule engine preventing the model from inventing pricing, inventory, or policies not present in verified knowledge.

### Key Files & Endpoints
- Endpoints: `POST /api/v1/knowledge`, `POST /api/v1/knowledge/{id}/documents`, `POST /api/v1/knowledge/query`
- [`backend/app/knowledge/chunking.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/knowledge/chunking.py)
- [`backend/app/knowledge/embeddings.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/knowledge/embeddings.py)
- [`backend/app/knowledge/retrieval.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/knowledge/retrieval.py)
- Migration: `0003_knowledge_and_rag.py`

---

## Phase 4: Conversational AI Agent Engine & State Machine (Completed ✅)

### Objective
Build the agent orchestration runtime, conversation turn manager, multi-lingual prompt manager, and turn state machine.

### Deliverables & Modules
- **Provider-Agnostic AI Abstraction**: `AIProviderInterface` supporting OpenAI, Anthropic, and custom LLM runtimes.
- **Agent Lifecycle & Configuration**: Persona definition, temperature, model selection, and prompt template management.
- **Conversation State Engine**: Turn history persistence, token window truncation, and idempotent message processing.
- **Prompt Injection Defense**: Input sanitizer detecting prompt extraction and jailbreak attempts before hitting the LLM.

### Key Files & Endpoints
- Endpoints: `POST /api/v1/agents`, `POST /api/v1/conversations`, `POST /api/v1/conversations/{id}/turns`
- [`backend/app/agents/llm_provider.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/agents/llm_provider.py)
- [`backend/app/agents/runtime_service.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/agents/runtime_service.py)
- [`backend/app/conversations/memory.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/conversations/memory.py)
- Documentation: [`docs/agent-runtime.md`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/docs/agent-runtime.md)

---

## Phase 5: Secure Tool Execution Sandbox & Actions (Completed ✅)

### Objective
Enable AI agents to execute actions (CRM sync, HTTP API calls, appointment booking) safely without compromising system security.

### Deliverables & Modules
- **Tool Registry**: Dynamic assignment of tools to specific agents.
- **Input Argument Validation**: Pydantic schema validation for tool function calls.
- **SSRF Protection & Sandbox**: IP blocking, private network range restrictions (blocking 10.0.0.0/8, 127.0.0.1, 169.254.169.254), and payload sanitization.
- **Execution Audit**: Full logging of tool call inputs, outputs, execution duration, and error codes.

### Key Files & Endpoints
- Endpoints: `POST /api/v1/tools`, `POST /api/v1/tools/execute`, `GET /api/v1/tools/executions`
- [`backend/app/tools/ssrf.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/tools/ssrf.py)
- [`backend/app/tools/http_tool.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/tools/http_tool.py)
- [`backend/app/tools/service.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/tools/service.py)
- Documentation: [`docs/tool-runtime.md`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/docs/tool-runtime.md)

---

## Phase 6: Real-Time Voice Pipeline & Telemetry Engine (Completed ✅)

### Objective
Construct the low-latency streaming voice pipeline capable of handling speech-to-text, text-to-speech, voice activity detection, barge-in interruptions, and multi-lingual voice streaming across **English, Hindi, Telugu, Tamil, and Malayalam**.

### Deliverables & Modules
- **Supported Languages**: English (`en`), Hindi (`hi`), Telugu (`te`), Tamil (`ta`), and Malayalam (`ml`).
- **Speech-to-Text (STT)**: Streaming WebSocket audio transcription.
- **Text-to-Speech (TTS)**: Low-latency streaming voice synthesis with sentence chunking.
- **Voice Activity Detection (VAD) & Turn Detection**: Real-time energy and model-based VAD to distinguish active speech from background noise.
- **Barge-in Interruption Handler**: Immediate cancellation of TTS playback when user starts speaking mid-agent turn.
- **Voice Telemetry**: Millisecond-level tracking of First Byte Latency, VAD delay, STT latency, and TTS synthesis time.

### Key Files & Endpoints
- Endpoints: `WS /api/v1/voice/stream`, `POST /api/v1/voice/sessions`
- [`backend/app/voice/pipeline.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/voice/pipeline.py)
- [`backend/app/voice/vad.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/voice/vad.py)
- [`backend/app/voice/stt.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/voice/stt.py)
- [`backend/app/voice/tts.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/voice/tts.py)
- [`backend/app/voice/telemetry.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/voice/telemetry.py)
- Documentation: [`docs/voice-runtime.md`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/docs/voice-runtime.md)

---

## Phase 7: Telephony Routing, Call Dispatcher & Analytics (Completed ✅)

### Objective
Connect the streaming voice runtime directly to PSTN/SIP telephony networks (Twilio, Vonage, Plivo) for inbound/outbound automated calling campaigns, lifecycle tracking, and real-time analytics.

### Deliverables & Modules
- **Telephony Provider Interface**: Pluggable vendor-neutral `TelephonyProviderInterface` with `TwilioTelephonyProvider` and `MockTelephonyProvider`.
- **Inbound Call Webhooks**: Authenticated webhook processing, active agent resolution, TwiML Media Stream connection, and persistent `CallSession` creation.
- **Outbound Call Dispatcher**: Outbound calling API enforcing tenant calling permissions, agent validation, idempotency, and retries.
- **Call State Machine & Webhooks**: Real-time lifecycle tracking (`queued` -> `ringing` -> `in_progress` -> `completed`/`failed`) and voice pipeline session termination.
- **Telephony Analytics Engine**: Call volume metrics, total/average call duration calculation, completion rates, and breakdown by direction.

### Key Files & Endpoints
- Endpoints: `POST /api/v1/telephony/inbound/webhook`, `POST /api/v1/telephony/outbound`, `POST /api/v1/telephony/status/webhook`, `GET /api/v1/telephony/calls/{id}`, `GET /api/v1/telephony/analytics`
- [`backend/app/telephony/provider.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/telephony/provider.py)
- [`backend/app/telephony/service.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/telephony/service.py)
- [`backend/app/telephony/models.py`](file:///c:/Users/spoor/OneDrive/Desktop/ai%20calling%20agent/backend/app/telephony/models.py)
- Migration: `0007_telephony_call_sessions.py`

---

## Verification & Test Suite Summary

Every phase contains corresponding pytest suites:

| Phase | Test Suite File | Coverage Target |
| :--- | :--- | :--- |
| **Phase 1** | `test_health.py`, `test_config.py`, `test_tenant_isolation.py` | Infrastructure & Tenant Boundaries |
| **Phase 2** | `test_auth_registration.py`, `test_auth_login_jwt.py`, `test_rbac_and_permissions.py` | Auth & Security Controls |
| **Phase 3** | `test_knowledge_base_crud.py`, `test_document_ingestion_and_extraction.py`, `test_rag_retrieval_and_citations.py` | Knowledge & Grounding |
| **Phase 4** | `test_agent_crud_and_lifecycle.py`, `test_agent_runtime_grounding_and_rag.py`, `test_agent_security_and_prompt_injection.py` | Agent Machine Engine |
| **Phase 5** | `test_tool_crud_and_lifecycle.py`, `test_tool_execution_pipeline.py`, `test_tool_ssrf_and_security.py` | Sandbox & Tool Security |
| **Phase 6** | `test_voice_pipeline_orchestration.py`, `test_voice_vad_and_turn_detection.py`, `test_voice_interruption_and_stale_audio.py`, `test_voice_hardening_and_adversarial.py` | Low-latency Voice, Concurrency & Security Gate |
| **Phase 7** | `test_telephony_inbound_outbound.py` | Inbound/Outbound Telephony, Webhooks, Isolation & Analytics |

