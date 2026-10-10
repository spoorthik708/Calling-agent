"""Voice Session State Machine & Transition Invariants.

Enforces:
1. Deterministic state transitions across the voice session lifecycle.
2. Rejection of illegal state jumps (e.g. ENDED -> ACTIVE or CREATED -> SPEAKING).
3. Explicit interruption (barge-in) and termination states.
"""

from enum import Enum
from typing import Dict, FrozenSet, Set, Union

from app.core.exceptions import VoiceSessionStateError


class VoiceSessionStatus(str, Enum):
    CREATED = "created"
    CONNECTING = "connecting"
    ACTIVE = "active"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ENDING = "ending"
    ENDED = "ended"
    FAILED = "failed"


# Valid state machine transitions
ALLOWED_TRANSITIONS: Dict[VoiceSessionStatus, FrozenSet[VoiceSessionStatus]] = {
    VoiceSessionStatus.CREATED: frozenset({
        VoiceSessionStatus.CONNECTING,
        VoiceSessionStatus.ACTIVE,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.CONNECTING: frozenset({
        VoiceSessionStatus.ACTIVE,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.ACTIVE: frozenset({
        VoiceSessionStatus.LISTENING,
        VoiceSessionStatus.PROCESSING,
        VoiceSessionStatus.ENDING,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.LISTENING: frozenset({
        VoiceSessionStatus.PROCESSING,
        VoiceSessionStatus.SPEAKING,
        VoiceSessionStatus.INTERRUPTED,
        VoiceSessionStatus.ENDING,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.PROCESSING: frozenset({
        VoiceSessionStatus.SPEAKING,
        VoiceSessionStatus.LISTENING,
        VoiceSessionStatus.INTERRUPTED,
        VoiceSessionStatus.ENDING,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.SPEAKING: frozenset({
        VoiceSessionStatus.LISTENING,
        VoiceSessionStatus.INTERRUPTED,
        VoiceSessionStatus.ENDING,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.INTERRUPTED: frozenset({
        VoiceSessionStatus.LISTENING,
        VoiceSessionStatus.PROCESSING,
        VoiceSessionStatus.ENDING,
        VoiceSessionStatus.FAILED,
        VoiceSessionStatus.ENDED,
    }),
    VoiceSessionStatus.ENDING: frozenset({
        VoiceSessionStatus.ENDED,
        VoiceSessionStatus.FAILED,
    }),
    VoiceSessionStatus.ENDED: frozenset(),  # Terminal state
    VoiceSessionStatus.FAILED: frozenset(),  # Terminal state
}


def _normalize_status(status_val: Union[VoiceSessionStatus, str]) -> VoiceSessionStatus:
    if isinstance(status_val, VoiceSessionStatus):
        return status_val
    val = str(status_val).lower().strip()
    if val in ("completed", "ended"):
        return VoiceSessionStatus.ENDED
    return VoiceSessionStatus(val)


def validate_status_transition(
    current_status: Union[VoiceSessionStatus, str],
    target_status: Union[VoiceSessionStatus, str],
) -> bool:
    """
    Validates that a transition from current_status to target_status is permitted.
    Raises VoiceSessionStateError if invalid. Returns True if valid.
    """
    curr = _normalize_status(current_status)
    target = _normalize_status(target_status)

    if curr == target:
        return True

    allowed = ALLOWED_TRANSITIONS.get(curr, frozenset())
    if target not in allowed:
        raise VoiceSessionStateError(
            message=f"Invalid voice session transition from '{curr.value}' to '{target.value}'.",
            details={
                "current_status": curr.value,
                "target_status": target.value,
                "allowed_transitions": [s.value for s in allowed],
            },
        )
    return True
