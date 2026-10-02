# YAVURA AI Tool & Action Layer Architecture (Phase 5)

> **Document Version:** 1.0.0
> **Status:** Production Architecture
> **Scope:** Tool Models, Deterministic Registry, 15-Step Execution Pipeline, SSRF Defenses, Credential Architecture, Idempotency, Timeouts, Audit Logging, and Agent Runtime Integration.

---

## 1. Core Architectural Principle

YAVURA enforces a strict, non-negotiable architectural invariant:

> **"LLM decides whether a tool is useful.**
> **The server decides whether the tool is allowed.**
> **The tool implementation decides what actually happens.**
> **The database and verified tool results remain the source of truth."**

The LLM is strictly an untrusted client that can **request** a capability, but has **zero** direct execution privileges. The LLM cannot:
- execute Python code, shell commands, or SQL queries
- dynamically import libraries or access the filesystem
- construct arbitrary target URLs or bypass network filters
- read or manipulate environment variables, keys, or secrets
- bypass tenant isolation or invoke unassigned capabilities.

---

## 2. Tool Domain Models

All tool capabilities are persisted and managed as tenant-scoped entities:

### 2.1 `ToolDefinition` (`tool_definitions` table)
Represents an approved, registered capability belonging to a specific tenant:
- `id`: Unique identifier (UUID).
- `tenant_id`: Mandatory tenant ownership foreign key.
- `name`: Unique alphanumeric identifier per tenant (`uq_tool_tenant_name`).
- `display_name`, `description`: Human and machine-readable metadata.
- `tool_type`: `INTERNAL` (mapped to server-side Python classes) or `HTTP_API` (controlled external REST/webhook).
- `version`: Version identifier (default `1.0.0`).
- `input_schema`: JSON Schema defining validated parameters.
- `output_schema`: JSON Schema defining structured response format.
- `configuration`: Non-secret runtime settings (base URLs, path templates, timeout overrides, and `CredentialReference`). Plaintext secrets are strictly prohibited.
- `is_active`: Operational toggle; deactivated tools immediately reject execution.

### 2.2 `AgentTool` (`agent_tools` table)
Explicit authorization link between an Agent and a ToolDefinition:
- Enforces an explicit least-privilege boundary: An agent can **only** invoke tools explicitly assigned to it and marked `enabled=True`.
- Unique constraint: `uq_agent_tool (agent_id, tool_id)`.
- Cross-tenant assignment is strictly prevented.

### 2.3 `ToolExecution` (`tool_executions` table)
Immutable audit trail of every tool execution:
- Captures `tenant_id`, `agent_id`, `conversation_id`, `message_id`, `tool_id`, `tool_name`, `tool_version`.
- Records outcome status (`SUCCESS`, `FAILED`, `TIMEOUT`, `BLOCKED`, `RATE_LIMITED`, `VALIDATION_FAILED`).
- Stores sanitized inputs and outputs (`validated_input`, `sanitized_output`) with deep recursive secret scrubbing.
- Records execution latency (`duration_ms`), correlation ID, and idempotency key.

---

## 3. Tool Registry (`ToolRegistry`)

Internal tools map to explicit, pre-compiled server-side classes extending `BaseTool`:
- **Deterministic Resolution:** Lookup occurs via registered name in an in-memory dictionary.
- **No Dynamic Code Loading:** Zero `eval()`, zero `exec()`, and zero dynamic module imports based on database input.
- **Built-in Capabilities:**
  - `LookupCustomerTool` (`lookup_customer`): Safely retrieves customer profile, status, and tier without data leaks.
  - `CreateFollowupTool` (`create_followup`): Schedules a customer callback/followup ticket with idempotency support.

---

## 4. 15-Step Secure Execution Pipeline (`ToolExecutionService`)

Every tool invocation passes through a central, non-bypassable 15-step pipeline:

```text
 1. Authenticate Request & Actor Context
                 ↓
 2. Resolve Tenant Identity (from verified session, never client body)
                 ↓
 3. Resolve Agent Identity & Status
                 ↓
 4. Verify Agent belongs to Tenant and is ACTIVE
                 ↓
 5. Verify Tool belongs to Tenant
                 ↓
 6. Verify Tool is ACTIVE
                 ↓
 7. Verify Agent is Explicitly Assigned the Tool (AgentTool.enabled == True)
                 ↓
 8. Verify Caller/Agent Permission (RBAC: tools:execute)
                 ↓
 9. Validate Input against Pydantic schema and injection filters
                 ↓
10. Apply Security Policy (SSRF check for HTTP tools)
                 ↓
11. Resolve Approved Implementation (Internal or HttpApiTool)
                 ↓
12. Verify Idempotency (replay cached result if identical payload)
                 ↓
13. Check Tenant-Scoped Rate Limits
                 ↓
14. Execute with Bounded Timeout & Retry Policy
                 ↓
15. Persist Sanitized ToolExecution Audit Record & Return Structured ToolResult
```

