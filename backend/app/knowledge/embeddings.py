from abc import ABC, abstractmethod
import hashlib
import math
import re
from typing import Dict, List, Optional
from app.core.config import get_settings
from app.core.exceptions import YavuraException
from app.core.logging import get_logger

logger = get_logger("yavura.knowledge.embeddings")


class EmbeddingProviderError(YavuraException):
    """Raised when embedding generation fails."""
    def __init__(self, message: str, code: str = "EMBEDDING_FAILED"):
        super().__init__(message=message, code=code)


class EmbeddingDimensionMismatchError(EmbeddingProviderError):
    """Raised when generated vector does not match expected dimension."""
    def __init__(self, expected: int, received: int):
        super().__init__(
            message=f"Embedding dimension mismatch: expected {expected}, received {received}",
            code="EMBEDDING_DIMENSION_MISMATCH",
        )


class EmbeddingProvider(ABC):
    """
    Abstract interface for vector embedding generation.
    Decouples document ingestion and RAG retrieval from specific model providers.
    """
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Generates an embedding vector for a single string."""
        pass

    @abstractmethod
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Batch generates embeddings for multiple strings."""
        pass


class MockEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic Mock Embedding Provider for testing and local development.
    Generates unit-normalized 1536-dimensional vectors deterministically based
    on text hashing and vocabulary frequencies.

    Invariants:
    - Same text -> identical vector.
    - Texts sharing key terms -> high cosine similarity (>0.70).
    - Unrelated texts -> low cosine similarity (<0.30).
    - Normalized to unit length (L2 norm = 1.0) so cosine distance is consistent.
    """
    def __init__(
        self,
        dimension: int = 1536,
        model_name: str = "mock-embedding-v1",
    ):
        self._dimension = dimension
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _generate_vector(self, text: str) -> List[float]:
        if not text or not text.strip():
            # Zero-padded unit vector
            v = [0.0] * self._dimension
            v[0] = 1.0
            return v

        vec = [0.0] * self._dimension
        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            v = [0.0] * self._dimension
            v[0] = 1.0
            return v

        # Distribute token hashes into vector dimensions
        for token in tokens:
            token_bytes = token.encode("utf-8")
            h = hashlib.sha256(token_bytes).digest()
            for i in range(0, 16, 2):
                idx = int.from_bytes(h[i:i+2], "big") % self._dimension
                val = (int.from_bytes(h[i+2:i+4], "big") - 32768) / 32768.0
                vec[idx] += val

        # L2 Normalize vector to unit length
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0

        if len(vec) != self._dimension:
            raise EmbeddingDimensionMismatchError(self._dimension, len(vec))

        return vec

    async def embed_text(self, text: str) -> List[float]:
        return self._generate_vector(text)

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._generate_vector(t) for t in texts]


class EmbeddingProviderFactory:
    """Factory to manage and retrieve configured embedding providers."""
    _registry: Dict[str, EmbeddingProvider] = {}

    @classmethod
    def register(cls, name: str, provider: EmbeddingProvider) -> None:
        cls._registry[name.lower()] = provider

    @classmethod
    def get_provider(cls, name: Optional[str] = None) -> EmbeddingProvider:
        settings = get_settings()
        provider_name = (name or settings.EMBEDDING_PROVIDER).lower()

        if provider_name not in cls._registry:
            if provider_name == "mock":
                cls._registry["mock"] = MockEmbeddingProvider(
                    dimension=settings.EMBEDDING_DIMENSION,
                    model_name=settings.EMBEDDING_MODEL,
                )
            else:
                logger.error(f"Requested embedding provider '{provider_name}' is not registered.")
                raise EmbeddingProviderError(
                    f"Embedding provider '{provider_name}' is not registered or configured. "
                    "Please register an authorized provider adapter before use."
                )

        return cls._registry[provider_name]
