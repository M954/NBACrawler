"""文章模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from utils.exceptions import ValidationError

TranslationStatus = Literal["pending", "completed", "failed", "skipped"]


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


@dataclass(slots=True)
class Article:
    """结构化文章对象。"""

    title: str
    url: str
    source: str
    title_cn: str | None = None
    summary: str | None = None
    summary_cn: str | None = None
    author: str | None = None
    publish_date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=utc_now)
    translation_status: TranslationStatus = "pending"

    def __post_init__(self) -> None:
        """执行基础校验。"""

        self.title = self.title.strip()
        self.url = self.url.strip()
        self.source = self.source.strip()
        self.summary = self.summary.strip() if self.summary else None
        self.author = self.author.strip() if self.author else None
        self.title_cn = self.title_cn.strip() if self.title_cn else None
        self.summary_cn = self.summary_cn.strip() if self.summary_cn else None
        self.tags = [tag.strip() for tag in self.tags if tag and tag.strip()]

        if not self.title:
            raise ValidationError("title 不能为空")
        if not self.url:
            raise ValidationError("url 不能为空")
        if not self.source:
            raise ValidationError("source 不能为空")

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""

        return {
            "title": self.title,
            "title_cn": self.title_cn,
            "summary": self.summary,
            "summary_cn": self.summary_cn,
            "author": self.author,
            "publish_date": self.publish_date.isoformat()
            if self.publish_date
            else None,
            "url": self.url,
            "source": self.source,
            "tags": list(self.tags),
            "scraped_at": self.scraped_at.isoformat(),
            "translation_status": self.translation_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        """从字典反序列化。"""

        return cls(
            title=str(data["title"]),
            title_cn=data.get("title_cn"),
            summary=data.get("summary"),
            summary_cn=data.get("summary_cn"),
            author=data.get("author"),
            publish_date=_parse_datetime(data.get("publish_date")),
            url=str(data["url"]),
            source=str(data["source"]),
            tags=list(data.get("tags", [])),
            scraped_at=_parse_datetime(data.get("scraped_at")) or utc_now(),
            translation_status=data.get("translation_status", "pending"),
        )
