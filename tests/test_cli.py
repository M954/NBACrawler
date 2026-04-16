"""CLI 测试。"""

from __future__ import annotations

import pytest

from cli.app import BasketballNewsApplication, ScrapeResult, build_parser, run_cli


class FakeApp(BasketballNewsApplication):
    def __init__(self) -> None:
        pass

    async def scrape(self, site: str, limit: int, storage: str) -> ScrapeResult:
        return ScrapeResult(
            site=site,
            scraped_count=2,
            stored_count=2,
            storage_location=f"/virtual/{storage}",
            translation_statuses={"completed": 2},
        )

    async def translate_test(self, text: str) -> str:
        return f"ZH:{text}"


async def test_cli_translate_test(capsys) -> None:
    code = await run_cli(["translate-test", "Hello"], app=FakeApp())
    captured = capsys.readouterr()
    assert code == 0
    assert "ZH:Hello" in captured.out


async def test_cli_scrape(capsys) -> None:
    code = await run_cli(
        ["scrape", "--site", "nba", "--limit", "2", "--storage", "json"],
        app=FakeApp(),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "抓取数: 2" in captured.out


def test_cli_invalid_args() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["scrape", "--site", "nba"])


def test_cli_rejects_non_positive_limit() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["scrape", "--site", "nba", "--limit", "0", "--storage", "json"]
        )
