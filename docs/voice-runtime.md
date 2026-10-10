# YAVURA Real-Time Voice Intelligence Layer Architecture (Phase 6)

> **Document Version:** 1.0.0
> **Status:** Production Architecture
> **Scope:** Voice Pipeline, Audio Framing & Buffers, Voice Session Lifecycle, VAD & Turn Detection, STT/TTS Abstractions, Real-Time Text Chunking, Barge-in Interruption, Stale Audio Protection, Telemetry, RBAC, and Production Safety.

---

## 1. Core Architectural Invariant

YAVURA's real-time voice intelligence layer adheres to a strict foundational invariant:

> **"Voice is a multimodal transport layer for intelligence, not a shortcut around business truth.**
> **The voice pipeline streams audio and text in real time, but all conversational reasoning,**
> **factual grounding, and tool execution remain governed by the verified Agent Runtime."**

The voice system enforces the following core guarantees:
1. **Channel-Agnostic & Vendor-Neutral**: The pipeline operates strictly on normalized audio frames (`PCM_S16LE`, `LINEAR16`, `MULAW`, `ALAW`, `OPUS`), decoupling turn detection, VAD, STT, and TTS from downstream transport channels (WebSockets, WebRTC, SIP/telephony).
2. **Immediate Interruption & Barge-In**: User speech detected while the assistant is speaking immediately triggers asynchronous cancellation of downstream generation/synthesis tasks, drains all pending audio buffers, increments the turn generation ID, and drops stale chunks.
3. **Factual Truth Preservation**: Voice responses reuse Phase 4 `AgentRuntimeService` and Phase 5 Tool execution pipelines. Speculative hallucination without verified context is strictly prohibited.
4. **Zero Mock Fallback in Production**: In `ENVIRONMENT=production`, all mock STT, TTS, VAD, and LLM implementations are strictly rejected at startup and runtime with validation errors.
5. **Multi-Language Normalization**: Explicit language routing and normalization across English (`en`), Hindi (`hi`), Telugu (`te`), and Tamil (`ta`).

---

## 2. Voice Pipeline Architecture

The end-to-end real-time audio pipeline executes in a streaming loop:

```
[ Inbound Audio Stream ]
           │
           ▼
[ Audio Transport / Ingest ] ──▶ [ BoundedAudioBuffer ] (Memory overflow protection)
           │
           ▼
[ VAD (Voice Activity Detection) ] ──▶ [ TurnDetector ] (Stateful silence & speech tracking)
           │
           ├──▶ [ Barge-In Interruption ] ──▶ (Cancel LLM/TTS, discard output audio, bump generation_id)
           │
           ▼ (Turn Complete Event)
[ STT (Speech-to-Text Streaming) ] ──▶ Transcribed User Text
           │
           ▼
[ Phase 4 AgentRuntimeService & Phase 5 Tools ] ──▶ Verified LLM Token Stream
           │
           ▼
[ Streaming Text Chunker ] (Sentence & clause boundary detection)
           │
           ▼
[ TTS (Text-to-Speech Streaming) ] ──▶ Synthesized Audio Chunks (stamped with generation_id)
           │
           ▼
[ Stale Chunk Filter ] (Drops chunks with generation_id < current_generation_id)
           │
           ▼
[ Outbound Voice Transport ] ──▶ [ Client Speaker / Audio Sink ]
```

---

## 3. Audio Abstractions & Memory Bounds

### 3.1 `AudioFrame`
The fundamental unit of audio exchange across the pipeline:
- `payload`: Raw binary audio bytes.
- `sequence_number`: Monotonically increasing sequence index within the session.
- `encoding`: `AudioEncoding` enum (`pcm_s16le`, `linear16`, `mulaw`, `alaw`, `opus`).
- `sample_rate`: Sample rate in Hz (default: `16000`).
- `channels`: Channel count (default: `1` mono).
- `bit_depth`: Bit depth per sample (default: `16`).
- `duration_ms`: Duration computed dynamically or passed explicitly:
  $$\text{duration\_ms} = \frac{\text{len(payload)}}{\text{sample\_rate} \times \text{channels} \times (\text{bit\_depth} / 8)} \times 1000$$

