from datetime import datetime
from enum import Enum
from typing import List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICTING = "conflicting"


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
