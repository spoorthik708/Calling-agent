"""Speech-to-Text (STT) Provider Abstraction & Implementations.

Enforces:
1. Vendor-neutral STT protocol supporting both one-shot and streaming transcription.
2. Structured Pydantic transcript models preserving confidence, language, and timings.
3. Clearly identified MockSTTProvider for test automation.
4. Strict production validation prohibiting silent mock downgrades.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.exceptions import VoiceConfigurationError, STTTranscriptionError
from app.voice.audio import AudioFrame


class TranscriptSegment(BaseModel):
    """Structured transcription segment emitted by STT engines."""
    text: str = ""
    is_final: bool = False
    confidence: Optional[float] = None
    start_ms: Optional[float] = None
    end_ms: Optional[float] = None
    latency_ms: float = 0.0
    language: Optional[str] = None
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)


class STTProvider(ABC):
    """Abstract interface for Speech-to-Text transcription engines."""

    @abstractmethod
    async def transcribe_audio(
        self,
        audio_data: Optional[bytes] = None,
        audio_bytes: Optional[bytes] = None,
        language: Any = "en",
        **kwargs: Any,
    ) -> TranscriptSegment:
        """Performs batch transcription on a complete turn audio buffer."""
        pass

    @abstractmethod
    async def stream_transcription(
        self,
        audio_stream: AsyncGenerator[AudioFrame, None],
        language: Any = "en",
        **kwargs: Any,
    ) -> AsyncGenerator[TranscriptSegment, None]:
        """Streams incremental partial transcripts and yields final transcript segment."""
        pass


class MockSTTProvider(STTProvider):
    """
    Deterministic test implementation of STTProvider.
    Allows tests to configure preset transcriptions or transcribe recognizable test tokens.
    """

    def __init__(self, preset_transcript: Optional[str] = None):
        self.preset_transcript = preset_transcript
        self._last_language: Optional[str] = None

    def set_preset_transcript(self, text: str) -> None:
        self.preset_transcript = text

    async def transcribe_audio(
        self,
        audio_data: Optional[bytes] = None,
        audio_bytes: Optional[bytes] = None,
        language: Any = "en",
        **kwargs: Any,
    ) -> TranscriptSegment:
        import time
        start = time.perf_counter()
        raw_bytes = audio_data if audio_data is not None else (audio_bytes or b"")
        lang_str = getattr(language, "value", str(language))
        self._last_language = lang_str

        if not raw_bytes:
            return TranscriptSegment(text="", is_final=True, language=lang_str, latency_ms=1.0)

        text = self.preset_transcript or "Hello, I would like to check my order status."
        elapsed_ms = max(1.0, (time.perf_counter() - start) * 1000.0)
        return TranscriptSegment(
            text=text,
            is_final=True,
            confidence=0.98,
            start_ms=0.0,
            end_ms=float(len(raw_bytes) / 32.0),
            latency_ms=elapsed_ms,
            language=lang_str,
            provider_metadata={"provider": "mock", "byte_count": len(raw_bytes)},
        )

    async def stream_transcription(
        self,
        audio_stream: AsyncGenerator[AudioFrame, None],
        language: str = "en",
    ) -> AsyncGenerator[TranscriptSegment, None]:
        self._last_language = language
        total_bytes = 0
        async for frame in audio_stream:
            total_bytes += len(frame.payload)
            # Emit interim partial
            yield TranscriptSegment(
                text="Hello...",
                is_final=False,
                confidence=0.75,
                language=language,
                provider_metadata={"partial": True},
            )

        # Emit final
        text = self.preset_transcript or "Hello, I would like to check my order status."
        yield TranscriptSegment(
            text=text,
            is_final=True,
            confidence=0.98,
            language=language,
            provider_metadata={"provider": "mock", "total_bytes": total_bytes},
        )


def get_stt_provider(provider_name: Optional[str] = None) -> STTProvider:
    """
    Factory resolving configured STTProvider.
    Rejects mock providers when running in production environment.
    """
    settings = get_settings()
    name = (provider_name or settings.DEFAULT_STT_PROVIDER).lower().strip()

    if name == "mock":
        if settings.is_production:
            raise VoiceConfigurationError(
                "Mock STT provider is strictly prohibited in production environments."
            )
        return MockSTTProvider()

    raise VoiceConfigurationError(f"Unsupported STT provider '{name}'.")