---

## 5. HTTP API Tool & SSRF Defenses

### 5.1 Controlled HTTP Execution (`HttpApiTool`)
External APIs cannot be used as unrestricted proxies:
- The server determines the destination `base_url` and parameterized `path_template`.
- The LLM can only supply validated parameter values (e.g. `customer_id: "123"`). It can **never** supply arbitrary target URLs.

### 5.2 Multi-Layer SSRF Defense (`app.tools.ssrf`)
Every destination URL is validated before an HTTP connection is established:
1. **Scheme Restrictions:** Only `https://` is permitted in production. Unencrypted `http://` is blocked. Non-HTTP schemes (`file://`, `ftp://`, `gopher://`, `dict://`, etc.) are unconditionally rejected.
2. **Hostname Validation:** Hostnames matching internal patterns (`localhost`, `metadata.google.internal`, `.local`, `.internal`, `.corp`, `.lan`) are blocked.
3. **DNS Pre-Resolution & IP Inspection:**
   - Hostnames are resolved via `socket.getaddrinfo`.
   - Every resolved IP is validated against `ipaddress.ip_address`:
     - Loopback (`127.0.0.0/8`, `::1`)
     - Private RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) and IPv6 Unique Local (`fc00::/7`)
     - Link-local (`169.254.0.0/16`, `fe80::/10`)
     - Cloud Metadata IP (`169.254.169.254`, `fd00:ec2::254`)
     - Multicast, unspecified, and reserved ranges.
4. **Honest Architectural Limitation on DNS Rebinding:**
   While pre-resolution detects malicious records, DNS rebinding could theoretically occur if a server resolves to a public IP during pre-check and returns a private IP upon connection. Complete mitigation requires pinning the resolved IP in custom socket transport layers or using egress gateway firewalls.

---

## 6. Credential & Secret Architecture

- Plaintext secrets are **never** stored in `ToolDefinition.configuration`.
- Configurations store non-sensitive `CredentialReference(credential_id, provider_type, auth_header_name, auth_scheme)`.
- `CredentialProvider` interface resolves secrets server-side at execution time (from environment variables or secret vaults).
- `scrub_secrets` performs deep recursive redaction on keys matching `(secret|password|token|key|authorization|bearer|cookie|credential)`.
- Secrets are scrubbed from error messages, logs, audit trails, and client API responses.

---

## 7. Idempotency & Concurrency

- Side-effecting tools accept an `idempotency_key`.
- If an existing execution is found for `(tenant_id, tool_id, idempotency_key)`:
  - If input payload matches: Returns cached `ToolResult` (`idempotent_cached=True`).
  - If input payload differs: Raises `ToolIdempotencyConflictError`.
- Keys expire after `TOOL_IDEMPOTENCY_EXPIRE_HOURS` (default 24 hours).

---

## 8. Timeouts, Retries, and Rate Limiting

- **Bounded Timeouts:** Configurable per tool (default 10s). Applied directly to the underlying HTTP transport. Triggers `ToolTimeoutError` and logs `TIMEOUT` audit status.
- **Controlled Retries:**
  - Retryable: Transient network timeouts, HTTP 502, 503, 504.
  - Non-retryable: HTTP 4xx, validation failures, authorization denials, SSRF blocks, and non-idempotent operations without idempotency keys.
  - Bounded to max 2 retries with exponential backoff.
- **Tenant-Aware Rate Limiting:** Enforces `TOOL_RATE_LIMIT_PER_MINUTE` (default 120 calls/min) per tenant. Exceeding quota raises `ToolRateLimitError` and logs `RATE_LIMITED` audit status.

---

## 9. Agent Runtime Integration & Tool Result Grounding

- In conversational turns, available tools assigned to the agent are declared in the prompt context.
- The model can request tool execution using structured format.
- A **bounded tool-call loop** (`MAX_TOOL_CALLS_PER_TURN = 3`) prevents infinite recursion.
- **Tool Result Delimitation & Sanitization:** Output is enclosed in `<tool_result name="..." success="...">` with tag neutralization (`</tool_result>`, `<system>`, `<instructions>`), treating external tool outputs strictly as read-only data to defeat prompt injection attacks.
- **Factual Grounding Invariant:** If a tool fails or returns no record, the agent declares the information unavailable and offers fallback/escalation. The agent is strictly prohibited from fabricating business facts.
