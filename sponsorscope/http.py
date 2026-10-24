from __future__ import annotations

import asyncio
import email.utils
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

USER_AGENT = "sponsorscope/0.1 (+https://github.com/BurakBakkar/sponsorscope)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 300.0

Sleep = Callable[[float], Awaitable[None]]


def rate_key(host: str) -> str:
    """Hosts sharing a registrable domain share one limiter ({slug}.recruitee.com → recruitee.com)."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


class _HostLimiter:
    """Caps concurrent requests and spaces request starts for one host."""

    def __init__(self, concurrency: int, rate: float, sleep: Sleep):
        self.semaphore = asyncio.Semaphore(concurrency)
        self._interval = 1.0 / rate
        self._next_slot = 0.0
        self._lock = asyncio.Lock()
        self._sleep = sleep

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        delay = slot - now
        if delay > 0:
            await self._sleep(delay)


class Http:
    """Polite async HTTP client shared by every register and ATS adapter."""

    def __init__(
        self,
        *,
        concurrency: int = 4,
        rate: float = 5.0,
        retries: int = 4,
        backoff: float = 0.5,
        timeout: float = 30.0,
        sleep: Sleep = asyncio.sleep,
    ):
        self._client = httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._concurrency = concurrency
        self._rate = rate
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._limiters: dict[str, _HostLimiter] = {}

    def _limiter(self, host: str) -> _HostLimiter:
        key = rate_key(host)
        if key not in self._limiters:
            self._limiters[key] = _HostLimiter(self._concurrency, self._rate, self._sleep)
        return self._limiters[key]

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self._request("POST", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        limiter = self._limiter(urlsplit(url).hostname or "")
        attempt = 0
        while True:
            response: httpx.Response | None = None
            async with limiter.semaphore:
                await limiter.wait_turn()
                try:
                    response = await self._client.request(method, url, **kwargs)
                except httpx.TransportError:
                    if attempt >= self._retries:
                        raise
            if response is not None and (
                response.status_code not in RETRY_STATUSES or attempt >= self._retries
            ):
                return response
            await self._sleep(self._delay(attempt, response))
            attempt += 1

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("Retry-After", "").strip() if response is not None else ""
        if retry_after.isdigit():
            return min(float(retry_after), MAX_RETRY_AFTER)
        if retry_after:
            try:
                when = email.utils.parsedate_to_datetime(retry_after)
                seconds = (when - datetime.now(timezone.utc)).total_seconds()
                return min(max(0.0, seconds), MAX_RETRY_AFTER)
            except (TypeError, ValueError):
                pass
        return self._backoff * (2**attempt) + random.uniform(0, self._backoff)

    async def aclose(self) -> None:
        await self._client.aclose()
