import asyncio
import logging
import random
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.config import settings
from app.database import AsyncSessionFactory

logger = logging.getLogger(__name__)


async def process_request(request_id: str) -> None:
    async with AsyncSessionFactory() as session:
        request = await repository.get_request_by_id(session, request_id)
        if request is None:
            return

        jitter = random.uniform(0.8, 1.2)
        wait_ms = min(
            int(request.backoff_ms * (2**request.attempt_count) * jitter),
            settings.max_wait_ms,
        )

        # Mark as retrying immediately to prevent a concurrent worker cycle
        # from picking up the same row before this attempt completes.
        await repository.update_request(
            session,
            request.id,
            {
                "status": "retrying",
                "next_retry_at": time.time() + wait_ms / 1000,
            },
        )

    status_code = None
    error = None
    response_body = None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
        ) as client:
            if request.body is not None:
                response = await client.request(
                    method=request.method,
                    url=request.url,
                    content=request.body,
                )
            else:
                response = await client.request(
                    method=request.method,
                    url=request.url,
                )
            status_code = response.status_code
            response_body = response.text

    except httpx.TimeoutException as exc:
        error = f"timeout: {exc}"
    except httpx.RequestError as exc:
        error = f"network error: {exc}"

    attempt_number = request.attempt_count + 1

    async with AsyncSessionFactory() as session:
        await repository.insert_attempt(
            session,
            {
                "request_id": request.id,
                "attempt_number": attempt_number,
                "status_code": status_code,
                "error": error,
                "response_body": response_body,
                "wait_ms": wait_ms,
            },
        )

        await _update_request_after_attempt(
            session=session,
            request=request,
            attempt_number=attempt_number,
            status_code=status_code,
            error=error,
            response_body=response_body,
            wait_ms=wait_ms,
        )


async def _update_request_after_attempt(
    session: AsyncSession,
    request,
    attempt_number: int,
    status_code: int | None,
    error: str | None,
    response_body: str | None,
    wait_ms: int,
) -> None:
    is_success = status_code is not None and 200 <= status_code < 300
    is_client_error = status_code is not None and 400 <= status_code < 500
    exhausted = attempt_number > request.max_retries

    if is_success:
        await repository.update_request(
            session,
            request.id,
            {
                "status": "completed",
                "attempt_count": attempt_number,
                "result": response_body,
                "last_error": None,
                "next_retry_at": None,
            },
        )
        return

    if is_client_error or exhausted:
        last_error = f"http {status_code}" if status_code is not None else error
        await repository.update_request(
            session,
            request.id,
            {
                "status": "failed",
                "attempt_count": attempt_number,
                "last_error": last_error,
                "next_retry_at": None,
            },
        )
        return

    await repository.update_request(
        session,
        request.id,
        {
            "status": "retrying",
            "attempt_count": attempt_number,
            "last_error": error or f"http {status_code}",
            "next_retry_at": time.time() + wait_ms / 1000,
        },
    )


async def run_worker() -> None:
    logger.info("worker started")

    while True:
        try:
            async with AsyncSessionFactory() as session:
                due_requests = await repository.fetch_due_requests(session)

            if due_requests:
                await asyncio.gather(*[process_request(req.id) for req in due_requests])
        except asyncio.CancelledError:
            logger.info("worker stopped")
            raise
        except Exception:
            logger.exception("worker cycle failed")

        await asyncio.sleep(settings.worker_interval_ms / 1000)