### 3.2 `BoundedAudioBuffer`
In-memory queue designed with strict defenses against memory bloat and denial-of-service attacks:
- `max_bytes`: Configurable byte cap (default: `5,242,880` bytes / 5 MB).
- `max_frames`: Configurable frame cap (default: `1,000` frames).
- Overflow Behavior: Raises `AudioBufferOverflowError` if pushed frames exceed capacity, preventing unbounded server memory exhaustion.
- Thread-safe operations: `push()`, `drain()`, `clear()`, `get_all_bytes()`.

---

## 4. Voice Session Lifecycle & State Machine

Every voice session is tracked in the `voice_sessions` database table and in active pipeline memory:

```
                     ┌──────────────────┐
                     │   INITIALIZING   │
                     └─────────┬────────┘
                               │ (Session Started)
                               ▼
        ┌──────────────────────────────────────────────┐
        │                                              │
        │                  LISTENING                   │◀────────┐
        │                                              │         │
        └───────┬──────────────────────────────▲───────┘         │
                │                              │                 │
                │ (Turn Complete)              │ (Turn Done)     │
                ▼                              │                 │
        ┌───────────────┐              ┌───────┴───────┐         │
        │   THINKING    │─────────────▶│   SPEAKING    │         │
        └───────┬───────┘ (LLM Stream) └───────┬───────┘         │
                │                              │                 │
                │ (User Speaks)                │ (User Speaks)   │
                └──────────────┐        ┌──────┘                 │
                               ▼        ▼                        │
                         ┌─────────────┐                         │
                         │ INTERRUPTED │─────────────────────────┘
                         └──────┬──────┘ (Drain & Resume Listening)
                                │
                 (Error)        │        (Normal End)
                    ┌───────────┴───────────┐
                    ▼                       ▼
            ┌───────────────┐       ┌───────────────┐
            │    FAILED     │       │   COMPLETED   │
            └───────────────┘       └───────────────┘
```

### State Machine Rules (`validate_status_transition`):
- `INITIALIZING` -> `LISTENING`, `FAILED`
- `LISTENING` -> `THINKING`, `INTERRUPTED`, `COMPLETED`, `FAILED`
- `THINKING` -> `SPEAKING`, `INTERRUPTED`, `FAILED`, `COMPLETED`
- `SPEAKING` -> `LISTENING`, `INTERRUPTED`, `FAILED`, `COMPLETED`
- `INTERRUPTED` -> `LISTENING`, `THINKING`, `COMPLETED`, `FAILED`
- `COMPLETED` -> Terminal state (no further transitions)
- `FAILED` -> Terminal state (no further transitions)

Invalid transitions raise `VoiceSessionStateError`.

---

## 5. Voice Activity Detection & Turn Detection

### 5.1 Voice Activity Detection (`VADInterface`)
Decoupled VAD layer processing discrete audio frames:
- `EnergyVAD`: Computes Root-Mean-Square (RMS) amplitude normalized to 16-bit PCM scale. Flags frames as speech if RMS exceeds `energy_threshold` (default: `0.02`).
- `MockVAD`: Test and staging implementation with programmatic speech state injection. Strictly prohibited in production.

### 5.2 Turn Detection (`TurnDetector`)
Stateful turn boundary detector tracking silence windows and speech activity:
- `speech_pad_ms`: Buffer window to prevent clipping word onsets (default: `200ms`).
- `silence_timeout_ms`: Trailing silence required to trigger turn completion (default: `600ms`).
- `min_speech_duration_ms`: Minimum speech duration required to reject background clicks/coughs (default: `250ms`).
- Emits events:
  - `TurnEvent.USER_STARTED_SPEAKING`
  - `TurnEvent.USER_CONTINUES`
  - `TurnEvent.USER_STOPPED_SPEAKING`
  - `TurnEvent.TURN_COMPLETE`

---

## 6. Barge-In Interruption & Stale Audio Protection

When `USER_STARTED_SPEAKING` occurs while session state is `SPEAKING` or `THINKING`:

