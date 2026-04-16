"""SQLite 仓储。"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from models.article import Article
from models.tweet import Tweet
from utils.exceptions import StorageError


class SqliteArticleRepository:
    """SQLite 文章仓储。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def location(self) -> str:
        return str(self._path)

    async def initialize(self) -> None:
        """初始化数据表。"""

        try:
            async with aiosqlite.connect(self._path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS articles (
                        url TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        title_cn TEXT,
                        summary TEXT,
                        summary_cn TEXT,
                        author TEXT,
                        publish_date TEXT,
                        source TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        scraped_at TEXT NOT NULL,
                        translation_status TEXT NOT NULL
                    )
                    """
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"初始化 SQLite 失败: {self._path}") from exc

    async def save_many(self, articles: list[Article]) -> int:
        """批量保存。"""

        await self.initialize()
        inserted = 0
        try:
            async with aiosqlite.connect(self._path) as db:
                for article in articles:
                    before = db.total_changes
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO articles (
                            url, title, title_cn, summary, summary_cn, author,
                            publish_date, source, tags, scraped_at,
                            translation_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            article.url,
                            article.title,
                            article.title_cn,
                            article.summary,
                            article.summary_cn,
                            article.author,
                            article.publish_date.isoformat()
                            if article.publish_date
                            else None,
                            article.source,
                            json.dumps(article.tags, ensure_ascii=False),
                            article.scraped_at.isoformat(),
                            article.translation_status,
                        ),
                    )
                    inserted += db.total_changes - before
                await db.commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"写入 SQLite 失败: {self._path}") from exc
        return inserted

    async def exists(self, url: str) -> bool:
        await self.initialize()
        try:
            async with aiosqlite.connect(self._path) as db:
                async with db.execute(
                    "SELECT 1 FROM articles WHERE url = ? LIMIT 1",
                    (url,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return row is not None
        except aiosqlite.Error as exc:
            raise StorageError(f"查询 SQLite 失败: {self._path}") from exc

    async def count(self) -> int:
        """统计条数。"""

        await self.initialize()
        async with aiosqlite.connect(self._path) as db:
            async with db.execute("SELECT COUNT(*) FROM articles") as cursor:
                row = await cursor.fetchone()
                return int(row[0])


class SqliteTweetRepository:
    """SQLite 推文仓储。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def location(self) -> str:
        return str(self._path)

    async def initialize(self) -> None:
        """初始化推文数据表。"""
        try:
            async with aiosqlite.connect(self._path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tweets (
                        tweet_id TEXT PRIMARY KEY,
                        player_name TEXT NOT NULL,
                        player_handle TEXT NOT NULL,
                        content TEXT NOT NULL,
                        content_cn TEXT,
                        url TEXT NOT NULL,
                        media_urls TEXT NOT NULL,
                        cover_image_path TEXT,
                        retweet_count INTEGER DEFAULT 0,
                        like_count INTEGER DEFAULT 0,
                        reply_count INTEGER DEFAULT 0,
                        tweet_type TEXT DEFAULT 'original',
                        tweet_date TEXT NOT NULL,
                        scraped_at TEXT NOT NULL,
                        translation_status TEXT NOT NULL
                    )
                    """
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"初始化推文表失败: {self._path}") from exc

    async def save_many(self, tweets: list[Tweet]) -> int:
        """批量保存推文（基于 tweet_id 去重）。"""
        await self.initialize()
        inserted = 0
        try:
            async with aiosqlite.connect(self._path) as db:
                for tweet in tweets:
                    before = db.total_changes
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO tweets (
                            tweet_id, player_name, player_handle, content,
                            content_cn, url, media_urls, cover_image_path,
                            retweet_count, like_count, reply_count,
                            tweet_type, tweet_date, scraped_at, translation_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            tweet.tweet_id,
                            tweet.player_name,
                            tweet.player_handle,
                            tweet.content,
                            tweet.content_cn,
                            tweet.url,
                            json.dumps(tweet.media_urls, ensure_ascii=False),
                            tweet.cover_image_path,
                            tweet.retweet_count,
                            tweet.like_count,
                            tweet.reply_count,
                            tweet.tweet_type,
                            tweet.tweet_date.isoformat() if tweet.tweet_date else None,
                            tweet.scraped_at.isoformat(),
                            tweet.translation_status,
                        ),
                    )
                    inserted += db.total_changes - before
                await db.commit()
        except aiosqlite.Error as exc:
            raise StorageError(f"写入推文 SQLite 失败: {self._path}") from exc
        return inserted

    async def exists(self, tweet_id: str) -> bool:
        await self.initialize()
        try:
            async with aiosqlite.connect(self._path) as db:
                async with db.execute(
                    "SELECT 1 FROM tweets WHERE tweet_id = ? LIMIT 1",
                    (tweet_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return row is not None
        except aiosqlite.Error as exc:
            raise StorageError(f"查询推文 SQLite 失败: {self._path}") from exc
