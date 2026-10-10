"""Normalized Audio Processing & Bounded Buffer Management.

Ensures:
1. Vendor-neutral internal audio format representation.
2. Bounded audio chunk processing preventing resource exhaustion.
3. Audio buffer accumulation with strict byte and frame limits.
4. Backpressure handling on asynchronous queues.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import AsyncGenerator, List, Optional

from app.core.config import get_settings
from app.core.exceptions import AudioBufferOverflowError


class AudioEncoding(str, Enum):
    PCM_S16LE = "pcm_s16le"  # Linear 16-bit signed PCM (industry standard internal format)
    LINEAR16 = "pcm_s16le"   # Common alias for PCM 16-bit
    MULAW = "mulaw"          # G.711 mu-law (telephony standard)
    ALAW = "alaw"            # G.711 a-law
    OPUS = "opus"            # Compressed WebRTC / stream standard


@dataclass
class AudioFrame:
    """Normalized internal frame of audio stream."""
    payload: bytes
    sequence: int = 0
    sample_rate: int = 16000
    channels: int = 1
    encoding: AudioEncoding = AudioEncoding.PCM_S16LE
    bit_depth: int = 16
    timestamp_ms: float = 0.0
    duration_ms: float = 0.0

    def __post_init__(self):
        from app.core.exceptions import VoiceAudioFormatError

        if not isinstance(self.payload, bytes):
            raise VoiceAudioFormatError("Audio frame payload must be raw bytes.")

        if self.sequence < 0:
            raise VoiceAudioFormatError(f"Sequence number must be non-negative, received {self.sequence}.")

        valid_sample_rates = (8000, 16000, 22050, 24000, 32000, 44100, 48000)
        if self.sample_rate not in valid_sample_rates:
            raise VoiceAudioFormatError(
                f"Unsupported sample rate: {self.sample_rate} Hz. Supported: {valid_sample_rates}"
            )

        if self.channels not in (1, 2):
            raise VoiceAudioFormatError(f"Unsupported channel count: {self.channels}. Must be 1 (mono) or 2 (stereo).")

        if self.bit_depth not in (8, 16, 24, 32):
            raise VoiceAudioFormatError(f"Unsupported bit depth: {self.bit_depth}. Must be 8, 16, 24, or 32.")

        # For PCM audio, validate sample boundary alignment and duration consistency
        if self.encoding in (AudioEncoding.PCM_S16LE, AudioEncoding.LINEAR16):
            bytes_per_sample = self.channels * (self.bit_depth // 8)
            if bytes_per_sample <= 0:
                raise VoiceAudioFormatError("Invalid bytes_per_sample configuration.")

            if len(self.payload) % bytes_per_sample != 0:
                raise VoiceAudioFormatError(
                    f"Corrupted or incomplete PCM frame: payload length {len(self.payload)} is not divisible by bytes per sample frame ({bytes_per_sample})."
                )

            expected_duration_ms = (len(self.payload) / bytes_per_sample / self.sample_rate) * 1000.0
            if self.duration_ms <= 0.0:
                self.duration_ms = expected_duration_ms
            elif abs(self.duration_ms - expected_duration_ms) > 5.0 and len(self.payload) > 0:
                raise VoiceAudioFormatError(
                    f"Inconsistent audio metadata: payload implies duration {expected_duration_ms:.2f}ms, but frame metadata specifies {self.duration_ms:.2f}ms."
                )


class BoundedAudioBuffer:
    """
    Accumulates raw audio frames for turn processing under strict memory boundaries.
    Rejects oversized chunks or total buffer overflow to prevent denial of service.
    """

    def __init__(
        self,
        max_chunk_bytes: Optional[int] = None,
        max_buffer_bytes: Optional[int] = None,
        max_queue_size: Optional[int] = None,
    ):
        settings = get_settings()
        self.max_chunk_bytes = max_chunk_bytes or settings.MAX_AUDIO_CHUNK_BYTES
        self.max_buffer_bytes = max_buffer_bytes or settings.MAX_AUDIO_BUFFER_BYTES
        self.max_queue_size = max_queue_size or settings.MAX_AUDIO_QUEUE_SIZE

        self._frames: List[AudioFrame] = []
        self._total_bytes: int = 0
        self._total_duration_ms: float = 0.0

    def add_frame(self, frame: AudioFrame) -> None:
        """Adds an audio frame to the accumulator, checking safety boundaries."""
        chunk_len = len(frame.payload)
        if chunk_len > self.max_chunk_bytes:
            raise AudioBufferOverflowError(
                message=f"Audio chunk of {chunk_len} bytes exceeds maximum allowed limit of {self.max_chunk_bytes} bytes.",
                details={"chunk_bytes": chunk_len, "max_chunk_bytes": self.max_chunk_bytes},
            )

        if len(self._frames) >= self.max_queue_size:
            raise AudioBufferOverflowError(
                message=f"Audio frame queue limit exceeded (maximum capacity of {self.max_queue_size} frames).",
                details={"queue_size": len(self._frames), "max_queue_size": self.max_queue_size},
            )

        if self._total_bytes + chunk_len > self.max_buffer_bytes:
            raise AudioBufferOverflowError(
                message=f"Audio buffer total memory limit exceeded ({self._total_bytes + chunk_len} bytes exceeds maximum limit of {self.max_buffer_bytes} bytes).",
                details={"total_bytes": self._total_bytes + chunk_len, "max_buffer_bytes": self.max_buffer_bytes},
            )

        self._frames.append(frame)
        self._total_bytes += chunk_len
        self._total_duration_ms += frame.duration_ms

    async def push(self, frame: AudioFrame) -> None:
        """Asynchronously pushes an audio frame into the buffer."""
        self.add_frame(frame)

    def drain(self) -> List[AudioFrame]:
        """Drains and returns all buffered audio frames, clearing the buffer."""
        drained = list(self._frames)
        self.clear()
        return drained

    def get_concatenated_bytes(self) -> bytes:
        """Returns the concatenated audio payload of all accumulated frames."""
        return b"".join(f.payload for f in self._frames)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def queue_size(self) -> int:
        return len(self._frames)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def total_buffered_bytes(self) -> int:
        return self._total_bytes

    @property
    def total_duration_ms(self) -> float:
        return self._total_duration_ms

    def clear(self) -> None:
        """Resets the accumulator for the next turn."""
        self._frames.clear()
        self._total_bytes = 0
        self._total_duration_ms = 0.0
