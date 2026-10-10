"""Voice Observability & Latency Telemetry.

Tracks production latency budgets and reliability metrics:
- STT finalization latency (ms)
- LLM Time-to-First-Token (TTFT) (ms)
- TTS Time-to-First-Audio (TTFA) (ms)
- Total turn latency (ms)
- Barge-in / interruption count
- Session duration and error counters
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
import uuid

from app.core.logging import get_logger
from app.tools.credentials import scrub_secrets

logger = get_logger("yavura.voice.telemetry")


@dataclass
class TurnTelemetry:
    """Latency and execution metrics for a single conversational turn."""
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generation_id: int = 1
    stt_latency_ms: float = 0.0
    llm_first_token_ms: float = 0.0
    tts_first_audio_ms: float = 0.0
    total_turn_latency_ms: float = 0.0
    interrupted: bool = False
    tokens_generated: int = 0
    audio_bytes_synthesized: int = 0
    _start_time: float = field(default_factory=time.perf_counter)

    def start_timer(self) -> None:
        self._start_time = time.perf_counter()

    def record_stt(self, latency_ms: float) -> None:
        self.stt_latency_ms = round(latency_ms, 2)

    def record_llm_first_token(self, latency_ms: float) -> None:
        self.llm_first_token_ms = round(latency_ms, 2)

    def record_tts_first_audio(self, latency_ms: float) -> None:
        self.tts_first_audio_ms = round(latency_ms, 2)

    def stop_timer(self) -> None:
        self.total_turn_latency_ms = round((time.perf_counter() - self._start_time) * 1000.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "generation_id": self.generation_id,
            "stt_latency_ms": self.stt_latency_ms,
            "llm_first_token_ms": self.llm_first_token_ms,
            "tts_first_audio_ms": self.tts_first_audio_ms,
            "total_turn_latency_ms": self.total_turn_latency_ms,
            "interrupted": self.interrupted,
            "tokens_generated": self.tokens_generated,
            "audio_bytes_synthesized": self.audio_bytes_synthesized,
        }


class VoiceSessionTelemetry:
    """Session-level telemetry aggregator and logger."""

    def __init__(self, session_id: Any, tenant_id: Any):
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.start_time = time.perf_counter()
        self.turns: List[TurnTelemetry] = []
        self.interruption_count: int = 0
        self.stt_errors: int = 0
        self.tts_errors: int = 0
        self.pipeline_errors: int = 0

    def record_interruption(self) -> None:
        self.interruption_count += 1
        logger.info(
            "Barge-in interruption recorded for session %s (total: %s)",
            self.session_id,
            self.interruption_count,
            extra={"tenant_id": str(self.tenant_id), "session_id": str(self.session_id)},
        )

    def record_turn(self, turn: TurnTelemetry) -> None:
        self.turns.append(turn)
        logger.info(
            "Turn completed for session %s: STT=%.1fms, TTFT=%.1fms, TTFA=%.1fms, Total=%.1fms",
            self.session_id,
            turn.stt_latency_ms,
            turn.llm_first_token_ms,
            turn.tts_first_audio_ms,
            turn.total_turn_latency_ms,
            extra={
                "tenant_id": str(self.tenant_id),
                "session_id": str(self.session_id),
                "turn_id": turn.turn_id,
                "stt_ms": turn.stt_latency_ms,
                "ttft_ms": turn.llm_first_token_ms,
                "ttfa_ms": turn.tts_first_audio_ms,
                "total_ms": turn.total_turn_latency_ms,
            },
        )

    def summary(self) -> Dict[str, Any]:
        duration_sec = time.perf_counter() - self.start_time
        avg_turn_ms = (
            sum(t.total_turn_latency_ms for t in self.turns) / len(self.turns)
            if self.turns
            else 0.0
        )
        return {
            "session_id": str(self.session_id),
            "tenant_id": str(self.tenant_id),
            "duration_seconds": duration_sec,
            "turns_completed": len(self.turns),
            "average_turn_latency_ms": avg_turn_ms,
            "interruption_count": self.interruption_count,
            "stt_errors": self.stt_errors,
            "tts_errors": self.tts_errors,
            "pipeline_errors": self.pipeline_errors,
        }
