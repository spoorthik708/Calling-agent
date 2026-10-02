from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class YavuraBaseException(Exception):
    """Base exception for all YAVURA domain exceptions."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


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
    elif isinstance(exc, EntityNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": exc.message, "details": exc.details},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "INTERNAL_ERROR", "message": "An unexpected server error occurred."},
    )
