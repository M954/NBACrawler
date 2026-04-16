"""MVP 不启用复杂代理池，此处保留最小占位。"""

from __future__ import annotations

from collections.abc import Sequence


class ProxyManager:
    """代理接口占位实现。"""

    def __init__(self, proxies: Sequence[str] | None = None) -> None:
        self._proxies = list(proxies) if proxies else []

    def get_proxy(self) -> str | None:
        """MVP 固定直连。"""
        return None
