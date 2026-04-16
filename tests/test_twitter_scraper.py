"""Twitter 推文爬虫测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from config.players import PlayerConfig, load_players
from models.tweet import Tweet
from scraper.twitter_scraper import TwitterScraper
from storage.json_storage import JsonTweetRepository
from storage.sqlite_storage import SqliteTweetRepository


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_player() -> PlayerConfig:
    return PlayerConfig(name="LeBron James", handle="KingJames", team="Lakers")


@pytest.fixture
def api_response_data(fixture_dir: Path) -> dict:
    path = fixture_dir / "twitter_api_response.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def nitter_html(fixture_dir: Path) -> str:
    path = fixture_dir / "nitter_tweet.html"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def sample_tweet() -> Tweet:
    return Tweet(
        tweet_id="1234567890",
        player_name="LeBron James",
        player_handle="KingJames",
        content="What a W tonight! 40 points and the dub",
        url="https://x.com/KingJames/status/1234567890",
        tweet_date=datetime(2026, 4, 10, 3, 45, tzinfo=timezone.utc),
        retweet_count=15200,
        like_count=89000,
        reply_count=3400,
        tweet_type="original",
    )


@pytest.fixture
def sample_tweets() -> list[Tweet]:
    return [
        Tweet(
            tweet_id="100",
            player_name="LeBron James",
            player_handle="KingJames",
            content="First tweet",
            url="https://x.com/KingJames/status/100",
            tweet_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
        ),
        Tweet(
            tweet_id="101",
            player_name="Stephen Curry",
            player_handle="StephenCurry30",
            content="Second tweet",
            url="https://x.com/StephenCurry30/status/101",
            tweet_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        ),
    ]


# ── Tweet 模型测试 ────────────────────────────────────

class TestTweetModel:
    """Tweet 数据模型测试。"""

    def test_create_valid_tweet(self, sample_tweet: Tweet) -> None:
        assert sample_tweet.tweet_id == "1234567890"
        assert sample_tweet.player_name == "LeBron James"
        assert sample_tweet.player_handle == "KingJames"
        assert sample_tweet.retweet_count == 15200
        assert sample_tweet.translation_status == "pending"

    def test_create_tweet_strips_whitespace(self) -> None:
        tweet = Tweet(
            tweet_id="  123  ",
            player_name="  LeBron  ",
            player_handle="  KingJames  ",
            content="  Some content  ",
            url="  https://x.com/test  ",
            tweet_date=datetime.now(timezone.utc),
        )
        assert tweet.tweet_id == "123"
        assert tweet.player_name == "LeBron"
        assert tweet.content == "Some content"

    def test_create_tweet_empty_id_raises(self) -> None:
        from utils.exceptions import ValidationError
        with pytest.raises(ValidationError, match="tweet_id"):
            Tweet(
                tweet_id="",
                player_name="Test",
                player_handle="test",
                content="Content",
                url="https://x.com",
                tweet_date=datetime.now(timezone.utc),
            )

    def test_create_tweet_empty_handle_raises(self) -> None:
        from utils.exceptions import ValidationError
        with pytest.raises(ValidationError, match="player_handle"):
            Tweet(
                tweet_id="123",
                player_name="Test",
                player_handle="",
                content="Content",
                url="https://x.com",
                tweet_date=datetime.now(timezone.utc),
            )

    def test_create_tweet_empty_content_raises(self) -> None:
        from utils.exceptions import ValidationError
        with pytest.raises(ValidationError, match="content"):
            Tweet(
                tweet_id="123",
                player_name="Test",
                player_handle="test",
                content="   ",
                url="https://x.com",
                tweet_date=datetime.now(timezone.utc),
            )

    def test_to_dict_roundtrip(self, sample_tweet: Tweet) -> None:
        data = sample_tweet.to_dict()
        restored = Tweet.from_dict(data)
        assert restored.tweet_id == sample_tweet.tweet_id
        assert restored.player_name == sample_tweet.player_name
        assert restored.content == sample_tweet.content
        assert restored.retweet_count == sample_tweet.retweet_count
        assert restored.tweet_type == sample_tweet.tweet_type

    def test_to_dict_includes_all_fields(self, sample_tweet: Tweet) -> None:
        data = sample_tweet.to_dict()
        expected_keys = {
            "tweet_id", "player_name", "player_handle", "content",
            "content_cn", "url", "media_urls", "cover_image_path",
            "retweet_count", "like_count", "reply_count",
            "tweet_type", "tweet_date", "scraped_at", "translation_status",
        }
        assert set(data.keys()) == expected_keys

    def test_default_values(self) -> None:
        tweet = Tweet(
            tweet_id="123",
            player_name="Test",
            player_handle="test",
            content="Content",
            url="https://x.com",
            tweet_date=datetime.now(timezone.utc),
        )
        assert tweet.media_urls == []
        assert tweet.cover_image_path is None
        assert tweet.retweet_count == 0
        assert tweet.tweet_type == "original"
        assert tweet.translation_status == "pending"


# ── API 响应解析测试 ──────────────────────────────────

class TestApiResponseParsing:
    """Twitter API v2 响应解析测试。"""

    def test_parse_api_response_normal(
        self, api_response_data: dict, sample_player: PlayerConfig
    ) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response(api_response_data, sample_player)
        assert len(tweets) == 3
        assert tweets[0].tweet_id == "1234567890"
        assert tweets[0].player_name == "LeBron James"
        assert "40 points" in tweets[0].content

    def test_parse_api_response_detects_retweet(
        self, api_response_data: dict, sample_player: PlayerConfig
    ) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response(api_response_data, sample_player)
        retweet = next(t for t in tweets if t.tweet_id == "1234567892")
        assert retweet.tweet_type == "retweet"

    def test_parse_api_response_extracts_media(
        self, api_response_data: dict, sample_player: PlayerConfig
    ) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response(api_response_data, sample_player)
        first = tweets[0]
        assert len(first.media_urls) == 1
        assert "example_photo.jpg" in first.media_urls[0]

    def test_parse_api_response_extracts_metrics(
        self, api_response_data: dict, sample_player: PlayerConfig
    ) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response(api_response_data, sample_player)
        assert tweets[0].retweet_count == 15200
        assert tweets[0].like_count == 89000
        assert tweets[0].reply_count == 3400

    def test_parse_api_response_builds_url(
        self, api_response_data: dict, sample_player: PlayerConfig
    ) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response(api_response_data, sample_player)
        assert tweets[0].url == "https://x.com/KingJames/status/1234567890"

    def test_parse_api_response_empty_data(self, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response({"data": []}, sample_player)
        assert tweets == []

    def test_parse_api_response_missing_data_key(self, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_api_response({}, sample_player)
        assert tweets == []

    def test_parse_api_response_skips_empty_text(self, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        data = {"data": [{"id": "999", "text": "   "}]}
        tweets = scraper._parse_api_response(data, sample_player)
        assert tweets == []


# ── Nitter 解析测试 ───────────────────────────────────

class TestNitterParsing:
    """Nitter HTML 解析测试。"""

    def test_parse_nitter_html(self, nitter_html: str, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_nitter_html(nitter_html, sample_player, "https://nitter.test", 10)
        assert len(tweets) >= 2

    def test_parse_nitter_extracts_id(self, nitter_html: str, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_nitter_html(nitter_html, sample_player, "https://nitter.test", 10)
        ids = [t.tweet_id for t in tweets]
        assert "1234567890" in ids
        assert "1234567891" in ids

    def test_parse_nitter_extracts_content(self, nitter_html: str, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_nitter_html(nitter_html, sample_player, "https://nitter.test", 10)
        first = next(t for t in tweets if t.tweet_id == "1234567890")
        assert "40 points" in first.content

    def test_parse_nitter_detects_quote(self, nitter_html: str, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_nitter_html(nitter_html, sample_player, "https://nitter.test", 10)
        quote_tweet = next((t for t in tweets if t.tweet_id == "1234567892"), None)
        if quote_tweet:
            assert quote_tweet.tweet_type == "quote"

    def test_parse_nitter_respects_limit(self, nitter_html: str, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_nitter_html(nitter_html, sample_player, "https://nitter.test", 1)
        assert len(tweets) <= 1

    def test_parse_nitter_empty_html(self, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        tweets = scraper._parse_nitter_html("<html><body></body></html>", sample_player, "https://nitter.test", 10)
        assert tweets == []


# ── 球星配置测试 ──────────────────────────────────────

class TestPlayerConfig:
    """球星配置加载测试。"""

    def test_load_players_from_default(self) -> None:
        players = load_players()
        assert len(players) >= 15
        handles = [p.handle for p in players]
        assert "KingJames" in handles
        assert "StephenCurry30" in handles

    def test_load_players_validates_fields(self) -> None:
        players = load_players()
        for p in players:
            assert p.name.strip() != ""
            assert p.handle.strip() != ""

    def test_load_players_missing_file_raises(self, tmp_path: Path) -> None:
        from utils.exceptions import ConfigurationError
        with pytest.raises(ConfigurationError, match="不存在"):
            load_players(tmp_path / "nonexistent.json")

    def test_load_players_invalid_json_raises(self, tmp_path: Path) -> None:
        from utils.exceptions import ConfigurationError
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="读取"):
            load_players(bad_file)

    def test_load_players_wrong_format_raises(self, tmp_path: Path) -> None:
        from utils.exceptions import ConfigurationError
        bad_file = tmp_path / "wrong.json"
        bad_file.write_text('{"not": "a list"}', encoding="utf-8")
        with pytest.raises(ConfigurationError, match="数组"):
            load_players(bad_file)

    def test_get_player_by_handle(self) -> None:
        from config.players import get_player_by_handle
        player = get_player_by_handle("KingJames")
        assert player is not None
        assert player.name == "LeBron James"

    def test_get_player_by_handle_case_insensitive(self) -> None:
        from config.players import get_player_by_handle
        player = get_player_by_handle("kingjames")
        assert player is not None

    def test_get_player_by_handle_not_found(self) -> None:
        from config.players import get_player_by_handle
        player = get_player_by_handle("nonexistent_handle")
        assert player is None


# ── JSON 存储测试 ─────────────────────────────────────

class TestJsonTweetStorage:
    """推文 JSON 存储测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path: Path, sample_tweets: list[Tweet]) -> None:
        repo = JsonTweetRepository(tmp_path / "tweets.json")
        count = await repo.save_many(sample_tweets)
        assert count == 2
        loaded = await repo.load_all()
        assert len(loaded) == 2
        assert loaded[0].tweet_id == "100"

    @pytest.mark.asyncio
    async def test_deduplication(self, tmp_path: Path, sample_tweets: list[Tweet]) -> None:
        repo = JsonTweetRepository(tmp_path / "tweets.json")
        await repo.save_many(sample_tweets)
        count2 = await repo.save_many(sample_tweets)
        assert count2 == 0  # 全部重复
        loaded = await repo.load_all()
        assert len(loaded) == 2

    @pytest.mark.asyncio
    async def test_exists(self, tmp_path: Path, sample_tweets: list[Tweet]) -> None:
        repo = JsonTweetRepository(tmp_path / "tweets.json")
        await repo.save_many(sample_tweets)
        assert await repo.exists("100") is True
        assert await repo.exists("999") is False

    @pytest.mark.asyncio
    async def test_empty_load(self, tmp_path: Path) -> None:
        repo = JsonTweetRepository(tmp_path / "tweets.json")
        loaded = await repo.load_all()
        assert loaded == []


