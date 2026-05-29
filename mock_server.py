"""
Mock server for testing the retry engine.

Endpoints:
    GET /health              — 200, confirms the mock is running
    POST /unstable           — returns 500 for the first `fail_count` hits, then 200
    POST /always-fail        — always returns 500 (for dead-letter testing)
    POST /bad-request        — always returns 404 (for 4xx terminal testing)
    POST /unstable/reset     — resets the /unstable failure counter

Usage:
    uv run uvicorn mock_server:app --port 9000
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Server")

# --- state ----------------------------------------------------------------- #

FAIL_COUNT = 3  # how many 500s before /unstable starts returning 200
_hit_counter: int = 0


# --- helpers --------------------------------------------------------------- #


def _reset_counter() -> None:
    global _hit_counter
    _hit_counter = 0


# --- routes ---------------------------------------------------------------- #


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/unstable")
async def unstable(request: Request) -> JSONResponse:
    """Return 500 for the first FAIL_COUNT hits, then 200."""
    global _hit_counter
    _hit_counter += 1

    if _hit_counter <= FAIL_COUNT:
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal server error",
                "attempt": _hit_counter,
                "remaining_failures": FAIL_COUNT - _hit_counter,
            },
        )

    body = await request.body()
    return JSONResponse(
        status_code=200,
        content={
            "message": "success",
            "attempt": _hit_counter,
            "echo": body.decode() if body else None,
        },
    )


@app.post("/always-fail")
async def always_fail() -> JSONResponse:
    """Always returns 500 — used to test dead-lettering at maxRetries."""
    return JSONResponse(
        status_code=500,
        content={"error": "permanent server failure"},
    )


@app.post("/bad-request")
async def bad_request() -> JSONResponse:
    """Always returns 404 — used to test that 4xx is terminal."""
    return JSONResponse(
        status_code=404,
        content={"error": "not found"},
    )


@app.post("/unstable/reset")
async def reset() -> dict:
    """Reset the /unstable hit counter back to zero."""
    _reset_counter()
    return {"status": "reset", "fail_count": FAIL_COUNT}
