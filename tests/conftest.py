"""测试公共夹具。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from models.article import Article
from utils.http import FetchResponse


class FakeTransport:
    """可控假传输层。"""

    def __init__(self, responses: dict[str, list[FetchResponse] | FetchResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def fetch(self, url: str, headers: dict[str, str] | None = None) -> FetchResponse:
        self.calls.append((url, headers))
        response = self.responses[url]
        if isinstance(response, list):
            return response.pop(0)
        return response


class AllowAllRobots:
    """始终允许抓取。"""

    async def can_fetch(self, url: str, user_agent: str) -> bool:
        return True


class FakeTranslatorBackend:
    """可控翻译后端。"""

    def __init__(self, mapping: dict[str, str], fail_on: set[str] | None = None) -> None:
        self.mapping = mapping
        self.fail_on = fail_on or set()

    async def translate(self, text: str) -> str:
        if text in self.fail_on:
            raise RuntimeError("translation failed")
        return self.mapping[text]


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def normal_fixture_html(fixture_dir: Path) -> str:
    return (fixture_dir / "nba_news_list.html").read_text(encoding="utf-8")


@pytest.fixture
def missing_fixture_html(fixture_dir: Path) -> str:
    return (fixture_dir / "nba_news_missing_fields.html").read_text(encoding="utf-8")


@pytest.fixture
def sample_article() -> Article:
    return Article(
        title="LeBron James scores 40 points",
        title_cn="勒布朗·詹姆斯砍下40分",
        summary="The Lakers star dominated late in the game.",
        summary_cn="这位湖人球星在比赛末段统治比赛。",
        author="NBA Staff",
        publish_date=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        url="https://www.nba.com/news/lebron-james-scores-40",
        source="NBA News",
        tags=["Lakers", "Game Recap"],
        translation_status="completed",
    )
