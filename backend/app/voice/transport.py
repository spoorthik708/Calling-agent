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


class TwilioVoiceTransport(VoiceTransport):
    """
    Twilio Media Stream WebSocket Voice Transport.
    Formats synthesized TTS audio chunks into Twilio 'media' JSON frames and
    sends 'clear' frames on barge-in interruption to halt Twilio playback buffer.
    """

    def __init__(self, websocket: Any, stream_sid: Optional[str] = None):
        self.websocket = websocket
        self.stream_sid = stream_sid
        self.is_closed: bool = False

    def set_stream_sid(self, stream_sid: str) -> None:
        self.stream_sid = stream_sid

    async def send_audio(self, chunk: TTSAudioChunk) -> None:
        if self.is_closed or not self.stream_sid:
            return

        import base64
        import json

        base64_audio = base64.b64encode(chunk.audio_bytes).decode("utf-8")
        payload = {
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {
                "payload": base64_audio,
            },
        }
        try:
            if hasattr(self.websocket, "send_text"):
                await self.websocket.send_text(json.dumps(payload))
            elif hasattr(self.websocket, "send_json"):
                await self.websocket.send_json(payload)
        except Exception:
            self.is_closed = True

    async def send_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.is_closed or not self.stream_sid:
            return

        import json

        if event_type in ("interrupted", "clear"):
            clear_msg = {
                "event": "clear",
                "streamSid": self.stream_sid,
            }
            try:
                if hasattr(self.websocket, "send_text"):
                    await self.websocket.send_text(json.dumps(clear_msg))
                elif hasattr(self.websocket, "send_json"):
                    await self.websocket.send_json(clear_msg)
            except Exception:
                self.is_closed = True

    async def close(self) -> None:
        self.is_closed = True
        try:
            if hasattr(self.websocket, "close"):
                await self.websocket.close()
        except Exception:
            pass
