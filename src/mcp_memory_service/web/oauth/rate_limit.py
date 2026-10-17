# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Lightweight in-process rate limiting + concurrency caps for OAuth endpoints.

No external dependency and no shared store: the limiter lives in the worker
process and keys on the client IP. It protects a single instance against
credential stuffing, brute force, and request floods on the auth endpoints.
For multi-instance deployments behind a load balancer, pair this with an
edge/proxy rate limit — this is the per-process backstop, not a global quota.
"""

import time
import logging
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException, Request, status

from ...config import (
    OAUTH_RATE_LIMIT_PER_MINUTE,
    OAUTH_RATE_LIMIT_MAX_CONCURRENT,
    OAUTH_TRUST_PROXY_HEADER,
)

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60.0


class _SlidingWindowRateLimiter:
    """Per-key sliding-window counter. Single-event-loop safe (no await between
    the read and the mutation of a key's deque)."""

    def __init__(self, max_per_window: int, window_seconds: float = _WINDOW_SECONDS):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = {}

    def check(self, key: str, now: float) -> bool:
        """Record a hit for ``key``. Return True if allowed, False if over limit."""
        cutoff = now - self.window_seconds
        bucket = self._hits.get(key)
        if bucket is None:
            bucket = deque()
            self._hits[key] = bucket

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_per_window:
            return False

        bucket.append(now)
        return True

    def prune(self, now: float) -> None:
        """Drop empty buckets so idle keys don't accumulate unbounded memory."""
        cutoff = now - self.window_seconds
        empty = []
        for key, bucket in self._hits.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                empty.append(key)
        for key in empty:
            del self._hits[key]


def _client_key(request: Request) -> str:
    # Behind a trusted reverse proxy the socket peer is the proxy, so every
    # client collapses into one bucket. When OAUTH_TRUST_PROXY_HEADER is set,
    # trust that header's left-most entry as the originating client instead.
    # Opt-in only: an untrusted client could otherwise spoof it to dodge the
    # per-IP limit.
    if OAUTH_TRUST_PROXY_HEADER and request is not None:
        forwarded = request.headers.get(OAUTH_TRUST_PROXY_HEADER)
        if forwarded:
            client = forwarded.split(",")[0].strip()
            if client:
                return client
    return request.client.host if request and request.client else "unknown"


_rate_limiter = _SlidingWindowRateLimiter(OAUTH_RATE_LIMIT_PER_MINUTE)
_active_requests = 0
_prune_counter = 0


async def auth_rate_limit(request: Request):
    """FastAPI dependency: per-IP rate limit + global concurrency cap.

    Raises 429 when the per-IP request rate is exceeded, or 503 when too many
    auth requests are in flight at once. Acquired before the handler runs and
    released (concurrency slot) when the request completes.
    """
    global _active_requests, _prune_counter

    now = time.monotonic()
    key = _client_key(request)

    _prune_counter += 1
    if _prune_counter >= 1000:
        _prune_counter = 0
        _rate_limiter.prune(now)

    if not _rate_limiter.check(key, now):
        logger.warning("Auth rate limit exceeded for client")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "too_many_requests",
                "error_description": "Rate limit exceeded. Try again later.",
            },
            headers={"Retry-After": "60"},
        )

    if _active_requests >= OAUTH_RATE_LIMIT_MAX_CONCURRENT:
        logger.warning("Auth concurrency cap reached")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "temporarily_unavailable",
                "error_description": "Server is busy. Try again shortly.",
            },
            headers={"Retry-After": "1"},
        )

    _active_requests += 1
    try:
        yield
    finally:
        _active_requests -= 1


def _reset_for_tests() -> None:
    """Reset shared limiter state (test isolation helper)."""
    global _active_requests, _prune_counter
    _rate_limiter._hits.clear()
    _active_requests = 0
    _prune_counter = 0
