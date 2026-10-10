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


# Phase 5 Tool & Action Exceptions
class ToolNotAssignedError(YavuraBaseException):
    """Raised when an agent attempts to execute a tool not explicitly assigned to it."""
    pass


class ToolDisabledError(YavuraBaseException):
    """Raised when attempting to execute a deactivated or archived tool."""
    pass


class ToolAuthorizationError(YavuraBaseException):
    """Raised when caller or agent lacks required permissions to execute tool."""
    pass


class ToolValidationError(YavuraBaseException):
    """Raised when tool inputs or schemas fail validation."""
    pass


class ToolExecutionError(YavuraBaseException):
    """Raised when a tool encounters an unhandled runtime error during execution."""
    pass


class ToolTimeoutError(YavuraBaseException):
    """Raised when tool execution exceeds configured timeout boundary."""
    pass


class ToolRateLimitError(YavuraBaseException):
    """Raised when tenant tool execution exceeds rate limit quota."""
    pass


class CredentialResolutionError(YavuraBaseException):
    """Raised when resolving tool credential reference fails server-side."""
    pass


class SSRFBlockedError(YavuraBaseException):
    """Raised when HTTP tool destination target violates SSRF security boundaries."""
    pass


class ToolIdempotencyConflictError(YavuraBaseException):
    """Raised when tool idempotency key is reused with a conflicting payload."""
    pass


# ==========================================
# Voice Domain Exceptions (Phase 6)
# ==========================================

class VoiceSessionNotFoundError(EntityNotFoundError):
    """Raised when a voice session is not found in the tenant context."""
    pass


class VoiceSessionStateError(YavuraBaseException):
    """Raised on invalid state transitions in the voice session state machine."""
    pass


class VoiceProviderError(YavuraBaseException):
    """Raised when an external voice provider (STT/TTS) encounters an unrecoverable error."""
    pass


class VoiceConfigurationError(YavuraBaseException):
    """Raised when voice provider configuration is invalid or missing required keys."""
    pass


class VoiceAudioFormatError(YavuraBaseException):
    """Raised when audio frame metadata or payload format is malformed or inconsistent."""
    pass


class AudioBufferOverflowError(YavuraBaseException):
    """Raised when audio buffer or queue exceeds configured memory boundaries."""
    pass


class STTTranscriptionError(YavuraBaseException):
    """Raised when audio transcription fails."""
    pass


class TTSSynthesisError(YavuraBaseException):
    """Raised when text-to-speech synthesis fails."""
    pass


class VoiceRateLimitError(YavuraBaseException):
    """Raised when tenant exceeds voice session or audio ingestion rate limits."""
    pass


# ==========================================
# Telephony Domain Exceptions (Phase 7)
# ==========================================

class CallSessionNotFoundError(EntityNotFoundError):
    """Raised when a call session is not found in the tenant context."""
    pass


class TelephonyProviderError(YavuraBaseException):
    """Raised when PSTN/SIP telephony vendor API fails or invalid parameters supplied."""
    pass


class TelephonyPermissionError(YavuraBaseException):
    """Raised when user or tenant lacks calling permissions."""
    pass


def http_exception_from_domain(exc: YavuraBaseException) -> HTTPException:
    """Maps domain exceptions to appropriate HTTPExceptions."""
    if isinstance(exc, (VoiceSessionNotFoundError, EntityNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, VoiceSessionStateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_STATE_TRANSITION", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, (AudioBufferOverflowError, VoiceConfigurationError, VoiceAudioFormatError)):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VOICE_ERROR", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, VoiceRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "VOICE_RATE_LIMITED", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, (VoiceProviderError, STTTranscriptionError, TTSSynthesisError)):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "VOICE_PROVIDER_ERROR", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, TenantIsolationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_ACCESS_DENIED", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, FactualTruthViolationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "FACTUAL_TRUTH_VIOLATION", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, SSRFBlockedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SSRF_SECURITY_VIOLATION", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, (ToolExecutionSecurityError, ToolValidationError)):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "TOOL_VALIDATION_ERROR", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, (ToolNotAssignedError, ToolAuthorizationError)):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TOOL_ACCESS_DENIED", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, ToolDisabledError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "TOOL_DISABLED", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, ToolTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "TOOL_TIMEOUT", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, ToolRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "TOOL_RATE_LIMITED", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, (IdempotencyConflictError, ToolIdempotencyConflictError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": exc.message, "details": exc.details},
        )
    elif isinstance(exc, CredentialResolutionError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREDENTIAL_ERROR", "message": "Failed to resolve secure tool credentials."},
        )
    elif isinstance(exc, (ToolExecutionError, LLMProviderError)):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "EXECUTION_ERROR", "message": exc.message, "details": exc.details},
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
