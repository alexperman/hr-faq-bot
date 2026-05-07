"""
Simple in-memory rate limiter for the /ask endpoint.
Tracks requests per user_id using a sliding window counter.
For production, replace with Redis-based rate limiting.
"""
import time
from collections import defaultdict
from fastapi import HTTPException, status

# sliding window: user_id -> list of request timestamps
_request_windows: dict[int, list[float]] = defaultdict(list)

# Config
MAX_REQUESTS = 20       # per window
WINDOW_SECONDS = 60     # 1-minute window


def _cleanup_window(user_id: int, now: float) -> None:
    """Remove timestamps outside the current window."""
    cutoff = now - WINDOW_SECONDS
    _request_windows[user_id] = [
        ts for ts in _request_windows[user_id] if ts > cutoff
    ]


def check_rate_limit(user_id: int) -> None:
    """
    Raises HTTPException 429 if user has exceeded the rate limit.
    Call this at the start of any rate-limited endpoint.
    """
    now = time.time()
    _cleanup_window(user_id, now)

    if len(_request_windows[user_id]) >= MAX_REQUESTS:
        oldest = _request_windows[user_id][0]
        retry_after = int(oldest + WINDOW_SECONDS - now) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    _request_windows[user_id].append(now)
