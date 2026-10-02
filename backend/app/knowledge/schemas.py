from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICTING = "conflicting"


class RetrievalStatus(str, Enum):
    FOUND = "FOUND"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NOT_FOUND = "NOT_FOUND"


# ==============================================================================
# KNOWLEDGE BASE SCHEMAS
# ==============================================================================

class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class KnowledgeBaseUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, pattern="^(active|archived)$")


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    document_count: Optional[int] = None


# ==============================================================================
# DOCUMENT SCHEMAS
# ==============================================================================

class DocumentCreateTextRequest(BaseModel):
    """Direct text document ingestion request."""
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, description="Raw text content to ingest")


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    name: str
    original_filename: str
    content_type: str
    source_type: str
    status: str
    current_version_id: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    content_hash: str
    processing_status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime


# ==============================================================================
# RETRIEVAL & CITATION SCHEMAS
# ==============================================================================

class CitationSource(BaseModel):
    """
    CRITICAL REQUIREMENT: Citations & Provenance Tracking.
    Every retrieved chunk MUST carry verified provenance back to its exact source.
    """
    model_config = ConfigDict(from_attributes=True)

    tenant_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    document_name: str
    chunk_id: uuid.UUID
    chunk_index: int
    page_number: Optional[int] = None
    content: str
    similarity_score: float
    metadata: Optional[Dict[str, Any]] = None


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: Optional[int] = Field(default=5, ge=1, le=50)
    min_similarity: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RetrievalResponse(BaseModel):
    """
    Structured retrieval result with explicit confidence evaluation.
    Integrates with YAVURA's Factual Truth principle:
    - FOUND: Sufficient verified similarity found.
    - LOW_CONFIDENCE: Matches exist but are below high-confidence threshold.
    - NOT_FOUND: No relevant knowledge found. AI must decline to invent facts.
    """
    status: RetrievalStatus
    query: str
    items: List[CitationSource] = Field(default_factory=list)
    top_similarity: float = 0.0
    explanation: Optional[str] = None


# ==============================================================================
# FACTUAL TRUTH & GROUNDING VERIFICATION (PHASE 1 PRESERVED)
# ==============================================================================

class VerifiedKnowledgeItem(BaseModel):
    """
    Represents an atomic, verified truth from business documentation.
    AI responses discussing factual business attributes (pricing, policies, availability)
    MUST be grounded in items with verification_status == VERIFIED.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    topic: str
    content: str
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    source_document_id: Optional[uuid.UUID] = None
    last_verified_at: Optional[datetime] = None


class GroundingCheckResult(BaseModel):
    """Result of factual truth verification before an AI response is returned."""
    is_grounded: bool
    unverified_claims: List[str] = Field(default_factory=list)
    grounded_claims: List[str] = Field(default_factory=list)
    suggested_action: str = Field(
        default="ALLOW",
        description="ALLOW, CLARIFY, or ESCALATE_TO_HUMAN",
    )
    explanation: Optional[str] = None