1. **Immediate Cancellation**: Active asyncio tasks generating LLM tokens or TTS audio are cancelled via `task.cancel()`.
2. **Buffer Purge**: Inbound and outbound audio buffers are immediately cleared.
3. **Generation ID Increment**: `session.generation_id` is atomically incremented by `1`.
4. **Stale Audio Drop**: Any in-flight TTS chunks or transport messages bearing an older `generation_id` are dropped at the sink barrier.
5. **State Transition**: Session transitions to `INTERRUPTED`, logs `interruption_count`, and returns to `LISTENING`.

---

## 7. Speech-to-Text & Text-to-Speech Abstractions

### 7.1 Speech-to-Text (`STTProvider`)
- Streams `AudioFrame` chunks and produces `TranscriptSegment` objects with:
  - `text`: Transcribed utterance.
  - `is_final`: Boolean flag indicating complete sentence or interim hypothesis.
  - `confidence`: Confidence score (`0.0` - `1.0`).
  - `language`: Normalized ISO language code (`en`, `hi`, `te`, `ta`).
  - `latency_ms`: Time taken from frame receipt to transcription.
- Providers: `DeepgramSTTProvider`, `WhisperSTTProvider`, `MockSTTProvider` (dev/test only).

### 7.2 Text-to-Speech (`TTSProvider`)
- Consumes text chunks from the `TextChunker` and streams `TTSAudioChunk` objects with:
  - `audio_bytes`: Encoded audio bytes.
  - `sample_rate`, `encoding`, `channels`.
  - `generation_id`: Bound to the active turn generation ID.
  - `latency_ms`: Time-to-first-audio measurement.
- Providers: `CartesiaTTSProvider`, `ElevenLabsTTSProvider`, `MockTTSProvider` (dev/test only).

### 7.3 Streaming Text Chunker (`TextChunker`)
Buffers raw LLM token streams and emits synthesis-ready sentences:
- Splits on sentence terminals (`.`, `?`, `!`, `।`, `\n`) and pause boundaries (`,`, `;`, `:`).
- Minimum chunk length (default: `15` chars) prevents stuttered one-word TTS calls.
- Maximum chunk length (default: `250` chars) prevents unbounded latency.

---

## 8. Multi-Language Intelligence

Full support for 4 core languages with ISO-639-1 normalization:
- **English (`en`)**: Default international language.
- **Hindi (`hi`)**: Devanagari script; handles purnaviram (`।`) sentence delimiters.
- **Telugu (`te`)**: Telugu script; handles Indian phonetics and pause rules.
- **Tamil (`ta`)**: Tamil script; handles Dravidian phonetic segmentation.

Aliases (`EN`, `HI`, `TE`, `TA`) are automatically normalized via `normalize_voice_language()`.

---

## 9. Telemetry & Performance Bounds

Turn execution captures granular latency and operational telemetry:
- `time_to_first_token_ms` (TTFT): LLM response start latency.
- `time_to_first_audio_ms` (TTFA): Complete roundtrip latency to first playable TTS chunk.
- `stt_latency_ms`: Duration of audio transcription.
- `llm_latency_ms`: Duration of conversational generation.
- `tts_latency_ms`: Duration of audio synthesis.
- `total_turn_latency_ms`: Total end-to-end turn duration.
- `interruption_count`: Number of barge-in interruptions in the session.
- `turn_count`: Total conversational turns completed.

---

## 10. Security, Privacy & Multi-Tenancy

1. **Tenant Isolation**: Every `VoiceSession` is foreign-keyed to `tenant_id`. All queries enforce `tenant_id` boundaries.
2. **RBAC Permissions**:
   - `voice:read`: Required to list and inspect voice sessions.
   - `voice:create`: Required to initiate new voice sessions.
   - `voice:manage`: Required to update configuration or audio stream settings.
   - `voice:interrupt`: Required to send barge-in interruption signals.
   - `voice:end`: Required to terminate active sessions.
3. **Privacy & Retention Controls**:
   - `VOICE_TRANSCRIPT_RETENTION_ENABLED`: When `False`, raw transcripts are scrubbed after the session terminates.
   - `VOICE_AUDIO_RETENTION_ENABLED`: When `False`, audio frame payloads and recording buffers are discarded immediately upon processing.
4. **Production Safety Invariants**:
   - Startup validation rejects `mock` providers if `ENVIRONMENT=production`.
   - Secret scrubbing applies to all voice session metadata and telemetry logs.
