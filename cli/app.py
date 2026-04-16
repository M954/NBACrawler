"""CLI 与应用编排。"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import get_settings, get_site_config
from config.players import PlayerConfig, load_players, get_player_by_handle
from scraper.nba_scraper import NbaScraper
from scraper.twitter_scraper import TwitterScraper
from storage.json_storage import JsonArticleRepository, JsonTweetRepository
from storage.sqlite_storage import SqliteArticleRepository, SqliteTweetRepository
from translator.base import ArticleTranslator, TranslatorBackend
from translator.google_translator import DeepTranslatorBackend
from utils.exceptions import ConfigurationError, ProjectError
from utils.headers import HeaderProvider
from utils.http import HttpTransport, HttpxTransport
from utils.rate_limiter import RateLimiter
from utils.robots import BasicRobotsChecker, RobotsChecker

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    """抓取结果摘要。"""

    site: str
    scraped_count: int
    stored_count: int
    storage_location: str
    translation_statuses: dict[str, int]


@dataclass
class TwitterScrapeResult:
    """推文抓取结果摘要。"""

    player_count: int
    tweet_count: int
    stored_count: int
    storage_location: str
    translation_statuses: dict[str, int]
    screenshot_count: int


def positive_int(value: str) -> int:
    """解析正整数 CLI 参数。"""

    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("limit 必须是正整数")
    return parsed


class BasketballNewsApplication:
    """MVP 应用服务。"""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        robots_checker: RobotsChecker | None = None,
        translator_backend: TranslatorBackend | None = None,
        settings_factory=get_settings,
    ) -> None:
        self._settings_factory = settings_factory
        self._settings = self._settings_factory()
        self._transport = transport or HttpxTransport(
            timeout=self._settings.request_timeout
        )
        self._robots_checker = robots_checker or BasicRobotsChecker(self._transport)
        self._translator_backend = translator_backend or DeepTranslatorBackend(
            source_language=self._settings.translation.source_language,
            target_language=self._settings.translation.target_language,
        )

    def _build_scraper(self, site_key: str) -> NbaScraper:
        site_config = get_site_config(site_key)
        header_provider = HeaderProvider(
            user_agents=self._settings.user_agents,
            base_headers=self._settings.default_headers,
        )
        rate_limiter = RateLimiter(
            delay_min=self._settings.request_delay_min,
            delay_max=self._settings.request_delay_max,
            backoff_base=self._settings.retry.backoff_base_seconds,
            max_requests_per_minute=self._settings.max_requests_per_minute,
        )
        return NbaScraper(
            site_config=site_config,
            transport=self._transport,
            robots_checker=self._robots_checker,
            header_provider=header_provider,
            rate_limiter=rate_limiter,
            retry_settings=self._settings.retry,
        )

    async def scrape(self, site: str, limit: int, storage: str) -> ScrapeResult:
        """执行抓取闭环。"""

        scraper = self._build_scraper(site)
        articles = await scraper.scrape(limit=limit)

        # 过滤掉 publish_date 超过 7 天的旧文章
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        articles = [
            a for a in articles
            if a.publish_date is None or a.publish_date >= cutoff
        ]

        translator = ArticleTranslator(self._translator_backend)
        await translator.translate_many(articles)
        repository = self._create_repository(storage)
        stored_count = await repository.save_many(articles)
        statuses = Counter(article.translation_status for article in articles)
        return ScrapeResult(
            site=site,
            scraped_count=len(articles),
            stored_count=stored_count,
            storage_location=repository.location,
            translation_statuses=dict(statuses),
        )

    async def translate_test(self, text: str) -> str:
        """执行翻译测试。"""

        return await self._translator_backend.translate(text)

    async def scrape_twitter(
        self,
        player_handle: str | None = None,
        limit: int = 10,
        storage: str = "json",
        enable_screenshots: bool = True,
    ) -> TwitterScrapeResult:
        """抓取球星推文。"""
        from browser.screenshot import PlaywrightScreenshot, StubScreenshot

        screenshot_service = PlaywrightScreenshot() if enable_screenshots else StubScreenshot()
        scraper = TwitterScraper(
            screenshot_service=screenshot_service,
            enable_screenshots=enable_screenshots,
        )

        try:
            if player_handle:
                player = get_player_by_handle(player_handle)
                if not player:
                    raise ConfigurationError(f"未找到球星: @{player_handle}")
                players = [player]
            else:
                players = load_players()

            tweets = await scraper.scrape_all(players=players, limit=limit)

            # 翻译推文内容
            translator = self._translator_backend
            from config.glossary import expand_twitter_slang, TWITTER_POST_FIXES, POST_TRANSLATION_FIXES
            for tweet in tweets:
                try:
                    # 预处理：单词边界匹配展开缩写
                    text = expand_twitter_slang(tweet.content)
                    # 翻译
                    tweet.content_cn = await translator.translate(text)
                    # 后处理：修正术语
                    for wrong, right in TWITTER_POST_FIXES.items():
                        tweet.content_cn = tweet.content_cn.replace(wrong, right)
                    for wrong, right in POST_TRANSLATION_FIXES.items():
                        tweet.content_cn = tweet.content_cn.replace(wrong, right)
                    tweet.translation_status = "completed"
                except Exception as exc:
                    logger.warning("推文翻译失败 %s: %s", tweet.tweet_id, exc)
                    tweet.translation_status = "failed"

            # 存储
            repository = self._create_tweet_repository(storage)
            stored_count = await repository.save_many(tweets)
            statuses = Counter(t.translation_status for t in tweets)
            screenshot_count = sum(1 for t in tweets if t.cover_image_path)

            return TwitterScrapeResult(
                player_count=len(players),
                tweet_count=len(tweets),
                stored_count=stored_count,
                storage_location=repository.location,
                translation_statuses=dict(statuses),
                screenshot_count=screenshot_count,
            )
        finally:
            await scraper.close()

    def _create_repository(self, storage: str):
        output_dir = self._settings.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        if storage == "json":
            return JsonArticleRepository(self._settings.json_output_path)
        if storage == "sqlite":
            return SqliteArticleRepository(self._settings.sqlite_output_path)
        raise ConfigurationError(f"不支持的存储类型: {storage}")

    def _create_tweet_repository(self, storage: str):
        output_dir = self._settings.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        if storage == "json":
            return JsonTweetRepository(output_dir / "tweets.json")
        if storage == "sqlite":
            return SqliteTweetRepository(output_dir / "tweets.db")
        raise ConfigurationError(f"不支持的存储类型: {storage}")


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 解析器。"""

    parser = argparse.ArgumentParser(description="篮球资讯爬虫 MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="抓取并保存新闻")
    scrape_parser.add_argument("--site", choices=["nba"], required=True)
    scrape_parser.add_argument("--limit", type=positive_int, default=10)
    scrape_parser.add_argument("--storage", choices=["json", "sqlite"], required=True)

    twitter_parser = subparsers.add_parser("twitter", help="抓取球星推文")
    twitter_parser.add_argument("--player", default=None, help="球星 Twitter handle（如 KingJames）")
    twitter_parser.add_argument("--limit", type=positive_int, default=10, help="每人最多推文数")
    twitter_parser.add_argument("--storage", choices=["json", "sqlite"], default="json")
    twitter_parser.add_argument("--no-screenshot", action="store_true", help="禁用截图")

    translate_parser = subparsers.add_parser("translate-test", help="测试翻译")
    translate_parser.add_argument("text")
    return parser


async def run_cli(
    argv: list[str] | None = None,
    app: BasketballNewsApplication | None = None,
) -> int:
    """运行 CLI。"""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    application = app or BasketballNewsApplication()

    try:
        if args.command == "translate-test":
            result = await application.translate_test(args.text)
            print(f"原文: {args.text}")
            print(f"译文: {result}")
            return 0

        if args.command == "scrape":
            result = await application.scrape(
                site=args.site,
                limit=args.limit,
                storage=args.storage,
            )
            print(f"站点: {result.site}")
            print(f"抓取数: {result.scraped_count}")
            print(f"入库数: {result.stored_count}")
            print(f"翻译状态: {result.translation_statuses}")
            print(f"存储位置: {result.storage_location}")
            return 0

        if args.command == "twitter":
            result = await application.scrape_twitter(
                player_handle=args.player,
                limit=args.limit,
                storage=args.storage,
                enable_screenshots=not args.no_screenshot,
            )
            print(f"球星数: {result.player_count}")
            print(f"推文数: {result.tweet_count}")
            print(f"入库数: {result.stored_count}")
            print(f"截图数: {result.screenshot_count}")
            print(f"翻译状态: {result.translation_statuses}")
            print(f"存储位置: {result.storage_location}")
            return 0
    except ProjectError as exc:
        logger.error("运行失败: %s", exc)
        print(f"错误: {exc}")
        return 1

    return 1
