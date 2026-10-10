"""Text Chunking & Sentence Buffering for Streaming TTS.

Transforms fine-grained LLM token streams into natural speaking phrases/sentences.
Enforces:
1. Low latency: emits the first speaking clause as early as possible (e.g. upon comma/period).
2. Natural prosody: preserves punctuation boundaries (., ?, !, :, ;, \n).
3. Bounded phrase length: splits long sentences that exceed configured character thresholds.
"""

from typing import AsyncGenerator, List, Optional, Set

PUNCTUATION_SPLITTERS: Set[str] = {".", "!", "?", "\n", "।"}  # Includes Hindi purna viram
CLAUSE_SPLITTERS: Set[str] = {",", ";", ":", "—", "-"}


class TextChunker:
    """
    Asynchronous text buffer that accumulates LLM streaming tokens
    and yields natural sentence and phrase chunks for TTS synthesis.
    """

    def __init__(
        self,
        min_first_chunk_chars: int = 15,
        target_chunk_chars: int = 80,
        max_chunk_chars: int = 180,
        min_chunk_chars: Optional[int] = None,
    ):
        if min_chunk_chars is not None:
            self.min_first_chunk_chars = min_chunk_chars
            self.target_chunk_chars = min_chunk_chars
        else:
            self.min_first_chunk_chars = min_first_chunk_chars
            self.target_chunk_chars = target_chunk_chars
        self.max_chunk_chars = max_chunk_chars
        self._is_first_chunk: bool = True
        self._buffer: str = ""

    def feed(self, text: str) -> List[str]:
        """Feeds text token/chunk into buffer and returns any ready phrases."""
        self._buffer += text
        emitted: List[str] = []
        while self._buffer:
            split_idx = self._find_split_point(self._buffer)
            if split_idx != -1:
                chunk = self._buffer[: split_idx + 1].strip()
                self._buffer = self._buffer[split_idx + 1 :].lstrip()
                if chunk:
                    self._is_first_chunk = False
                    emitted.append(chunk)
            else:
                if len(self._buffer) >= self.max_chunk_chars:
                    space_idx = self._buffer.rfind(" ", 0, self.max_chunk_chars)
                    if space_idx != -1:
                        chunk = self._buffer[:space_idx].strip()
                        self._buffer = self._buffer[space_idx + 1 :].lstrip()
                        if chunk:
                            self._is_first_chunk = False
                            emitted.append(chunk)
                    else:
                        chunk = self._buffer[: self.max_chunk_chars].strip()
                        self._buffer = self._buffer[self.max_chunk_chars :].lstrip()
                        if chunk:
                            self._is_first_chunk = False
                            emitted.append(chunk)
                break
        return emitted

    def flush(self) -> List[str]:
        """Flushes remaining text in the buffer."""
        remaining = self._buffer.strip()
        self._buffer = ""
        self._is_first_chunk = True
        if remaining:
            return [remaining]
        return []

    async def chunk_stream(
        self,
        token_stream: AsyncGenerator[str, None],
    ) -> AsyncGenerator[str, None]:
        """
        Consumes streaming tokens, buffers them into phrases, and yields complete phrases.
        """
        async for token in token_stream:
            for chunk in self.feed(token):
                yield chunk

        for chunk in self.flush():
            yield chunk

    def _find_split_point(self, text: str) -> int:
        """Finds the earliest suitable punctuation boundary in the text buffer."""
        min_chars = self.min_first_chunk_chars if self._is_first_chunk else self.target_chunk_chars

        for i, char in enumerate(text):
            if char in PUNCTUATION_SPLITTERS and i >= min_chars:
                return i
            # On first chunk, allow splitting at clause boundaries early for ultra-fast TTFA
            if self._is_first_chunk and char in CLAUSE_SPLITTERS and i >= self.min_first_chunk_chars:
                return i
            if not self._is_first_chunk and char in CLAUSE_SPLITTERS and i >= self.target_chunk_chars:
                return i

        return -1
