"""端到端集成测试。"""

from __future__ import annotations

from cli.app import BasketballNewsApplication, run_cli
from config.settings import CrawlerSettings
from tests.conftest import AllowAllRobots, FakeTransport, FakeTranslatorBackend
from utils.http import FetchResponse


async def test_end_to_end_json(tmp_path, normal_fixture_html: str) -> None:
    transport = FakeTransport(
        {
            "https://www.nba.com/news": FetchResponse(
                "https://www.nba.com/news",
                200,
                normal_fixture_html,
            )
        }
    )
    translator = FakeTranslatorBackend(
        {
            "LeBron James scores 40 in Lakers win": "勒布朗40分率队取胜",
            "The Lakers held off a late run to secure the victory.": "湖人顶住末段反扑取胜。",
            "Nikola Jokic posts another triple-double": "约基奇再度拿下三双",
            "Denver continued its strong stretch with a balanced attack.": "掘金延续强势表现，多点开花。",
        }
    )
    app = BasketballNewsApplication(
        transport=transport,
        robots_checker=AllowAllRobots(),
        translator_backend=translator,
        settings_factory=lambda: CrawlerSettings(
            request_delay_min=0.0,
            request_delay_max=0.0,
            output_dir=tmp_path,
        ),
    )
    code = await run_cli(
        ["scrape", "--site", "nba", "--limit", "10", "--storage", "json"],
        app=app,
    )
    assert code == 0
    assert (tmp_path / "articles.json").exists()
