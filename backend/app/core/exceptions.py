from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class YavuraBaseException(Exception):
    """Base exception for all YAVURA domain exceptions."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.code = code or "DOMAIN_ERROR"


# Compatibility alias
YavuraException = YavuraBaseException


class TenantIsolationError(YavuraBaseException):
    """Raised when tenant isolation is violated or tenant context is missing/invalid."""
    pass


class FactualTruthViolationError(YavuraBaseException):
    """
    Raised when an AI generation attempts to output unverified business facts
    (pricing, discounts, policies, deadlines, guarantees) without factual grounding.
    """
    pass


class ToolExecutionSecurityError(YavuraBaseException):
    """Raised when tool execution violates security constraints or validation."""
    pass


class ToolNotFoundError(YavuraBaseException):
    """Raised when a requested tool does not exist in registry."""
    pass


class PasswordPolicyViolationError(YavuraBaseException):
    """Raised when password policy fails."""
    pass


class EntityNotFoundError(YavuraBaseException):
    """Raised when a requested resource is not found within tenant boundary."""
    pass


ResourceNotFoundError = EntityNotFoundError


class KnowledgeBaseNotFoundError(EntityNotFoundError):
    """Raised when knowledge base is not found."""
    pass


class DocumentNotFoundError(EntityNotFoundError):
    """Raised when document is not found."""
    pass


class KnowledgeIngestionError(YavuraBaseException):
    """Raised during document ingestion pipeline failures."""
    pass


class LowRetrievalConfidenceError(YavuraBaseException):
    """Raised when retrieved knowledge fails minimum confidence threshold."""
    pass


# Phase 4 Agent & Conversation Exceptions
class AgentNotFoundError(EntityNotFoundError):
    """Raised when agent is not found within tenant."""
    pass


class InactiveAgentExecutionError(YavuraBaseException):
    """Raised when attempting to execute an inactive or archived agent."""
    pass


class ConversationNotFoundError(EntityNotFoundError):
    """Raised when conversation is not found within tenant."""
    pass


class IdempotencyConflictError(YavuraBaseException):
    """Raised when an idempotency key is reused with a differing payload."""
    pass


class LLMProviderError(YavuraBaseException):
    """Raised when LLM provider returns an error, timeout, or invalid output."""
    pass


def http_exception_from_domain(exc: YavuraBaseException) -> HTTPException:
    """Maps domain exceptions to appropriate HTTPExceptions."""
    if isinstance(exc, TenantIsolationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_ACCESS_DENIED", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, FactualTruthViolationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "FACTUAL_TRUTH_VIOLATION", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, ToolExecutionSecurityError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "TOOL_SECURITY_VIOLATION", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, PasswordPolicyViolationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PASSWORD_POLICY_VIOLATION", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, InactiveAgentExecutionError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INACTIVE_AGENT", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, IdempotencyConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, LLMProviderError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "LLM_PROVIDER_ERROR", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, EntityNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": exc.message, "details": exc.details},
        )
    elif getattr(exc, "code", None) in (
        "UNSUPPORTED_FILE_TYPE",
        "FILE_TOO_LARGE",
        "INVALID_FILE",
        "DOCUMENT_EMPTY",
        "OCR_REQUIRED",
        "TEXT_EXTRACTION_FAILED",
        "INVALID_PDF",
        "ENCRYPTED_PDF",
        "INGESTION_FAILED",
        "EMBEDDING_FAILED",
    ):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "INTERNAL_ERROR", "message": "An unexpected server error occurred."},
    )
