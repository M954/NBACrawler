"""存储协议。"""

from __future__ import annotations

from typing import Protocol

from models.article import Article


class ArticleRepository(Protocol):
    """文章仓储协议。"""

    location: str

    async def save_many(self, articles: list[Article]) -> int:
        """批量保存。"""

    async def exists(self, url: str) -> bool:
        """按 URL 判断是否存在。"""