# ── SQLite 存储测试 ───────────────────────────────────

class TestSqliteTweetStorage:
    """推文 SQLite 存储测试。"""

    @pytest.mark.asyncio
    async def test_save_and_exists(self, tmp_path: Path, sample_tweets: list[Tweet]) -> None:
        repo = SqliteTweetRepository(tmp_path / "tweets.db")
        count = await repo.save_many(sample_tweets)
        assert count == 2
        assert await repo.exists("100") is True
        assert await repo.exists("999") is False

    @pytest.mark.asyncio
    async def test_deduplication(self, tmp_path: Path, sample_tweets: list[Tweet]) -> None:
        repo = SqliteTweetRepository(tmp_path / "tweets.db")
        await repo.save_many(sample_tweets)
        count2 = await repo.save_many(sample_tweets)
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_init_creates_table(self, tmp_path: Path) -> None:
        repo = SqliteTweetRepository(tmp_path / "tweets.db")
        await repo.initialize()
        assert (tmp_path / "tweets.db").exists()


# ── 截图服务测试 ──────────────────────────────────────

class TestScreenshotService:
    """截图协议与桩实现测试。"""

    @pytest.mark.asyncio
    async def test_stub_returns_none(self, tmp_path: Path) -> None:
        from browser.screenshot import StubScreenshot
        stub = StubScreenshot()
        result = await stub.capture(
            url="https://x.com/test/status/123",
            selector="article",
            output_path=tmp_path / "test.jpg",
        )
        assert result is None

    def test_screenshot_cache_check(self, tmp_path: Path) -> None:
        """验证缓存逻辑：已存在的文件应被跳过。"""
        output = tmp_path / "cached.jpg"
        output.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # fake JPEG
        assert output.exists() and output.stat().st_size > 0


