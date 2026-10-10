"""Voice Activity Detection (VAD) Abstraction & Implementations.

Separates VAD interface from concrete implementations:
1. VADInterface protocol.
2. EnergyVAD: deterministic server-side energy calculation for PCM audio.
3. MockVAD: controllable mock for deterministic test scenarios.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import struct
from typing import Optional

from app.core.exceptions import VoiceConfigurationError
from app.voice.audio import AudioEncoding, AudioFrame


@dataclass(frozen=True)
class VADResult:
    """Result of voice activity evaluation on a single audio frame."""
    is_speech: bool
    confidence: float
    energy: float


class VADInterface(ABC):
    """Abstract interface for speech presence detection."""

    @abstractmethod
    def process_frame(self, frame: AudioFrame) -> VADResult:
        """Evaluates whether an audio frame contains human speech."""
        pass

    def is_speech(self, frame: AudioFrame) -> VADResult:
        """Alias for process_frame."""
        return self.process_frame(frame)

    @abstractmethod
    def reset(self) -> None:
        """Resets internal state/filters."""
        pass


class EnergyVAD(VADInterface):
    """
    Deterministic energy-based Voice Activity Detector.
    Calculates Root Mean Square (RMS) amplitude of PCM 16-bit signed audio.
    Suitable for local testing and lightweight server-side speech boundaries.
    """

    def __init__(self, energy_threshold: float = 400.0):
        self.energy_threshold = energy_threshold

    def process_frame(self, frame: AudioFrame) -> VADResult:
        if frame.encoding != AudioEncoding.PCM_S16LE or not frame.payload:
            return VADResult(is_speech=False, confidence=0.0, energy=0.0)

        # Unpack 16-bit signed integers (little-endian)
        num_samples = len(frame.payload) // 2
        if num_samples == 0:
            return VADResult(is_speech=False, confidence=0.0, energy=0.0)

        try:
            samples = struct.unpack(f"<{num_samples}h", frame.payload[: num_samples * 2])
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / num_samples)
        except Exception:
            rms = 0.0

        is_speech = rms >= self.energy_threshold
        confidence = min(1.0, rms / (self.energy_threshold * 2.0)) if is_speech else 0.0

        return VADResult(is_speech=is_speech, confidence=confidence, energy=rms)

    def reset(self) -> None:
        pass


class MockVAD(VADInterface):
    """
    Controllable VAD implementation for test automation.
    Allows tests to deterministically force speech active or silence.
    """

    def __init__(self, default_speech: bool = False):
        self._speech_active = default_speech

    def set_speech(self, active: bool) -> None:
        """Manually triggers speech state in tests."""
        self._speech_active = active

    def set_speech_state(self, active: bool) -> None:
        """Alias for set_speech."""
        self._speech_active = active

    def process_frame(self, frame: AudioFrame) -> VADResult:
        return VADResult(
            is_speech=self._speech_active,
            confidence=1.0 if self._speech_active else 0.0,
            energy=1000.0 if self._speech_active else 50.0,
        )

    def reset(self) -> None:
        self._speech_active = False


def get_vad_provider(provider_name: str = "energy") -> VADInterface:
    """Factory to instantiate configured VAD implementation."""
    from app.core.config import get_settings
    settings = get_settings()

    name = (provider_name or "").lower().strip()
    if name == "energy":
        return EnergyVAD()
    elif name == "mock":
        if settings.is_production:
            raise VoiceConfigurationError(
                message="Mock VAD provider is strictly prohibited in production.",
                details={"provider": "mock"},
            )
        return MockVAD()
    raise VoiceConfigurationError(
        message=f"Unsupported VAD provider '{provider_name}'.",
        details={"provider": provider_name},
    )
