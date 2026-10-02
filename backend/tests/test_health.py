import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_endpoint(async_client: AsyncClient):
    """
    Verifies Section 17 requirement:
    GET /health responds with 200 and expected status, service name, and version.
    """
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "yavura-api"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_api_v1_health_check_endpoint(async_client: AsyncClient):
    """Verifies that /api/v1/health is also reachable and consistent."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "yavura-api"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_security_headers_present_on_response(async_client: AsyncClient):
    """Verifies production security headers are attached to every response."""
    response = await async_client.get("/health")
    assert "X-Request-ID" in response.headers
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "X-Response-Time-Ms" in response.headers
