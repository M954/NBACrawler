"""限速与退避测试。"""

from __future__ import annotations

import random

from utils.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


async def test_rate_limiter_waits_for_interval() -> None:
    sleeps: list[float] = []
    clock = FakeClock()

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.value += seconds

    limiter = RateLimiter(
        delay_min=2.0,
        delay_max=2.0,
        backoff_base=1.0,
        max_requests_per_minute=10,
        sleep_func=fake_sleep,
        clock=clock,
        randomizer=random.Random(0),
    )
    await limiter.wait("https://www.nba.com/news")
    await limiter.wait("https://www.nba.com/news?page=2")
    assert sleeps == [2.0]


def test_rate_limiter_backoff_grows() -> None:
    limiter = RateLimiter(
        delay_min=0.0,
        delay_max=0.0,
        backoff_base=1.0,
        max_requests_per_minute=10,
        randomizer=random.Random(0),
    )
    assert limiter.get_backoff_delay(1) > limiter.get_backoff_delay(0)
