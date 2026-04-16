"""翻译协议与服务。"""

from __future__ import annotations

import logging
from typing import Protocol

from models.article import Article

logger = logging.getLogger(__name__)


class TranslatorBackend(Protocol):
    """翻译后端协议。"""

    async def translate(self, text: str) -> str:
        """翻译文本。"""


class ArticleTranslator:
    """文章翻译服务。"""

    def __init__(self, backend: TranslatorBackend) -> None:
        self._backend = backend

    async def translate_article(self, article: Article) -> Article:
        """翻译文章标题与摘要。"""

        texts = [text for text in (article.title, article.summary) if text and text.strip()]
        if not texts:
            article.translation_status = "skipped"
            return article

        try:
            article.title_cn = await self._backend.translate(article.title)
            article.summary_cn = (
                await self._backend.translate(article.summary)
                if article.summary
                else None
            )
            article.translation_status = "completed"
        except Exception as exc:
            logger.warning("翻译失败，URL=%s，错误=%s", article.url, exc)
            article.title_cn = None
            article.summary_cn = None
            article.translation_status = "failed"
        return article

    async def translate_many(self, articles: list[Article]) -> list[Article]:
        """批量翻译文章。"""

        for article in articles:
            await self.translate_article(article)
        return articles
