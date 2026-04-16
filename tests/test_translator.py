"""翻译服务测试。"""

from __future__ import annotations

from models.article import Article
from tests.conftest import FakeTranslatorBackend
from translator.base import ArticleTranslator


async def test_translate_article_success() -> None:
    backend = FakeTranslatorBackend(
        {
            "LeBron James scores 40": "勒布朗·詹姆斯砍下40分",
            "A great game.": "一场精彩比赛。",
        }
    )
    service = ArticleTranslator(backend)
    article = Article(
        title="LeBron James scores 40",
        summary="A great game.",
        url="https://www.nba.com/news/x",
        source="NBA News",
    )
    await service.translate_article(article)
    assert article.title_cn == "勒布朗·詹姆斯砍下40分"
    assert article.summary_cn == "一场精彩比赛。"
    assert article.translation_status == "completed"


async def test_translate_article_failure_degrades_gracefully() -> None:
    backend = FakeTranslatorBackend(
        {"LeBron James scores 40": "勒布朗·詹姆斯砍下40分"},
        fail_on={"LeBron James scores 40"},
    )
    service = ArticleTranslator(backend)
    article = Article(
        title="LeBron James scores 40",
        summary="A great game.",
        url="https://www.nba.com/news/y",
        source="NBA News",
    )
    await service.translate_article(article)
    assert article.title_cn is None
    assert article.summary_cn is None
    assert article.translation_status == "failed"
