"""NBA 列表页解析与抓取测试。"""

from __future__ import annotations

from config import get_settings, get_site_config
from scraper.nba_scraper import NbaScraper
from utils.exceptions import FetchError
from tests.conftest import AllowAllRobots, FakeTransport
from utils.headers import HeaderProvider
from utils.http import FetchResponse
from utils.rate_limiter import RateLimiter


def _build_scraper(transport, robots_checker) -> NbaScraper:
    settings = get_settings()
    return NbaScraper(
        site_config=get_site_config("nba"),
        transport=transport,
        robots_checker=robots_checker,
        header_provider=HeaderProvider(
            user_agents=settings.user_agents,
            base_headers=settings.default_headers,
        ),
        rate_limiter=RateLimiter(
            delay_min=0.0,
            delay_max=0.0,
            backoff_base=0.0,
            max_requests_per_minute=100,
        ),
        retry_settings=settings.retry,
    )


def test_nba_parser_from_fixture(normal_fixture_html: str) -> None:
    scraper = _build_scraper(transport=None, robots_checker=None)  # type: ignore[arg-type]
    articles = scraper.parse_articles(normal_fixture_html)
    assert len(articles) == 2
    assert articles[0].title == "LeBron James scores 40 in Lakers win"
    assert articles[0].url == "https://www.nba.com/news/lebron-james-scores-40"
    assert articles[0].tags == ["Lakers", "Game Recap"]


def test_nba_parser_handles_missing_fields(missing_fixture_html: str) -> None:
    scraper = _build_scraper(transport=None, robots_checker=None)  # type: ignore[arg-type]
    articles = scraper.parse_articles(missing_fixture_html)
    assert len(articles) == 2
    assert articles[0].summary is None
    assert articles[0].publish_date is None
    assert articles[1].author is None


async def test_fetch_page_retries_on_503(normal_fixture_html: str) -> None:
    transport = FakeTransport(
        {
            "https://www.nba.com/news": [
                FetchResponse("https://www.nba.com/news", 503, "busy"),
                FetchResponse("https://www.nba.com/news", 200, normal_fixture_html),
            ]
        }
    )
    scraper = _build_scraper(transport=transport, robots_checker=AllowAllRobots())
    articles = await scraper.scrape(limit=5)
    assert len(articles) == 2


async def test_fetch_page_retries_on_fetch_error(normal_fixture_html: str) -> None:
    class FlakyTransport:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, url: str, headers=None) -> FetchResponse:
            self.calls += 1
            if self.calls == 1:
                raise FetchError("temporary network issue")
            return FetchResponse(url, 200, normal_fixture_html)

    transport = FlakyTransport()
    scraper = _build_scraper(transport=transport, robots_checker=AllowAllRobots())
    articles = await scraper.scrape(limit=5)
    assert len(articles) == 2
