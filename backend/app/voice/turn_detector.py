"""Turn Detection & Conversational Endpointing.

Evaluates continuous streams of VAD results to establish:
1. When user begins speaking (USER_STARTED_SPEAKING)
2. Sustained speech (USER_CONTINUES)
3. Speech pauses (USER_STOPPED_SPEAKING)
4. Definite turn completion after silence threshold (TURN_COMPLETE)
5. Turn cutoff if maximum speaking duration is reached (bounded turn safety).
"""

from enum import Enum
from typing import Optional

from app.core.config import get_settings
from app.voice.audio import AudioFrame
from app.voice.vad import VADInterface, VADResult


class TurnEvent(str, Enum):
    USER_STARTED_SPEAKING = "user_started_speaking"
    USER_CONTINUES = "user_continues"
    USER_STOPPED_SPEAKING = "user_stopped_speaking"
    TURN_COMPLETE = "turn_complete"
    NO_CHANGE = "no_change"


class TurnDetector:
    """
    Stateful conversational turn detector.
    Accumulates frame durations to trigger precise turn transition events.
    """

    def __init__(
        self,
        vad: Optional[VADInterface] = None,
        silence_timeout_seconds: Optional[float] = None,
        min_speech_duration_seconds: Optional[float] = None,
        max_turn_duration_seconds: Optional[float] = None,
    ):
        settings = get_settings()
        self.vad = vad
        self.silence_timeout_seconds = silence_timeout_seconds if silence_timeout_seconds is not None else settings.DEFAULT_SILENCE_TIMEOUT_SECONDS
        self.min_speech_duration_seconds = min_speech_duration_seconds if min_speech_duration_seconds is not None else settings.DEFAULT_MIN_SPEECH_DURATION_SECONDS
        self.max_turn_duration_seconds = max_turn_duration_seconds if max_turn_duration_seconds is not None else settings.MAX_TURN_DURATION_SECONDS

        self._is_user_speaking: bool = False
        self._speech_duration_seconds: float = 0.0
        self._silence_duration_seconds: float = 0.0
        self._total_turn_seconds: float = 0.0

    @property
    def is_user_speaking(self) -> bool:
        return self._is_user_speaking

    def process_frame(self, frame: AudioFrame, is_speech: Optional[bool] = None) -> Optional[TurnEvent]:
        """
        Evaluates an audio frame through VAD and updates turn endpointing state.
        Returns the appropriate TurnEvent or None.
        """
        if is_speech is not None:
            speech_active = is_speech
        elif self.vad is not None:
            speech_active = self.vad.process_frame(frame).is_speech
        else:
            speech_active = False

        frame_sec = frame.duration_ms / 1000.0 if frame.duration_ms > 0 else 0.02  # 20ms default

        self._total_turn_seconds += frame_sec

        if speech_active:
            self._speech_duration_seconds += frame_sec
            self._silence_duration_seconds = 0.0

            if not self._is_user_speaking:
                if self._speech_duration_seconds >= self.min_speech_duration_seconds:
                    self._is_user_speaking = True
                    return TurnEvent.USER_STARTED_SPEAKING
                return None
            else:
                # Max turn duration safety check (prevents indefinite speaking)
                if self._total_turn_seconds >= self.max_turn_duration_seconds:
                    self._is_user_speaking = False
                    return TurnEvent.TURN_COMPLETE
                return TurnEvent.USER_CONTINUES
        else:
            # Silence detected
            if self._is_user_speaking:
                self._silence_duration_seconds += frame_sec
                if self._silence_duration_seconds >= self.silence_timeout_seconds:
                    self._is_user_speaking = False
                    return TurnEvent.TURN_COMPLETE
                return TurnEvent.USER_STOPPED_SPEAKING

            self._speech_duration_seconds = 0.0
            return None

    def reset(self) -> None:
        """Resets detector state between conversation turns."""
        self._is_user_speaking = False
        self._speech_duration_seconds = 0.0
        self._silence_duration_seconds = 0.0
        self._total_turn_seconds = 0.0
        if self.vad is not None:
            self.vad.reset()
