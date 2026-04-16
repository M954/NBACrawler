"""浏览器抓取接口预留。"""

from __future__ import annotations

from typing import Protocol

from utils.exceptions import BrowserError


class BrowserFetcher(Protocol):
    """浏览器抓取协议。"""

    async def fetch(self, url: str) -> str:
        """抓取页面。"""


class StubBrowserFetcher:
    """MVP 浏览器占位实现。"""

    async def fetch(self, url: str) -> str:
        raise BrowserError(f"MVP 未启用浏览器抓取: {url}")
