import time
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func as sqlfunc

from app.models import Attempt, Request


async def create_request(session: AsyncSession, data: dict) -> Request:
    request = Request(**data)
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request


async def get_request_by_id(session: AsyncSession, request_id: str) -> Request | None:
    result = await session.execute(
        select(Request)
        .where(Request.id == request_id)
        .options(selectinload(Request.attempts))
    )
    return result.scalar_one_or_none()


async def list_requests(
    session: AsyncSession, status: str | None = None
) -> Sequence[Request]:
    query = select(Request).options(selectinload(Request.attempts))
    if status is not None:
        query = query.where(Request.status == status)
    result = await session.execute(query)
    return result.scalars().all()


async def fetch_due_requests(session: AsyncSession) -> Sequence[Request]:
    now = time.time()
    result = await session.execute(
        select(Request)
        .where(
            Request.status.in_(["pending", "retrying"]),
            Request.next_retry_at <= now,
        )
        .limit(50)
    )
    return result.scalars().all()


async def update_request(session: AsyncSession, request_id: str, data: dict) -> None:
    data["updated_at"] = sqlfunc.now()
    await session.execute(
        update(Request).where(Request.id == request_id).values(**data)
    )
    await session.commit()


async def insert_attempt(session: AsyncSession, data: dict) -> Attempt:
    attempt = Attempt(**data)
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt
