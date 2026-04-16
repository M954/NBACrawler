"""存储测试。"""

from __future__ import annotations

from storage.json_storage import JsonArticleRepository
from storage.sqlite_storage import SqliteArticleRepository


async def test_json_repository_save_and_exists(sample_article, tmp_path) -> None:
    repository = JsonArticleRepository(tmp_path / "articles.json")
    inserted = await repository.save_many([sample_article])
    assert inserted == 1
    assert await repository.exists(sample_article.url) is True
    loaded = await repository.load_all()
    assert loaded[0].title == sample_article.title


async def test_sqlite_repository_deduplicates(sample_article, tmp_path) -> None:
    repository = SqliteArticleRepository(tmp_path / "articles.db")
    inserted1 = await repository.save_many([sample_article])
    inserted2 = await repository.save_many([sample_article])
    assert inserted1 == 1
    assert inserted2 == 0
    assert await repository.exists(sample_article.url) is True
    assert await repository.count() == 1
