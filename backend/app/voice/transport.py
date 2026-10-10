"""Channel-Agnostic Voice Transport Protocol & Implementations.

Decouples the core voice intelligence pipeline from physical audio delivery channels:
- Browser microphone / WebRTC
- Generic WebSocket
- Phone / Telephony (Phase 7)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.voice.tts import TTSAudioChunk


class VoiceTransport(ABC):
    """Abstract protocol for bidirectional real-time audio transport."""

    @abstractmethod
    async def send_audio(self, chunk: TTSAudioChunk) -> None:
        """Transmits synthesized speech audio chunk to client / channel."""
        pass

    @abstractmethod
    async def send_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Transmits conversational or lifecycle event to client / channel."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Closes the underlying network transport channel."""
        pass


class MockVoiceTransport(VoiceTransport):
    """
    Deterministic in-memory mock transport for testing.
    Captures emitted audio chunks and events for assertions.
    """

    def __init__(self):
        self.sent_chunks: List[TTSAudioChunk] = []
        self.sent_events: List[Any] = []
        self.is_closed: bool = False

    async def send_audio(self, chunk: TTSAudioChunk) -> None:
        if not self.is_closed:
            self.sent_chunks.append(chunk)

    async def send_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.is_closed:
            self.sent_events.append((event_type, payload))

    async def close(self) -> None:
        self.is_closed = True

    def clear(self) -> None:
        self.sent_chunks.clear()
        self.sent_events.clear()
        self.is_closed = False
