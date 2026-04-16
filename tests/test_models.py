"""Article 模型测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.article import Article
from utils.exceptions import ValidationError


def test_article_serialization(sample_article: Article) -> None:
    payload = sample_article.to_dict()
    assert payload["title"] == sample_article.title
    assert payload["publish_date"] == "2026-04-10T12:00:00+00:00"
    restored = Article.from_dict(payload)
    assert restored.title_cn == sample_article.title_cn
    assert restored.tags == ["Lakers", "Game Recap"]


def test_article_requires_core_fields() -> None:
    with pytest.raises(ValidationError):
        Article(title="", url="https://example.com", source="NBA News")


def test_article_accepts_optional_none() -> None:
    article = Article(
        title="Title",
        url="https://www.nba.com/news/title",
        source="NBA News",
        publish_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )
    assert article.summary is None
    assert article.translation_status == "pending"
