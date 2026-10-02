from dataclasses import dataclass
from typing import List
from app.conversations.models import Message


@dataclass
class FormattedMessage:
    role: str
    content: str


class ConversationMemoryManager:
    """
    Manages bounded conversation history windowing.
    Ensures recent relevant conversation turns are preserved while strictly honoring
    token and character constraints. System instructions and retrieved knowledge are
    never truncated by the conversation memory window.
    """
    def __init__(self, max_messages: int = 20, max_characters: int = 16000):
        self.max_messages = max(1, max_messages)
        self.max_characters = max(500, max_characters)

    def select_history(self, messages: List[Message]) -> List[FormattedMessage]:
        """
        Selects a bounded slice of recent messages from history.
        Preserves chronological order of selected turns.
        Excludes raw system/internal messages from user history (system prompt is managed separately).
        """
        # Filter for valid conversational turn roles (user, assistant, tool)
        valid_messages = [
            m for m in messages
            if m.role in ("user", "assistant", "tool")
        ]

        if not valid_messages:
            return []

        # Start from the most recent messages and take up to max_messages
        recent_slice = valid_messages[-self.max_messages:]

        # Enforce character bound working backwards from most recent
        selected: List[Message] = []
        total_chars = 0

        for msg in reversed(recent_slice):
            content_len = len(msg.content or "")
            if total_chars + content_len > self.max_characters and len(selected) > 0:
                # If adding this message exceeds the character limit, stop adding older turns
                break
            selected.append(msg)
            total_chars += content_len

        # Re-sort to chronological order
        selected.reverse()

        return [
            FormattedMessage(
                role=msg.role,
                content=msg.content,
            )
            for msg in selected
        ]
