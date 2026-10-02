from abc import ABC, abstractmethod
from typing import List, Optional
import uuid
from app.knowledge.schemas import GroundingCheckResult, VerifiedKnowledgeItem


class KnowledgeRetrieverInterface(ABC):
    """
    Interface for tenant-isolated knowledge retrieval.
    All retrieval queries MUST strictly filter by tenant_id.
    """
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        tenant_id: uuid.UUID,
        top_k: int = 5,
        min_similarity: float = 0.70,
    ) -> List[VerifiedKnowledgeItem]:
        """Retrieves verified knowledge items strictly within the specified tenant boundary."""
        pass


class GroundingVerifierInterface(ABC):
    """
    CORE PRODUCT PRINCIPLE ENFORCER:
    Validates whether an AI candidate response is strictly grounded in verified business facts.
    If facts are missing or ungrounded, prevents the model from hallucinating policies/prices.
    """
    @abstractmethod
    async def verify_grounding(
        self,
        candidate_response: str,
        verified_context: List[VerifiedKnowledgeItem],
    ) -> GroundingCheckResult:
        """Verifies candidate response against verified business knowledge."""
        pass


class VectorStoreInterface(ABC):
    """Abstraction for vector embeddings store (e.g. pgvector)."""
    @abstractmethod
    async def upsert_vector(
        self,
        chunk_id: uuid.UUID,
        tenant_id: uuid.UUID,
        embedding: List[float],
        metadata: dict,
    ) -> None:
        pass

    @abstractmethod
    async def query_vectors(
        self,
        query_embedding: List[float],
        tenant_id: uuid.UUID,
        top_k: int = 5,
    ) -> List[dict]:
        pass
