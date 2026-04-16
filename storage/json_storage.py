"""JSON 仓储。"""

from __future__ import annotations

import json
from pathlib import Path

from models.article import Article
from models.tweet import Tweet
from utils.exceptions import StorageError


class JsonArticleRepository:
    """JSON 文章仓储。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def location(self) -> str:
        return str(self._path)

    def _load_raw(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"读取 JSON 失败: {self._path}") from exc

    async def save_many(self, articles: list[Article]) -> int:
        """保存文章列表。"""

        existing = self._load_raw()
        seen = {item["url"] for item in existing}
        new_items: list[dict] = []
        for article in articles:
            if article.url in seen:
                continue
            seen.add(article.url)
            new_items.append(article.to_dict())
        try:
            self._path.write_text(
                json.dumps(existing + new_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise StorageError(f"写入 JSON 失败: {self._path}") from exc
        return len(new_items)

    async def exists(self, url: str) -> bool:
        return any(item.get("url") == url for item in self._load_raw())

    async def load_all(self) -> list[Article]:
        """加载全部文章。"""

        return [Article.from_dict(item) for item in self._load_raw()]


class JsonTweetRepository:
    """JSON 推文仓储。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def location(self) -> str:
        return str(self._path)

    def _load_raw(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"读取推文 JSON 失败: {self._path}") from exc

    async def save_many(self, tweets: list[Tweet]) -> int:
        """批量保存推文（基于 tweet_id 去重）。"""
        existing = self._load_raw()
        seen = {item["tweet_id"] for item in existing}
        new_items: list[dict] = []
        for tweet in tweets:
            if tweet.tweet_id in seen:
                continue
            seen.add(tweet.tweet_id)
            new_items.append(tweet.to_dict())
        try:
            self._path.write_text(
                json.dumps(existing + new_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise StorageError(f"写入推文 JSON 失败: {self._path}") from exc
        return len(new_items)

    async def exists(self, tweet_id: str) -> bool:
        return any(item.get("tweet_id") == tweet_id for item in self._load_raw())

    async def load_all(self) -> list[Tweet]:
        """加载全部推文。"""
        return [Tweet.from_dict(item) for item in self._load_raw()]
