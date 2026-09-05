import pytest
from fastapi import HTTPException
from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in response.headers


async def test_unconfigured_ai_orchestrator_returns_503() -> None:
    from app.ai.registry import get_orchestrator

    with pytest.raises(HTTPException) as exc_info:
        get_orchestrator("nonexistent")()
    assert exc_info.value.status_code == 503
