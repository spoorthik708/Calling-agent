from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
import uuid
from app.voice.events import AudioChunk, CallEvent


class VoiceSessionInterface(ABC):
    """
    Interface for real-time voice sessions handling bi-directional audio streaming,
    interruption/barge-in, and agent turn coordination.
    """
    @abstractmethod
    async def initialize_session(self, call_id: str, tenant_id: uuid.UUID) -> None:
        """Initializes state and audio pipelines for an active call."""
        pass

    @abstractmethod
    async def process_incoming_audio(self, chunk: AudioChunk) -> None:
        """Feeds incoming customer audio to VAD and speech-to-text pipeline."""
        pass

    @abstractmethod
    async def handle_barge_in(self) -> None:
        """Interrupts ongoing speech synthesis immediately when customer speaks."""
        pass

    @abstractmethod
    async def close_session(self) -> None:
        """Cleans up session buffers and flushes metrics."""
        pass


class BargeInHandlerInterface(ABC):
    """Voice Activity Detection and interruption handler abstraction."""
    @abstractmethod
    def is_speech_active(self, chunk: AudioChunk) -> bool:
        """Evaluates whether customer is actively vocalizing during agent speech."""
        pass
