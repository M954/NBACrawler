"""限速与退避。"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse


class RateLimiter:
    """按域名限速，并支持指数退避。"""

    def __init__(
        self,
        delay_min: float = 1.0,
        delay_max: float = 3.0,
        backoff_base: float = 1.0,
        max_requests_per_minute: int = 10,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        randomizer: random.Random | None = None,
    ) -> None:
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._backoff_base = backoff_base
        self._max_requests_per_minute = max_requests_per_minute
        self._sleep = sleep_func
        self._clock = clock
        self._randomizer = randomizer or random.Random()
        self._last_request_at: dict[str, float] = {}
        self._history: dict[str, list[float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def get_domain(url: str) -> str:
        """提取域名。"""

        return urlparse(url).netloc

    def _lock_for(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    def _purge_history(self, domain: str, now: float) -> None:
        cutoff = now - 60.0
        self._history[domain] = [
            item for item in self._history.get(domain, []) if item >= cutoff
        ]

    async def wait(self, url: str) -> None:
        """请求前等待。"""

        domain = self.get_domain(url)
        async with self._lock_for(domain):
            now = self._clock()
            self._purge_history(domain, now)

            history = self._history.setdefault(domain, [])
            if len(history) >= self._max_requests_per_minute:
                wait_seconds = max(0.0, 60.0 - (now - history[0]))
                if wait_seconds > 0:
                    await self._sleep(wait_seconds)
                    now = self._clock()
                    self._purge_history(domain, now)

            last_request_at = self._last_request_at.get(domain)
            target_delay = self._randomizer.uniform(self._delay_min, self._delay_max)
            if last_request_at is not None:
                elapsed = now - last_request_at
                if elapsed < target_delay:
                    await self._sleep(target_delay - elapsed)
                    now = self._clock()

            self._last_request_at[domain] = now
            self._history.setdefault(domain, []).append(now)

    def get_backoff_delay(self, attempt_index: int) -> float:
        """计算退避时长。"""

        jitter = self._randomizer.uniform(0.0, self._backoff_base)
        return self._backoff_base * (2**attempt_index) + jitter

    async def wait_backoff(self, attempt_index: int) -> None:
        """执行退避等待。"""

        await self._sleep(self.get_backoff_delay(attempt_index))
