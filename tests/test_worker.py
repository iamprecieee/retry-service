import pytest
import time
import httpx
from app.database import AsyncSessionFactory
from app import repository
from app.worker import process_request

pytestmark = pytest.mark.asyncio


async def create_dummy_request(status="pending", max_retries=3, backoff_ms=1000):
    async with AsyncSessionFactory() as session:
        return await repository.create_request(
            session,
            {
                "url": "http://example.com",
                "method": "GET",
                "body": None,
                "max_retries": max_retries,
                "backoff_ms": backoff_ms,
                "next_retry_at": 0.0,
                "status": status,
            },
        )


def make_client(status_code: int = 200, text: str = "ok", raise_exc=None):
    def handler(request):
        if raise_exc:
            raise raise_exc
        return httpx.Response(status_code, text=text)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_worker_2xx_completed():
    req = await create_dummy_request()
    client = make_client(200, "success")
    await process_request(req.id, client)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.status == "completed"
        assert db_req.result == "success"
        assert db_req.attempt_count == 1
        assert len(db_req.attempts) == 1


async def test_worker_4xx_failed_immediately():
    req = await create_dummy_request(max_retries=5)
    client = make_client(400)
    await process_request(req.id, client)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.status == "failed"
        assert db_req.attempt_count == 1


async def test_worker_5xx_retrying():
    req = await create_dummy_request()
    client = make_client(500)
    await process_request(req.id, client)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.status == "retrying"
        assert db_req.attempt_count == 1
        assert db_req.next_retry_at is not None
        assert db_req.next_retry_at > time.time()


async def test_worker_backoff_doubling_and_jitter():
    req = await create_dummy_request(backoff_ms=100)
    client = make_client(500)

    await process_request(req.id, client)
    await process_request(req.id, client)
    await process_request(req.id, client)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.attempt_count == 3
        attempts = db_req.attempts
        w1, w2, w3 = attempts[0].wait_ms, attempts[1].wait_ms, attempts[2].wait_ms

        assert w1 is not None and w2 is not None and w3 is not None

        # Expected base waits before jitter: 100, 200, 400
        # Jitter is 0.8 to 1.2
        assert 80 <= w1 <= 120
        assert 160 <= w2 <= 240
        assert 320 <= w3 <= 480
        # Ensure not exactly backoff_ms * 2^n due to jitter
        assert w2 != 200 or w3 != 400


async def test_worker_max_retries_exhausted():
    req = await create_dummy_request(max_retries=2)
    client = make_client(500)

    await process_request(req.id, client)  # att 1
    await process_request(req.id, client)  # att 2
    await process_request(req.id, client)  # att 3 (fails)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.status == "failed"
        assert db_req.attempt_count == 3


async def test_worker_max_retries_zero():
    req = await create_dummy_request(max_retries=0)
    client = make_client(500)
    await process_request(req.id, client)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.status == "failed"
        assert db_req.attempt_count == 1


async def test_worker_network_error_is_retryable():
    req = await create_dummy_request()
    client = make_client(raise_exc=httpx.ConnectError("refused"))
    await process_request(req.id, client)

    async with AsyncSessionFactory() as session:
        db_req = await repository.get_request_by_id(session, req.id)
        assert db_req is not None
        assert db_req.status == "retrying"
        assert db_req.last_error is not None
        assert "refused" in db_req.last_error
