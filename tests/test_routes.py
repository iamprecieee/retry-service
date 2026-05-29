import pytest
from httpx import AsyncClient
from app.database import AsyncSessionFactory
from app import repository

pytestmark = pytest.mark.asyncio


async def test_enqueue_request_success(async_client: AsyncClient):
    response = await async_client.post(
        "/request",
        json={
            "url": "http://example.com",
            "method": "POST",
            "body": '{"key": "value"}',
            "max_retries": 3,
            "backoff_ms": 500,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "request queued"
    assert "id" in data["data"]
    assert data["data"]["status"] == "pending"


async def test_enqueue_request_invalid_url(async_client: AsyncClient):
    response = await async_client.post(
        "/request", json={"url": "not-a-url", "method": "POST"}
    )
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"


async def test_enqueue_request_unsupported_method(async_client: AsyncClient):
    response = await async_client.post(
        "/request", json={"url": "http://example.com", "method": "OPTIONS"}
    )
    assert response.status_code == 422


async def test_enqueue_request_invalid_backoff(async_client: AsyncClient):
    response = await async_client.post(
        "/request",
        json={"url": "http://example.com", "method": "GET", "backoff_ms": 50},
    )
    assert response.status_code == 422


async def test_get_request_not_found(async_client: AsyncClient):
    response = await async_client.get("/requests/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["status"] == "error"


async def test_get_request_success(async_client: AsyncClient):
    resp1 = await async_client.post(
        "/request", json={"url": "http://example.com", "method": "GET"}
    )
    req_id = resp1.json()["data"]["id"]

    resp2 = await async_client.get(f"/requests/{req_id}")
    assert resp2.status_code == 200
    data = resp2.json()["data"]
    assert data["id"] == req_id
    assert data["attempts"] == []


async def test_list_requests_all(async_client: AsyncClient):
    await async_client.post(
        "/request", json={"url": "http://example.com", "method": "GET"}
    )
    await async_client.post(
        "/request", json={"url": "http://example.org", "method": "GET"}
    )

    resp = await async_client.get("/requests")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] >= 2
    assert len(data["requests"]) >= 2


async def test_list_requests_by_status(async_client: AsyncClient):
    resp1 = await async_client.post(
        "/request", json={"url": "http://example.com", "method": "GET"}
    )
    req_id = resp1.json()["data"]["id"]

    async with AsyncSessionFactory() as session:
        await repository.update_request(session, req_id, {"status": "failed"})

    resp2 = await async_client.get("/requests?status=failed")
    data = resp2.json()["data"]
    assert data["count"] == 1
    assert data["requests"][0]["id"] == req_id

    resp3 = await async_client.get("/requests?status=pending")
    # All pending might be 0 if the previous test's pending was deleted by the fixture
    assert resp3.json()["data"]["count"] == 0


async def test_list_requests_unknown_status(async_client: AsyncClient):
    resp = await async_client.get("/requests?status=unknown")
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 0
