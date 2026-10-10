"""Text-to-Speech (TTS) Provider Abstraction & Streaming Synthesis.

Enforces:
1. Vendor-neutral TTS protocol supporting both batch and streaming phrase synthesis.
2. Structured audio chunk models with sample rate, encoding, and generation tracking.
3. Cancellation and stale-audio protection via generation_id tracking.
4. Clearly identified MockTTSProvider for test automation.
5. Strict production validation prohibiting silent mock downgrades.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.core.exceptions import TTSSynthesisError, VoiceConfigurationError
from app.voice.audio import AudioEncoding


class TTSAudioChunk(BaseModel):
    """Structured synthesized audio chunk emitted by TTS engines."""
    audio_bytes: bytes = b""
    audio_payload: Optional[bytes] = None
    sample_rate: int = 16000
    encoding: Any = AudioEncoding.PCM_S16LE
    text_segment: str = ""
    is_final: bool = False
    voice_session_id: Optional[str] = None
    turn_id: Optional[str] = None
    generation_id: Union[int, str] = 1
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def sync_payload(self) -> "TTSAudioChunk":
        if self.audio_payload is not None and not self.audio_bytes:
            self.audio_bytes = self.audio_payload
        elif self.audio_bytes and self.audio_payload is None:
            self.audio_payload = self.audio_bytes
        return self


class TTSProvider(ABC):
    """Abstract interface for Text-to-Speech synthesis engines."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: Any = "en",
        generation_id: Union[int, str] = 1,
        **kwargs: Any,
    ) -> TTSAudioChunk:
        """Performs batch synthesis of a full text response."""
        pass

    @abstractmethod
    async def stream_synthesis(
        self,
        text: Optional[str] = None,
        text_stream: Optional[Any] = None,
        voice_id: Optional[str] = None,
        language: Any = "en",
        generation_id: Union[int, str] = 1,
        **kwargs: Any,
    ) -> AsyncGenerator[TTSAudioChunk, None]:
        """Synthesizes incoming phrase chunks into streaming audio chunks."""
        pass


class MockTTSProvider(TTSProvider):
    """
    Deterministic test implementation of TTSProvider.
    Generates synthetic PCM audio frames corresponding to text character length.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def _generate_synthetic_pcm(self, text: str) -> bytes:
        # Generates synthetic 16-bit PCM samples (~200 samples per char = 400 bytes)
        sample_count = max(160, len(text) * 200)
        return b"\x00\x00" * sample_count

    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: Any = "en",
        generation_id: Union[int, str] = 1,
        **kwargs: Any,
    ) -> TTSAudioChunk:
        lang_str = getattr(language, "value", str(language))
        if not text or not text.strip():
            return TTSAudioChunk(
                audio_bytes=b"",
                sample_rate=self.sample_rate,
                is_final=True,
                generation_id=generation_id,
            )

        pcm_bytes = self._generate_synthetic_pcm(text)
        return TTSAudioChunk(
            audio_bytes=pcm_bytes,
            sample_rate=self.sample_rate,
            encoding=AudioEncoding.PCM_S16LE,
            text_segment=text,
            is_final=True,
            generation_id=generation_id,
            provider_metadata={"provider": "mock", "voice_id": voice_id or "default", "language": lang_str},
        )

    async def stream_synthesis(
        self,
        text: Optional[str] = None,
        text_stream: Optional[Any] = None,
        voice_id: Optional[str] = None,
        language: Any = "en",
        generation_id: Union[int, str] = 1,
        voice_session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[TTSAudioChunk, None]:
        lang_str = getattr(language, "value", str(language))

        # Support direct phrase string
        if text is not None:
            if text.strip():
                pcm_bytes = self._generate_synthetic_pcm(text)
                yield TTSAudioChunk(
                    audio_bytes=pcm_bytes,
                    sample_rate=self.sample_rate,
                    encoding=AudioEncoding.PCM_S16LE,
                    text_segment=text,
                    is_final=False,
                    generation_id=generation_id,
                    voice_session_id=voice_session_id,
                    turn_id=turn_id,
                    provider_metadata={"provider": "mock", "voice_id": voice_id or "default", "language": lang_str},
                )
            return

        # Support streaming input of phrases
        if text_stream is not None:
            async for phrase in text_stream:
                if not phrase or not phrase.strip():
                    continue
                pcm_bytes = self._generate_synthetic_pcm(phrase)
                yield TTSAudioChunk(
                    audio_bytes=pcm_bytes,
                    sample_rate=self.sample_rate,
                    encoding=AudioEncoding.PCM_S16LE,
                    text_segment=phrase,
                    is_final=False,
                    generation_id=generation_id,
                    voice_session_id=voice_session_id,
                    turn_id=turn_id,
                    provider_metadata={"provider": "mock", "voice_id": voice_id or "default", "language": lang_str},
                )


def get_tts_provider(provider_name: Optional[str] = None) -> TTSProvider:
    """
    Factory resolving configured TTSProvider.
    Rejects mock providers when running in production environment.
    """
    settings = get_settings()
    name = (provider_name or settings.DEFAULT_TTS_PROVIDER).lower().strip()

    if name == "mock":
        if settings.is_production:
            raise VoiceConfigurationError(
                "Mock TTS provider is strictly prohibited in production environments."
            )
        return MockTTSProvider()

    raise VoiceConfigurationError(f"Unsupported TTS provider '{name}'.")
