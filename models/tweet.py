"""推文数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from utils.exceptions import ValidationError

TranslationStatus = Literal["pending", "completed", "failed", "skipped"]

TweetType = Literal["original", "retweet", "quote", "reply"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, AttributeError):
        return None


@dataclass(slots=True)
class Tweet:
    """结构化推文对象。"""

    tweet_id: str
    player_name: str
    player_handle: str
    content: str
    url: str
    tweet_date: datetime
    content_cn: str | None = None
    media_urls: list[str] = field(default_factory=list)
    cover_image_path: str | None = None
    retweet_count: int = 0
    like_count: int = 0
    reply_count: int = 0
    tweet_type: TweetType = "original"
    scraped_at: datetime = field(default_factory=_utc_now)
    translation_status: TranslationStatus = "pending"

    def __post_init__(self) -> None:
        """执行基础校验。"""
        self.tweet_id = self.tweet_id.strip()
        self.player_name = self.player_name.strip()
        self.player_handle = self.player_handle.strip()
        self.content = self.content.strip()
        self.url = self.url.strip()
        self.content_cn = self.content_cn.strip() if self.content_cn else None

        if not self.tweet_id:
            raise ValidationError("tweet_id 不能为空")
        if not self.player_handle:
            raise ValidationError("player_handle 不能为空")
        if not self.content:
            raise ValidationError("content 不能为空")

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "tweet_id": self.tweet_id,
            "player_name": self.player_name,
            "player_handle": self.player_handle,
            "content": self.content,
            "content_cn": self.content_cn,
            "url": self.url,
            "media_urls": list(self.media_urls),
            "cover_image_path": self.cover_image_path,
            "retweet_count": self.retweet_count,
            "like_count": self.like_count,
            "reply_count": self.reply_count,
            "tweet_type": self.tweet_type,
            "tweet_date": self.tweet_date.isoformat() if self.tweet_date else None,
            "scraped_at": self.scraped_at.isoformat(),
            "translation_status": self.translation_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tweet:
        """从字典反序列化。"""
        return cls(
            tweet_id=str(data["tweet_id"]),
            player_name=str(data.get("player_name", "")),
            player_handle=str(data["player_handle"]),
            content=str(data["content"]),
            content_cn=data.get("content_cn"),
            url=str(data.get("url", "")),
            media_urls=list(data.get("media_urls", [])),
            cover_image_path=data.get("cover_image_path"),
            retweet_count=int(data.get("retweet_count", 0)),
            like_count=int(data.get("like_count", 0)),
            reply_count=int(data.get("reply_count", 0)),
            tweet_type=data.get("tweet_type", "original"),
            tweet_date=_parse_datetime(data.get("tweet_date")) or _utc_now(),
            scraped_at=_parse_datetime(data.get("scraped_at")) or _utc_now(),
            translation_status=data.get("translation_status", "pending"),
        )
