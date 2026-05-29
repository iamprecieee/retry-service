"""
Test script — Retry Engine demo.

Submits three requests to the retry service and polls until each reaches a
terminal state, then prints a summary that clearly shows:
  1. Backoff doubling with jitter  (5xx → eventual success)
  2. 4xx is terminal               (single attempt, immediate failure)
  3. Dead-lettering at maxRetries  (all attempts fail, marked failed)

Prerequisites:
    # Terminal 1 — mock server
    uv run uvicorn mock_server:app --port 9000

    # Terminal 2 — retry service
    uv run uvicorn app.main:app --port 8000

    # Terminal 3 — run this script
    uv run python test_script.py
"""

import asyncio
import sys
from datetime import datetime

import httpx

SERVICE_URL = "http://127.0.0.1:8000"
MOCK_URL = "http://127.0.0.1:9000"
POLL_INTERVAL = 0.5  # seconds


def timestamp() -> str:
    """Return a short HH:MM:SS timestamp for live output."""
    return datetime.now().strftime("%H:%M:%S")


async def submit_request(client: httpx.AsyncClient, payload: dict) -> str:
    """POST /requests and return the request ID."""
    resp = await client.post(f"{SERVICE_URL}/requests", json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["data"]["id"]


async def poll_until_terminal(client: httpx.AsyncClient, request_id: str) -> dict:
    """Poll GET /requests/:id, printing each new attempt in real time."""
    seen_attempts = 0

    while True:
        resp = await client.get(f"{SERVICE_URL}/requests/{request_id}")
        resp.raise_for_status()
        data = resp.json()["data"]

        # Print any new attempts that appeared since last poll
        attempts = data.get("attempts", [])
        if len(attempts) > seen_attempts:
            for attempt in attempts[seen_attempts:]:
                num = attempt["attempt_number"]
                code = attempt["status_code"] or "—"
                wait = attempt["wait_ms"]
                err = attempt["error"] or "—"

                if code and int(code) >= 400:
                    wait_info = f"  → waiting {wait}ms before retry..." if wait else ""
                    print(f"  [{timestamp()}]  Attempt {num}: HTTP {code} ✗  {err}{wait_info}")
                else:
                    print(f"  [{timestamp()}]  Attempt {num}: HTTP {code} ✓  Success!")

            seen_attempts = len(attempts)

        if data["status"] in ("completed", "failed"):
            return data

        await asyncio.sleep(POLL_INTERVAL)


def print_header(title: str) -> None:
    width = 64
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def print_result(data: dict) -> None:
    """Print the final summary with backoff progression."""
    print()
    print(f"  Result     : {data['status'].upper()}")
    print(f"  Attempts   : {data['attempt_count']}")

    # Show backoff doubling between attempts
    attempts = data.get("attempts", [])
    waits = [a["wait_ms"] for a in attempts if a["wait_ms"] is not None]
    if len(waits) >= 2:
        print()
        print("  Backoff progression:")
        for i, w in enumerate(waits):
            ratio = f"  (×{w / waits[i-1]:.2f})" if i > 0 else ""
            print(f"    Attempt {i+1} wait: {w}ms{ratio}")
    print()


async def main() -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        # ── Preflight checks ──────────────────────────────────────────
        try:
            await client.get(f"{MOCK_URL}/health")
        except httpx.ConnectError:
            print("ERROR: Mock server is not running on port 9000.")
            print("Start it with: uv run uvicorn mock_server:app --port 9000")
            sys.exit(1)

        try:
            await client.get(f"{SERVICE_URL}/requests")
        except httpx.ConnectError:
            print("ERROR: Retry service is not running on port 8000.")
            print("Start it with: uv run uvicorn app.main:app --port 8000")
            sys.exit(1)

        # Reset the mock server's failure counter
        await client.post(f"{MOCK_URL}/unstable/reset")

        # ── Scenario 1: 5xx → success ────────────────────────────────
        print_header("Scenario 1: Transient 5xx → eventual success")
        print("  Submitting request to /unstable (fails 3 times, then 200)...")
        id1 = await submit_request(client, {
            "url": f"{MOCK_URL}/unstable",
            "method": "POST",
            "body": '{"payment": "test"}',
            "max_retries": 5,
            "backoff_ms": 1000,
        })
        print(f"  Queued with ID: {id1}")
        print("  Waiting for worker to process...")
        result1 = await poll_until_terminal(client, id1)
        print_result(result1)

        # ── Scenario 2: 4xx terminal ─────────────────────────────────
        print_header("Scenario 2: 4xx is terminal (never retried)")
        print("  Submitting request to /bad-request (always 404)...")
        id2 = await submit_request(client, {
            "url": f"{MOCK_URL}/bad-request",
            "method": "POST",
            "max_retries": 5,
            "backoff_ms": 1000,
        })
        print(f"  Queued with ID: {id2}")
        print("  Waiting for worker to process...")
        result2 = await poll_until_terminal(client, id2)
        print_result(result2)

        # ── Scenario 3: Dead-letter ──────────────────────────────────
        print_header("Scenario 3: Dead-letter at maxRetries")
        print("  Submitting request to /always-fail (always 500)...")
        id3 = await submit_request(client, {
            "url": f"{MOCK_URL}/always-fail",
            "method": "POST",
            "max_retries": 3,
            "backoff_ms": 1000,
        })
        print(f"  Queued with ID: {id3}")
        print("  Waiting for worker to exhaust retries...")
        result3 = await poll_until_terminal(client, id3)
        print_result(result3)

        # ── Summary ──────────────────────────────────────────────────
        print_header("Summary")
        print(f"  Scenario 1 (5xx→success)  : {result1['status']:<10} — {result1['attempt_count']} attempts")
        print(f"  Scenario 2 (4xx terminal) : {result2['status']:<10} — {result2['attempt_count']} attempt(s)")
        print(f"  Scenario 3 (dead-letter)  : {result3['status']:<10} — {result3['attempt_count']} attempts")
        print()


if __name__ == "__main__":
    asyncio.run(main())
