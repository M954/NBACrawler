"""爬虫基类与抓取协议。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from config.settings import RetrySettings
from config.sites import SiteConfig
from models.article import Article
from utils.exceptions import FetchError, ParseError, RobotsDeniedError
from utils.headers import HeaderProvider
from utils.http import FetchResponse, HttpTransport
from utils.rate_limiter import RateLimiter
from utils.robots import RobotsChecker

logger = logging.getLogger(__name__)


class ScraperProtocol(Protocol):
    """可抓取列表页的协议。"""

    async def scrape(self, limit: int | None = None) -> list[Article]:
        """抓取文章列表。"""


class BaseScraper(ABC):
    """HTTP 列表页爬虫基类。"""

    def __init__(
        self,
        site_config: SiteConfig,
        transport: HttpTransport,
        robots_checker: RobotsChecker,
        header_provider: HeaderProvider,
        rate_limiter: RateLimiter,
        retry_settings: RetrySettings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.site_config = site_config
        self._transport = transport
        self._robots_checker = robots_checker
        self._header_provider = header_provider
        self._rate_limiter = rate_limiter
        self._retry_settings = retry_settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def fetch_page(self, url: str) -> str:
        """抓取页面 HTML。"""

        headers = self._header_provider.build(self.site_config.headers)
        user_agent = headers.get("User-Agent", "*")

        if not await self._robots_checker.can_fetch(url, user_agent):
            raise RobotsDeniedError(f"robots.txt 禁止抓取: {url}")

        last_response: FetchResponse | None = None
        last_error: Exception | None = None
        for attempt in range(self._retry_settings.max_attempts):
            await self._rate_limiter.wait(url)
            try:
                response = await self._transport.fetch(url, headers=headers)
            except FetchError as exc:
                last_error = exc
                if attempt < self._retry_settings.max_attempts - 1:
                    await self._rate_limiter.wait_backoff(attempt)
                    continue
                raise
            last_response = response
            if response.status_code in self._retry_settings.retry_status_codes:
                if attempt < self._retry_settings.max_attempts - 1:
                    await self._rate_limiter.wait_backoff(attempt)
                    continue
            if response.status_code >= 400:
                raise FetchError(f"抓取失败: {url} -> {response.status_code}")
            return response.text

        if last_error is not None:
            raise FetchError(f"抓取失败: {url}") from last_error
        status_code = last_response.status_code if last_response else "unknown"
        raise FetchError(f"抓取失败: {url} -> {status_code}")

    @abstractmethod
    def parse_articles(self, html: str) -> list[Article]:
        """解析文章列表。"""

    async def scrape(self, limit: int | None = None) -> list[Article]:
        """抓取并解析列表页。"""

        html = await self.fetch_page(self.site_config.news_url)
        try:
            articles = self.parse_articles(html)
        except Exception as exc:
            raise ParseError(f"解析 {self.site_config.name} 失败") from exc
        scraped_at = self._clock()
        for article in articles:
            article.scraped_at = scraped_at
        if limit is not None:
            return articles[:limit]
        return articles
