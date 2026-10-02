import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from app.core.config import get_settings
from app.knowledge.extraction import ExtractedDocument


@dataclass
class RawChunk:
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    metadata: Dict[str, Any]


class ChunkingService:
    """
    Deterministic, metadata-preserving document chunking service.

    Strategy:
    - Splits text on semantic boundaries (paragraphs \n\n, then sentences \n or . , then words).
    - Preserves exact page numbers for multi-page documents (e.g. PDFs).
    - Sliding window with configurable chunk_size and chunk_overlap.
    - Computes deterministic SHA-256 hash for each chunk.
    """
    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        self.settings = get_settings()
        self.chunk_size = chunk_size or self.settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else self.settings.CHUNK_OVERLAP

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(f"chunk_overlap ({self.chunk_overlap}) must be less than chunk_size ({self.chunk_size})")

    def _split_text_semantically(self, text: str) -> List[str]:
        """Splits a single text block into chunks with overlap, preferring semantic boundaries."""
        if len(text) <= self.chunk_size:
            return [text]

        chunks: List[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.chunk_size
            if end >= text_len:
                chunk = text[start:].strip()
                if chunk:
                    chunks.append(chunk)
                break

            # Find best split point near end (prefer \n\n, then \n, then . , then space)
            segment = text[start:end]
            split_idx = -1

            # Look for double newline
            p_idx = segment.rfind("\n\n")
            if p_idx > self.chunk_size // 2:
                split_idx = p_idx + 2
            else:
                # Look for sentence period
                s_idx = segment.rfind(". ")
                if s_idx > self.chunk_size // 2:
                    split_idx = s_idx + 2
                else:
                    # Look for single newline
                    nl_idx = segment.rfind("\n")
                    if nl_idx > self.chunk_size // 2:
                        split_idx = nl_idx + 1
                    else:
                        # Look for space
                        sp_idx = segment.rfind(" ")
                        if sp_idx > self.chunk_size // 2:
                            split_idx = sp_idx + 1

            if split_idx == -1:
                # Hard cut if no reasonable boundary found
                split_idx = self.chunk_size

            chunk = text[start:start + split_idx].strip()
            if chunk:
                chunks.append(chunk)

            # Advance with overlap, strictly guaranteeing forward progression
            next_start = start + split_idx - self.chunk_overlap
            if next_start <= start:
                next_start = start + 1
            start = next_start
            if start >= text_len:
                break

        return chunks

    def chunk_document(self, doc: ExtractedDocument) -> List[RawChunk]:
        """
        Chunks an extracted document into sequential, hashed RawChunk objects
        annotated with page numbers and source metadata.
        """
        raw_chunks: List[RawChunk] = []
        global_index = 0

        if doc.pages:
            # Multi-page extraction (e.g. PDF)
            for page in doc.pages:
                page_chunks = self._split_text_semantically(page.text)
                for chunk_text in page_chunks:
                    content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                    token_approx = max(1, len(chunk_text.split()))

                    chunk_meta = {
                        "page_number": page.page_number,
                        "char_count": len(chunk_text),
                    }
                    raw_chunks.append(
                        RawChunk(
                            chunk_index=global_index,
                            content=chunk_text,
                            content_hash=content_hash,
                            token_count=token_approx,
                            metadata=chunk_meta,
                        )
                    )
                    global_index += 1
        else:
            # Single text body
            chunks = self._split_text_semantically(doc.normalized_text)
            for chunk_text in chunks:
                content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                token_approx = max(1, len(chunk_text.split()))

                chunk_meta = {
                    "page_number": 1,
                    "char_count": len(chunk_text),
                }
                raw_chunks.append(
                    RawChunk(
                        chunk_index=global_index,
                        content=chunk_text,
                        content_hash=content_hash,
                        token_count=token_approx,
                        metadata=chunk_meta,
                    )
                )
                global_index += 1

        if len(raw_chunks) > self.settings.MAX_DOCUMENT_CHUNKS:
            raise ValueError(
                f"Document produced {len(raw_chunks)} chunks, exceeding maximum limit of {self.settings.MAX_DOCUMENT_CHUNKS} chunks."
            )

        return raw_chunks
