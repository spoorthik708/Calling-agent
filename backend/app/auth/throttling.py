from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional
from fastapi import HTTPException, Request, status
from app.core.config import get_settings


class RateLimiterInterface(ABC):
    """Clean abstraction for authentication endpoint rate limiting and throttling."""
    @abstractmethod
    def check_rate_limit(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        """Returns True if within rate limit; False if rate limit exceeded."""
        pass


class InMemoryRateLimiter(RateLimiterInterface):
    """
    In-memory sliding window rate limiter for development and single-instance deployments.
    Can be replaced in production with a Redis/Distributed limiter implementing RateLimiterInterface.
    """
    def __init__(self):
        self._attempts: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_rate_limit(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - window_seconds

        with self._lock:
            # Filter out older attempts
            valid_attempts = [ts for ts in self._attempts[key] if ts > cutoff]
            if len(valid_attempts) >= max_attempts:
                self._attempts[key] = valid_attempts
                return False
            valid_attempts.append(now)
            self._attempts[key] = valid_attempts
            return True


# Global default instance
default_rate_limiter = InMemoryRateLimiter()


def get_client_ip(
    request: Request,
    trust_proxy_headers: Optional[bool] = None,
    trusted_proxy_ips: Optional[List[str]] = None,
) -> str:
    """
    Extracts client IP safely with reverse-proxy verification.

    SEC-06 Security Invariants:
    1. If trust_proxy_headers is False: always return direct request.client.host.
       Header spoofing like X-Forwarded-For is strictly ignored.
    2. If trust_proxy_headers is True: inspect forwarding headers ONLY IF the direct
       peer (request.client.host) is in the configured trusted_proxy_ips list.
       Untrusted callers directly hitting the API cannot spoof their IP address.
    3. When trusted, parses the leftmost IP from X-Forwarded-For (client IP).
    """
    settings = get_settings()
    if trust_proxy_headers is None:
        trust_proxy_headers = settings.TRUST_PROXY_HEADERS
    if trusted_proxy_ips is None:
        trusted_proxy_ips = settings.TRUSTED_PROXY_IPS

    direct_ip = request.client.host if request.client else "unknown"

    if not trust_proxy_headers:
        return direct_ip

    if direct_ip not in trusted_proxy_ips:
        # Untrusted direct connection; ignore forwarded headers
        return direct_ip

    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[0]

    return direct_ip


def enforce_rate_limit(
    request: Request,
    action: str = "auth",
    max_attempts: int = 15,
    window_seconds: int = 60,
    limiter: RateLimiterInterface = default_rate_limiter,
    trust_proxy_headers: Optional[bool] = None,
    trusted_proxy_ips: Optional[List[str]] = None,
) -> None:
    """
    Enforces rate limit by verified client IP address.

    Deployment requirements:
    - Direct deployment: keep TRUST_PROXY_HEADERS=False (default).
    - Reverse-proxy deployment (e.g. AWS ALB, Cloudflare, Nginx): configure:
        TRUST_PROXY_HEADERS=True
        TRUSTED_PROXY_IPS=["10.0.0.1", "127.0.0.1", ...]
      matching ONLY the internal private IP addresses or loopback of the trusted proxy.
    """
    client_ip = get_client_ip(
        request,
        trust_proxy_headers=trust_proxy_headers,
        trusted_proxy_ips=trusted_proxy_ips,
    )
    key = f"{action}:{client_ip}"
    if not limiter.check_rate_limit(key, max_attempts, window_seconds):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests. Please try again later.",
        )
