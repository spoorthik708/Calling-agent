from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Dict, Optional, Tuple, Union
import uuid
import bcrypt
from jose import JWTError, jwt
from app.core.config import get_settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against the bcrypt hash with consistent 72-byte truncation."""
    pwd_bytes = plain_password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generates a secure bcrypt hash of the password."""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def hash_token(raw_token: str) -> str:
    """Computes deterministic SHA-256 hash of a raw token for secure database storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_secure_token(nbytes: int = 48) -> str:
    """Generates a cryptographically strong, URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def create_refresh_token_pair() -> Tuple[str, str]:
    """
    Generates a new refresh token and its SHA-256 hash.
    Returns: (raw_token, token_hash).
    Only token_hash is stored in the database.
    """
    raw_token = generate_secure_token(48)
    token_hash = hash_token(raw_token)
    return raw_token, token_hash


def create_access_token(
    subject: Union[str, uuid.UUID],
    tenant_id: Union[str, uuid.UUID],
    role: str = "member",
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Creates a signed, short-lived JWT access token.
    Claims strictly limited to: sub, tenant_id, role, type="access", jti, iat, exp.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: Dict[str, Any] = {
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "role": str(role),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decodes and validates any JWT token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid or expired token: {str(e)}")


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and validates an access token specifically.
    Verifies signature, expiration, and ensures type == 'access'.
    """
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise ValueError("Invalid token type: expected access token")
    return payload
