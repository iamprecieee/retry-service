from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository
from app.database import get_session
from app.schemas import (
    RequestCreate,
    RequestListData,
    RequestQueued,
    RequestResponse,
    SuccessResponse,
)

router = APIRouter(tags=["requests"])


@router.post("/request", response_model=SuccessResponse[RequestQueued], status_code=201)
async def enqueue_request(
    payload: RequestCreate,
    session: AsyncSession = Depends(get_session),
) -> SuccessResponse[RequestQueued]:
    data = {
        "url": str(payload.url),
        "method": payload.method,
        "body": payload.body,
        "max_retries": payload.max_retries,
        "backoff_ms": payload.backoff_ms,
        "next_retry_at": 0.0,
    }
    request = await repository.create_request(session, data)
    return SuccessResponse(
        message="request queued",
        data=RequestQueued(id=request.id, status=request.status),
    )


@router.get(
    "/requests/{request_id}",
    response_model=SuccessResponse[RequestResponse],
    status_code=200,
)
async def get_request(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> SuccessResponse[RequestResponse]:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="request not found")
    return SuccessResponse(
        message="request retrieved",
        data=RequestResponse.model_validate(request),
    )


@router.get("/requests", response_model=SuccessResponse[RequestListData], status_code=200)
async def list_requests(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> SuccessResponse[RequestListData]:
    requests = await repository.list_requests(session, status=status)
    return SuccessResponse(
        message="requests retrieved",
        data=RequestListData(
            requests=[RequestResponse.model_validate(req) for req in requests],
            count=len(requests),
        ),
    )
