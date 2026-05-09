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

# In-memory anomaly tracking (safe: no PII, only user_id + timestamps)
_exceeded_events: list[dict] = []

# Config
MAX_REQUESTS = 20       # per window
WINDOW_SECONDS = 60     # 1-minute window

# Keep only the most recent events to bound memory
_MAX_EVENT_HISTORY = 200


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

        _exceeded_events.append(
            {
                "user_id": user_id,
                "ts": now,
                "retry_after_s": retry_after,
            }
        )
        # trim
        if len(_exceeded_events) > _MAX_EVENT_HISTORY:
            del _exceeded_events[:-_MAX_EVENT_HISTORY]

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    _request_windows[user_id].append(now)


def get_rate_limit_stats(now: float | None = None) -> dict:
    """Return safe anomaly counters (no PII)."""
    now = now or time.time()

    def count_since(seconds: float) -> int:
        cutoff = now - seconds
        return sum(
            1
            for ev in _exceeded_events
            if isinstance(ev.get("ts"), (int, float)) and ev["ts"] >= cutoff
        )

    return {
        "exceeded_last_60s": count_since(60),
        "exceeded_last_24h": count_since(24 * 3600),
        "recent_exceeded_events": [
            {
                "user_id": ev.get("user_id"),
                "ts": ev.get("ts"),
                "retry_after_s": ev.get("retry_after_s"),
            }
            for ev in _exceeded_events[-10:]
        ],
    }