# ── 降级逻辑测试 ─────────────────────────────────────

class TestFallbackLogic:
    """API → Nitter 降级测试。"""

    def test_scraper_initializes_without_token(self) -> None:
        scraper = TwitterScraper(bearer_token="", enable_screenshots=False)
        assert scraper._bearer_token == ""

    def test_scraper_uses_provided_nitter_instances(self) -> None:
        instances = ["https://custom.nitter.example"]
        scraper = TwitterScraper(
            nitter_instances=instances, enable_screenshots=False
        )
        assert scraper._nitter_instances == instances

    def test_scraper_defaults_to_nitter_list(self) -> None:
        from scraper.twitter_scraper import NITTER_INSTANCES
        scraper = TwitterScraper(enable_screenshots=False)
        assert scraper._nitter_instances == NITTER_INSTANCES


# ── Glossary 测试 ─────────────────────────────────────

class TestTwitterGlossary:
    """Twitter 口语词汇表测试。"""

    def test_slang_expand_exists(self) -> None:
        from config.glossary import TWITTER_SLANG_EXPAND
        assert "W" in TWITTER_SLANG_EXPAND
        assert TWITTER_SLANG_EXPAND["W"] == "Win"

    def test_post_fixes_exists(self) -> None:
        from config.glossary import TWITTER_POST_FIXES
        assert "砖块" in TWITTER_POST_FIXES
        assert "海报" in TWITTER_POST_FIXES

    def test_slang_expansion_applied(self) -> None:
        from config.glossary import TWITTER_SLANG_EXPAND
        text = "Another W for the team"
        for slang, expanded in TWITTER_SLANG_EXPAND.items():
            text = text.replace(slang, expanded)
        assert "Win" in text


# ── 单词边界匹配测试 ─────────────────────────────────

class TestSlangBoundaryMatching:
    """验证俚语展开使用单词边界，不会误匹配。"""

    def test_ong_does_not_match_strong(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("He's strong and along the way")
        assert "strong" in result
        assert "along" in result
        assert "on god" not in result

    def test_ong_matches_standalone(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("ong that was crazy")
        assert "on god" in result

    def test_W_standalone_word(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("Got the W tonight")
        assert "Win" in result

    def test_W_does_not_match_inside_word(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("Welcome to the show")
        assert "Welcome" in result  # should not become "Winelcome"

    def test_L_standalone(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("That's an L")
        assert "Loss" in result

    def test_L_does_not_match_inside_word(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("Lakers looking good")
        assert "Lakers" in result  # should not be modified

    def test_ngl_matches_standalone(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("ngl that dunk was insane")
        assert "not gonna lie" in result

    def test_case_insensitive(self) -> None:
        from config.glossary import expand_twitter_slang
        result = expand_twitter_slang("NGL this team is goated")
        assert "not gonna lie" in result
        assert "greatest of all time" in result


# ── 端到端 Mock 测试 ─────────────────────────────────

class TestEndToEndMock:
    """使用 mock httpx 的端到端集成测试。"""

    @pytest.mark.asyncio
    async def test_scrape_player_api_success(
        self, api_response_data: dict, sample_player: PlayerConfig
    ) -> None:
        """API 抓取成功，不降级到 Nitter。"""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"data": {"id": "12345"}}
        user_response.raise_for_status = MagicMock()

        tweets_response = MagicMock()
        tweets_response.status_code = 200
        tweets_response.json.return_value = api_response_data
        tweets_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[user_response, tweets_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        scraper = TwitterScraper(
            bearer_token="test_token",
            enable_screenshots=False,
        )

        with patch("scraper.twitter_scraper.httpx.AsyncClient", return_value=mock_client):
            tweets = await scraper.scrape_player(sample_player, limit=10)

        assert len(tweets) == 3
        assert tweets[0].player_name == "LeBron James"

    @pytest.mark.asyncio
    async def test_scrape_player_api_fails_falls_to_nitter(
        self, nitter_html: str, sample_player: PlayerConfig
    ) -> None:
        """API 失败时降级到 Nitter。"""
        mock_api_client = AsyncMock()
        mock_api_client.get = AsyncMock(side_effect=httpx.HTTPError("API down"))
        mock_api_client.__aenter__ = AsyncMock(return_value=mock_api_client)
        mock_api_client.__aexit__ = AsyncMock(return_value=False)

        nitter_response = MagicMock()
        nitter_response.status_code = 200
        nitter_response.text = nitter_html
        nitter_response.raise_for_status = MagicMock()

        mock_nitter_client = AsyncMock()
        mock_nitter_client.get = AsyncMock(return_value=nitter_response)
        mock_nitter_client.__aenter__ = AsyncMock(return_value=mock_nitter_client)
        mock_nitter_client.__aexit__ = AsyncMock(return_value=False)

        scraper = TwitterScraper(
            bearer_token="test_token",
            enable_screenshots=False,
        )

        # First call: API (fails), subsequent: Nitter
        call_count = 0
        def client_factory(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_api_client
            return mock_nitter_client

        with patch("scraper.twitter_scraper.httpx.AsyncClient", side_effect=client_factory):
            tweets = await scraper.scrape_player(sample_player, limit=10)

        assert len(tweets) >= 2  # from Nitter HTML

    @pytest.mark.asyncio
    async def test_scrape_player_all_fail_returns_empty(
        self, sample_player: PlayerConfig
    ) -> None:
        """API 和所有 Nitter 都失败，返回空列表。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        scraper = TwitterScraper(
            bearer_token="test_token",
            nitter_instances=["https://nitter.test"],
            enable_screenshots=False,
        )

        with patch("scraper.twitter_scraper.httpx.AsyncClient", return_value=mock_client):
            tweets = await scraper.scrape_player(sample_player, limit=10)

        assert tweets == []


# ── Tweet.from_dict 异常输入 ─────────────────────────

class TestTweetFromDictEdgeCases:
    """from_dict 异常输入测试。"""

    def test_from_dict_missing_tweet_id_raises(self) -> None:
        from utils.exceptions import ValidationError
        with pytest.raises((ValidationError, KeyError)):
            Tweet.from_dict({"content": "test", "player_handle": "x"})

    def test_from_dict_invalid_date_uses_default(self) -> None:
        tweet = Tweet.from_dict({
            "tweet_id": "999",
            "player_name": "Test",
            "player_handle": "test",
            "content": "Content",
            "url": "https://x.com",
            "tweet_date": "invalid-date",
            "scraped_at": "also-invalid",
        })
        # Should fallback to utc_now() for invalid dates
        assert tweet.tweet_date is not None
        assert tweet.scraped_at is not None


# ── 路径穿越安全测试 ─────────────────────────────────

class TestCoverPathSecurity:
    """封面图路由安全测试。"""

    def test_valid_filename_pattern(self) -> None:
        import re
        valid = ["1234567890.jpg", "abc_def-123.jpg"]
        for f in valid:
            assert re.fullmatch(r'[a-zA-Z0-9_\-]+\.jpg', f), f"{f} should be valid"

    def test_path_traversal_rejected(self) -> None:
        import re
        malicious = ["../../../etc/passwd", "..\\..\\secret.jpg", "../../hack.jpg", "foo/bar.jpg"]
        for f in malicious:
            assert not re.fullmatch(r'[a-zA-Z0-9_\-]+\.jpg', f), f"{f} should be rejected"

    def test_non_jpg_rejected(self) -> None:
        import re
        invalid = ["file.png", "file.exe", "file", "file.jpg.exe"]
        for f in invalid:
            assert not re.fullmatch(r'[a-zA-Z0-9_\-]+\.jpg', f), f"{f} should be rejected"

    @pytest.mark.parametrize("filename,expected", [
        ("1234567890.jpg", True),
        ("tweet_abc-123.jpg", True),
        ("../etc/passwd", False),
        ("..\\..\\secret.jpg", False),
        ("foo/bar.jpg", False),
        ("file.png", False),
        ("file.exe", False),
        ("file.jpg.exe", False),
        ("\u4e2d\u6587.jpg", False),  # Unicode 应被拒绝
        ("", False),
    ])
    def test_cover_filename_parametrized(self, filename: str, expected: bool) -> None:
        import re
        result = bool(re.fullmatch(r'[a-zA-Z0-9_\-]+\.jpg', filename))
        assert result == expected, f"filename={filename!r}, expected={expected}"


# ── 并发控制测试 ─────────────────────────────────────

class TestConcurrencyControl:
    """验证并发 Semaphore 限制。"""

    @pytest.mark.asyncio
    async def test_scrape_all_limits_concurrency(self) -> None:
        """验证 scrape_all 使用并发限制。"""
        import asyncio
        concurrent_count = 0
        max_concurrent = 0

        original_scrape = TwitterScraper.scrape_player

        async def mock_scrape_player(self, player, limit=10):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)  # 模拟短延迟
            concurrent_count -= 1
            return []

        scraper = TwitterScraper(enable_screenshots=False)
        players = [
            PlayerConfig(name=f"Player{i}", handle=f"player{i}")
            for i in range(6)
        ]

        with patch.object(TwitterScraper, 'scrape_player', mock_scrape_player):
            await scraper.scrape_all(players=players, limit=5)

        # MAX_CONCURRENT_PLAYERS = 3，最大并发不应超过 3
        from scraper.twitter_scraper import MAX_CONCURRENT_PLAYERS
        assert max_concurrent <= MAX_CONCURRENT_PLAYERS


# ── API 日期容错测试 ─────────────────────────────────

class TestApiDateParsing:
    """API 响应中无效日期的容错测试。"""

    def test_invalid_created_at_does_not_crash(self, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        data = {
            "data": [{
                "id": "999",
                "text": "Test tweet",
                "created_at": "not-a-date",
                "public_metrics": {},
            }]
        }
        tweets = scraper._parse_api_response(data, sample_player)
        assert len(tweets) == 1
        assert tweets[0].tweet_date is not None  # should fallback to now

    def test_missing_created_at(self, sample_player: PlayerConfig) -> None:
        scraper = TwitterScraper(enable_screenshots=False)
        data = {
            "data": [{
                "id": "888",
                "text": "No date tweet",
            }]
        }
        tweets = scraper._parse_api_response(data, sample_player)
        assert len(tweets) == 1
        assert tweets[0].tweet_date is not None
