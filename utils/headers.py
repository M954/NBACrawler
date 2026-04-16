"""请求头生成工具。"""

from __future__ import annotations

import random
from collections.abc import Sequence

from config.settings import DEFAULT_HEADERS, DEFAULT_USER_AGENTS


class HeaderProvider:
    """提供带 UA 轮换的请求头。"""

    def __init__(
        self,
        user_agents: Sequence[str] | None = None,
        base_headers: dict[str, str] | None = None,
        chooser: random.Random | None = None,
    ) -> None:
        self._user_agents = tuple(user_agents or DEFAULT_USER_AGENTS)
        self._base_headers = dict(base_headers or DEFAULT_HEADERS)
        self._chooser = chooser or random.Random()

    def build(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        """构造请求头。"""

        headers = dict(self._base_headers)
        headers["User-Agent"] = self._chooser.choice(self._user_agents)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    # 兼容别名
    def get_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """get_headers 兼容方法，委托给 build()"""
        return self.build(extra_headers=extra)


class HeaderManager(HeaderProvider):
    """兼容别名，同时支持 ua_pool 参数"""

    def __init__(
        self,
        ua_pool: Sequence[str] | None = None,
        user_agents: Sequence[str] | None = None,
        base_headers: dict[str, str] | None = None,
        chooser: random.Random | None = None,
    ) -> None:
        super().__init__(
            user_agents=ua_pool or user_agents,
            base_headers=base_headers,
            chooser=chooser,
        )
