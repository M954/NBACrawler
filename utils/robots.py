"""robots 检查。"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from utils.http import HttpTransport


class RobotsChecker(Protocol):
    """robots 检查协议。"""

    async def can_fetch(self, url: str, user_agent: str) -> bool:
        """判断是否允许抓取。"""


class BasicRobotsChecker:
    """基础 robots 检查器。"""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport
        self._cache: dict[str, RobotFileParser | None] = {}

    @staticmethod
    def _robots_url(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    async def can_fetch(self, url: str, user_agent: str) -> bool:
        domain = urlparse(url).netloc
        if domain not in self._cache:
            robots_url = self._robots_url(url)
            try:
                response = await self._transport.fetch(robots_url)
                if response.status_code != 200:
                    self._cache[domain] = None
                else:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
                    self._cache[domain] = parser
            except Exception:
                self._cache[domain] = None

        parser = self._cache[domain]
        if parser is None:
            return True
        return parser.can_fetch(user_agent, url)
