# YAVURA AI Agent & Conversation Runtime Architecture (Phase 4)

> **Document Version:** 1.0.0
> **Status:** Production Architecture
> **Scope:** Tenant-Owned AI Agents, Conversation Runtime, Factual Grounding, Idempotency, Concurrency, and Prompt Security

---

## 1. Architectural Invariant

YAVURA adheres to a strict, non-negotiable architectural invariant:

> **The LLM controls conversation. The database and authorized tools control facts.**

Under no circumstances is the LLM permitted to fabricate, extrapolate, or approximate business facts, such as:
- Pricing, rates, fees, discounts, and refund policies
- Eligibility criteria, warranties, and terms of service
- Product specifications, inventory, and delivery timelines
- Customer account details, historical orders, or appointment availability.

If verified knowledge exists in an explicitly attached Knowledge Base, it is retrieved and presented as read-only factual grounding data. If verified knowledge is unavailable or insufficient, the runtime instructs the model to declare the information unavailable and offer human escalation or clarification.

---

## 2. End-to-End Execution Flow

```text
                  Authenticated Request (JWT)
                             ↓
                   Tenant Context Extraction
                             ↓
                   RBAC Authorization Check
                             ↓
              Concurrency Lock (with_for_update)
                             ↓
                     Idempotency Check
               (Hit -> return cached response)
                             ↓
                   Agent Status Verification
                             ↓
                    Persist User Message
                   (Sequence Number: N)
                             ↓
             Authorized Knowledge Base Retrieval
         (ONLY from explicitly attached agent KBs)
                             ↓
                 Bounded Context Assembly
    [System Invariants + Verified Knowledge + Bounded History + User Utterance]
                             ↓
                    LLM Provider Call
         (Server-Side API Key / In-Memory Mock Guard)
                             ↓
                 Response Validation & Safety
       (Fallback substitution if empty/provider failure)
                             ↓
                  Persist Assistant Message
                  (Sequence Number: N + 1)
                             ↓
                   Audit & Telemetry Emit
                             ↓
            Tenant-Safe Response + Citations
```

---

## 3. Core Components

### 3.1 Tenant-Owned Agents (`Agent`)
- Belongs strictly to exactly one tenant. Cross-tenant agent access is blocked at the database level.
- Configurable parameters:
  - `system_prompt`: High-level persona and purpose instructions.
  - `default_language`: Default ISO language code (e.g. `en`, `hi`, `te`, `ta`).
  - `llm_provider`: Approved server-side provider identifier (`mock`, `openai`).
  - `llm_model`: Approved model identifier (`gpt-4o-mini`, etc.).
  - `temperature`: Bounded between `0.0` and `2.0`.
  - `max_output_tokens`: Bounded between `16` and `8192`.
  - `fallback_message`: Guaranteed deterministic fallback message when knowledge is missing or provider fails.
  - `status`: Lifecycle states `ACTIVE`, `INACTIVE`, `ARCHIVED`. Deleting an agent marks it `ARCHIVED` to preserve historical message integrity.

### 3.2 Agent Knowledge Base Associations (`AgentKnowledgeBase`)
- **Explicit Authorization Boundary**: An agent **never** automatically searches all tenant knowledge bases. It can ONLY retrieve from knowledge bases explicitly attached via `agent_knowledge_bases`.
- Cross-tenant attachment is strictly prohibited and validated on both the agent and knowledge base foreign keys.

### 3.3 Conversations & Messages (`Conversation`, `Message`)
- **Channel Restriction**: Phase 4 strictly supports `text` and `api` channels. Telephony, WebRTC, SIP, and voice channels are explicitly deferred.
- **Monotonic Sequence Numbering**: Message turns enforce `uq_message_conversation_sequence` (`sequence_number`), ensuring deterministic, tamper-proof ordering.
- **Bounded Conversation Memory**: `ConversationMemoryManager` preserves recent turns up to `MAX_CONVERSATION_HISTORY_MESSAGES` (default 20) and character limits, without ever truncating system instructions or verified knowledge facts.

### 3.4 Provider Abstraction (`LLMProvider`)
- Clean asynchronous protocol `LLMProvider.generate()`.
- Supports `MockLLMProvider` (with automatic production guards) and `OpenAILLMProvider` (with secure server-side credentials).
- Production mode strictly rejects mock providers during startup and runtime.
- API keys are never stored in database tables or exposed to the frontend.

### 3.5 Grounding & Prompt-Injection Resistance
- Context structure:
  ```text
  SYSTEM INSTRUCTIONS
         ↓
  RUNTIME FACTUAL TRUTH INVARIANTS
         ↓
  VERIFIED BUSINESS KNOWLEDGE (READ-ONLY GROUNDING DATA)
  <verified_fact source="..." chunk="...">
  [delimiter-neutralized content]
  </verified_fact>
         ↓
  BOUNDED CONVERSATION HISTORY
         ↓
  CURRENT USER MESSAGE
  ```
- All untrusted document chunks pass through delimiter neutralization, stripping embedded closing tags (`</verified_fact>`, `<system>`, `<instructions>`), preventing prompt injection attacks from hijacking runtime directives.

### 3.6 Idempotency Engine (`IdempotencyRecord`)
- Supports `Idempotency-Key` header for turn executions.
- Scoped strictly by `(tenant_id, idempotency_key, endpoint)`.
- Replaying the identical request returns the cached response without creating duplicate user or assistant messages.
- Reusing an idempotency key with a differing payload triggers `409 Conflict`.

### 3.7 Concurrency & Row-Level Locking
- Simultaneous message executions on the same conversation acquire a row-level lock (`with_for_update()` in PostgreSQL).
- Message sequence numbers are calculated within the locked transaction, eliminating sequence race conditions and history corruption.

### 3.8 Tool Execution Boundary
- For Phase 4, the `ToolRegistry` contains zero tools, enforcing that no arbitrary code, shell commands, or external APIs can be invoked by the LLM.
- Future tools will require explicit registration, Pydantic schema validation, and tenant-scoped authorization.

---

## 4. Role-Based Access Control (RBAC) Matrix

| Permission | Role: OWNER | Role: ADMIN | Role: MEMBER | Description |
| :--- | :---: | :---: | :---: | :--- |
| `agents:read` | Yes | Yes | Yes | List and view tenant agents |
| `agents:create` | Yes | Yes | No | Create tenant agents |
| `agents:update` | Yes | Yes | No | Update agent prompts and parameters |
| `agents:delete` | Yes | Yes | No | Archive tenant agents |
| `agents:manage_knowledge` | Yes | Yes | No | Attach/detach knowledge bases to/from agents |
| `agents:run` | Yes | Yes | Yes | Execute conversational turns |
| `conversations:read` | Yes | Yes | Yes | View conversation sessions and messages |
| `conversations:create` | Yes | Yes | Yes | Start new conversation sessions |
| `conversations:delete` | Yes | Yes | No | Delete conversation sessions |

---

## 5. Security & Observability

- **No Secrets in Responses or Logs**: System prompts and secrets are never returned in conversational turn responses.
- **Audit Logging**: All agent creations, updates, archivals, KB attachments/detachments, and turn executions are persisted to `audit_logs`.
- **Latency & Token Accounting**: Turn executions capture retrieval latency, LLM latency, total latency, prompt tokens, and completion tokens.
- **Data Retention Ready**: All conversations and messages include timezone-aware timestamps and status fields to support future automated data retention schedulers.
