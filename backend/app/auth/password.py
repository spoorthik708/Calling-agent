from typing import Optional
from app.core.exceptions import YavuraBaseException


class PasswordPolicyError(YavuraBaseException):
    """Raised when a password violates baseline security policy."""
    pass


class PasswordPolicy:
    """
    Baseline password policy validator.
    Configurable and extensible without leaking sensitive internal validation criteria.
    """
    MIN_LENGTH = 12
    MAX_LENGTH = 128

    @classmethod
    def validate(cls, password: Optional[str]) -> None:
        if not password or not isinstance(password, str):
            raise PasswordPolicyError("Password is required and cannot be empty.")

        # Reject whitespace-only passwords
        trimmed = password.strip()
        if not trimmed:
            raise PasswordPolicyError("Password cannot consist solely of whitespace.")

        if len(password) < cls.MIN_LENGTH:
            raise PasswordPolicyError(
                f"Password must be at least {cls.MIN_LENGTH} characters long."
            )

        if len(password) > cls.MAX_LENGTH:
            raise PasswordPolicyError(
                f"Password cannot exceed {cls.MAX_LENGTH} characters."
            )


def validate_password(password: str) -> None:
    """Convenience helper to enforce password policy."""
    PasswordPolicy.validate(password)
