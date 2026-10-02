import pytest
from starlette.requests import Request
from fastapi import HTTPException

from app.auth.throttling import (
    InMemoryRateLimiter,
    enforce_rate_limit,
    get_client_ip,
)
from app.core.config import Settings


def make_request(client_host: str, headers: dict = None) -> Request:
    """Helper to build a Starlette Request with specific client IP and headers."""
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": raw_headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_direct_client_mode_ignores_forwarded_headers():
    """
    SEC-06 Direct Client Mode Test:
    When trust_proxy_headers is False, the limiter uses request.client.host directly.
    Any X-Forwarded-For header sent by the client is strictly ignored.
    """
    req = make_request(
        client_host="192.168.1.100",
        headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2"},
    )
    ip = get_client_ip(req, trust_proxy_headers=False)
    assert ip == "192.168.1.100"


def test_trusted_proxy_mode_extracts_client_ip():
    """
    SEC-06 Trusted Proxy Mode Test:
    When trust_proxy_headers is True AND the request originates from a configured
    trusted proxy IP, the client IP is extracted from the X-Forwarded-For header.
    """
    trusted_proxy = "10.0.0.1"
    req = make_request(
        client_host=trusted_proxy,
        headers={"x-forwarded-for": "203.0.113.195, 10.0.0.1"},
    )
    ip = get_client_ip(
        req,
        trust_proxy_headers=True,
        trusted_proxy_ips=[trusted_proxy],
    )
    assert ip == "203.0.113.195"


def test_untrusted_forwarded_header_spoofing_attempt_rejected():
    """
    SEC-06 Spoofing Prevention Test:
    Even when trust_proxy_headers is True, if the connecting peer IP is NOT in
    trusted_proxy_ips, X-Forwarded-For is rejected to prevent arbitrary IP spoofing.
    """
    untrusted_attacker_ip = "198.51.100.77"
    req = make_request(
        client_host=untrusted_attacker_ip,
        headers={"x-forwarded-for": "1.1.1.1"},
    )
    # Trusted proxy infrastructure is defined as 10.0.0.1 only
    ip = get_client_ip(
        req,
        trust_proxy_headers=True,
        trusted_proxy_ips=["10.0.0.1"],
    )
    # Must use attacker's actual IP, rejecting the spoofed 1.1.1.1
    assert ip == untrusted_attacker_ip


def test_rate_limiter_enforces_limit_per_extracted_ip():
    """
    SEC-06 Rate Limiter Verification:
    Verifies that enforce_rate_limit throttles attempts based on the extracted IP
    and raises HTTP 429 when max_attempts is exceeded.
    """
    limiter = InMemoryRateLimiter()
    trusted_proxy = "127.0.0.1"

    # Client A: 203.0.113.10
    req_a = make_request(
        client_host=trusted_proxy,
        headers={"x-forwarded-for": "203.0.113.10"},
    )
    # Client B: 203.0.113.20
    req_b = make_request(
        client_host=trusted_proxy,
        headers={"x-forwarded-for": "203.0.113.20"},
    )

    # 3 allowed attempts
    for _ in range(3):
        enforce_rate_limit(
            req_a,
            action="login",
            max_attempts=3,
            window_seconds=60,
            limiter=limiter,
            trust_proxy_headers=True,
            trusted_proxy_ips=[trusted_proxy],
        )

    # 4th attempt from Client A must be blocked with 429
    with pytest.raises(HTTPException) as exc_info:
        enforce_rate_limit(
            req_a,
            action="login",
            max_attempts=3,
            window_seconds=60,
            limiter=limiter,
            trust_proxy_headers=True,
            trusted_proxy_ips=[trusted_proxy],
        )
    assert exc_info.value.status_code == 429
    assert "too many" in exc_info.value.detail.lower()

    # Client B should NOT be blocked (rate limit isolation per client IP)
    enforce_rate_limit(
        req_b,
        action="login",
        max_attempts=3,
        window_seconds=60,
        limiter=limiter,
        trust_proxy_headers=True,
        trusted_proxy_ips=[trusted_proxy],
    )


def test_config_trusted_proxy_settings():
    """
    SEC-06 Configuration Test:
    Verifies Settings defaults and string list parsing for TRUSTED_PROXY_IPS.
    """
    settings = Settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_IPS="10.0.0.1, 10.0.0.2 , 192.168.1.1",
    )
    assert settings.TRUST_PROXY_HEADERS is True
    assert settings.TRUSTED_PROXY_IPS == ["10.0.0.1", "10.0.0.2", "192.168.1.1"]
