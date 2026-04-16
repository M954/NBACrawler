"""HTTP 抽象与实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import httpx

from utils.exceptions import FetchError


@dataclass(frozen=True)
class FetchResponse:
    """HTTP 响应结果。"""

    url: str
    status_code: int
    text: str


class HttpTransport(Protocol):
    """可注入的底层 HTTP 传输协议。"""

    async def fetch(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResponse:
        """发送请求。"""


class HttpxTransport:
    """基于 httpx 的异步 HTTP 传输。"""

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def fetch(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResponse:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self._timeout,
            ) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise FetchError(f"请求失败: {url}") from exc
        return FetchResponse(
            url=str(response.url),
            status_code=response.status_code,
            text=response.text,
        )
