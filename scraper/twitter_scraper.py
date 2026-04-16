"""Twitter/X 推文爬虫 — API v2 + Nitter 降级。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from browser.screenshot import ScreenshotService, StubScreenshot
from config.players import PlayerConfig, load_players
from config.settings import get_settings
from models.tweet import Tweet

logger = logging.getLogger(__name__)

# Nitter 镜像列表（按可用性排序）
NITTER_INSTANCES: list[str] = [
    "https://nitter.net",
    "https://xcancel.com",
]

# 推文元素选择器（用于截图）
TWEET_SELECTOR_NITTER = ".timeline-item .tweet-body"
TWEET_SELECTOR_TWITTER = "article[data-testid='tweet']"

# API 限流：请求间隔（秒）
API_REQUEST_DELAY = 1.0
NITTER_REQUEST_DELAY = 2.0
# 并发控制
MAX_CONCURRENT_PLAYERS = 3


class TwitterScraper:
    """Twitter 推文抓取器，支持 API v2 和 Nitter 降级。"""

    def __init__(
        self,
        screenshot_service: ScreenshotService | None = None,
        bearer_token: str | None = None,
        nitter_instances: list[str] | None = None,
        enable_screenshots: bool = True,
    ) -> None:
        self._bearer_token = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
        self._nitter_instances = nitter_instances or list(NITTER_INSTANCES)
        self._screenshot = screenshot_service or StubScreenshot()
        self._enable_screenshots = enable_screenshots
        self._settings = get_settings()
        self._covers_dir = self._settings.output_dir / "covers"

    async def scrape_player(
        self,
        player: PlayerConfig,
        limit: int = 10,
    ) -> list[Tweet]:
        """抓取单个球星的推文。优先 API，降级 Nitter。"""

        tweets: list[Tweet] = []

        # 方案 A：Twitter API v2
        if self._bearer_token:
            try:
                tweets = await self._fetch_via_api(player, limit)
                logger.info("API 抓取 @%s 成功: %d 条", player.handle, len(tweets))
            except Exception as exc:
                logger.warning("API 抓取 @%s 失败: %s，降级到 Nitter", player.handle, exc)
                tweets = []

        # 方案 B：Nitter 降级
        if not tweets:
            tweets = await self._fetch_via_nitter(player, limit)

        # 截图（批量）
        if self._enable_screenshots and tweets:
            await self._batch_screenshot(tweets)

        return tweets

    async def scrape_all(
        self,
        players: list[PlayerConfig] | None = None,
        limit: int = 10,
    ) -> list[Tweet]:
        """抓取所有球星的推文（带并发控制）。"""
        if players is None:
            players = load_players()

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PLAYERS)
        all_tweets: list[Tweet] = []

        async def _scrape_one(player: PlayerConfig) -> list[Tweet]:
            async with semaphore:
                try:
                    tweets = await self.scrape_player(player, limit)
                    logger.info("@%s: 获取 %d 条推文", player.handle, len(tweets))
                    return tweets
                except Exception as exc:
                    logger.error("抓取 @%s 失败: %s", player.handle, exc)
                    return []

        results = await asyncio.gather(*[_scrape_one(p) for p in players])
        for tweets in results:
            all_tweets.extend(tweets)
        return all_tweets

    # ── Twitter API v2 ────────────────────────────────

    async def _fetch_via_api(self, player: PlayerConfig, limit: int) -> list[Tweet]:
        """通过 Twitter API v2 抓取推文（含限流）。"""
        # 先获取 user_id
        user_url = f"https://api.twitter.com/2/users/by/username/{player.handle}"
        headers = {"Authorization": f"Bearer {self._bearer_token}"}

        async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
            user_resp = await client.get(user_url)
            user_resp.raise_for_status()
            user_data = user_resp.json()

            user_id = user_data.get("data", {}).get("id")
            if not user_id:
                raise ValueError(f"未找到用户 @{player.handle}")

            # 限流：请求间隔
            await asyncio.sleep(API_REQUEST_DELAY)

            # 获取推文列表
            tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
            params = {
                "max_results": min(limit, 100),
                "tweet.fields": "created_at,public_metrics,referenced_tweets,attachments",
                "media.fields": "url,preview_image_url",
                "expansions": "attachments.media_keys",
            }
            tweets_resp = await client.get(tweets_url, params=params)
            tweets_resp.raise_for_status()
            tweets_data = tweets_resp.json()

        return self._parse_api_response(tweets_data, player)

    def _parse_api_response(self, data: dict, player: PlayerConfig) -> list[Tweet]:
        """解析 API v2 响应。"""
        tweets: list[Tweet] = []
        items = data.get("data", [])

        # 构建 media_key → url 映射
        media_map: dict[str, str] = {}
        for media in data.get("includes", {}).get("media", []):
            key = media.get("media_key", "")
            url = media.get("url") or media.get("preview_image_url") or ""
            if key and url:
                media_map[key] = url

        for item in items:
            tweet_id = item.get("id", "")
            text = item.get("text", "").strip()
            if not tweet_id or not text:
                continue

            # 判断推文类型
            tweet_type = "original"
            refs = item.get("referenced_tweets", [])
            if refs:
                ref_type = refs[0].get("type", "")
                if ref_type == "retweeted":
                    tweet_type = "retweet"
                elif ref_type == "quoted":
                    tweet_type = "quote"
                elif ref_type == "replied_to":
                    tweet_type = "reply"

            # 提取媒体 URL
            media_urls: list[str] = []
            attachments = item.get("attachments", {})
            for mk in attachments.get("media_keys", []):
                if mk in media_map:
                    media_urls.append(media_map[mk])

            metrics = item.get("public_metrics", {})
            created_at = item.get("created_at", "")

            # 容错日期解析
            tweet_date = datetime.now(timezone.utc)
            if created_at:
                try:
                    tweet_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    logger.warning("推文日期解析失败: %s", created_at)

            tweets.append(Tweet(
                tweet_id=tweet_id,
                player_name=player.name,
                player_handle=player.handle,
                content=text,
                url=f"https://x.com/{player.handle}/status/{tweet_id}",
                tweet_date=tweet_date,
                media_urls=media_urls,
                retweet_count=metrics.get("retweet_count", 0),
                like_count=metrics.get("like_count", 0),
                reply_count=metrics.get("reply_count", 0),
                tweet_type=tweet_type,
            ))

        return tweets

    # ── Nitter 降级 ───────────────────────────────────

    async def _fetch_via_nitter(self, player: PlayerConfig, limit: int) -> list[Tweet]:
        """通过 Nitter 镜像抓取推文（含限流）。"""
        for instance in self._nitter_instances:
            try:
                await asyncio.sleep(NITTER_REQUEST_DELAY)
                tweets = await self._try_nitter_instance(instance, player, limit)
                if tweets:
                    logger.info("Nitter [%s] 抓取 @%s 成功: %d 条", instance, player.handle, len(tweets))
                    return tweets
            except Exception as exc:
                logger.warning("Nitter [%s] @%s 失败: %s", instance, player.handle, exc)
                continue

        logger.error("所有 Nitter 镜像均不可用，抓取 @%s 失败", player.handle)
        return []

    async def _try_nitter_instance(
        self,
        instance: str,
        player: PlayerConfig,
        limit: int,
    ) -> list[Tweet]:
        """尝试单个 Nitter 实例。"""
        url = f"{instance}/{player.handle}"

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        return self._parse_nitter_html(html, player, instance, limit)

    def _parse_nitter_html(
        self,
        html: str,
        player: PlayerConfig,
        instance: str,
        limit: int,
    ) -> list[Tweet]:
        """解析 Nitter HTML 提取推文。"""
        soup = BeautifulSoup(html, "lxml")
        tweets: list[Tweet] = []

        items = soup.select(".timeline-item")
        if not items:
            # 备选选择器
            items = soup.select(".tweet-item, .thread-line")

        for item in items[:limit]:
            try:
                tweet = self._parse_nitter_item(item, player, instance)
                if tweet:
                    tweets.append(tweet)
            except Exception as exc:
                logger.debug("Nitter 条目解析失败: %s", exc)
                continue

        return tweets

    def _parse_nitter_item(self, item, player: PlayerConfig, instance: str) -> Tweet | None:
        """解析单个 Nitter 推文条目。"""
        # 提取推文链接和 ID
        link_el = item.select_one(".tweet-link, a.tweet-date")
        if not link_el:
            return None

        href = link_el.get("href", "")
        tweet_id_match = re.search(r"/status/(\d+)", href)
        if not tweet_id_match:
            return None
        tweet_id = tweet_id_match.group(1)

        # 推文内容
        content_el = item.select_one(".tweet-content, .tweet-body .content")
        content = content_el.get_text(strip=True) if content_el else ""
        if not content:
            return None

        # 时间
        time_el = item.select_one(".tweet-date a, time")
        tweet_date = datetime.now(timezone.utc)
        if time_el:
            title = time_el.get("title", "")
            if title:
                try:
                    tweet_date = datetime.strptime(title, "%b %d, %Y · %I:%M %p %Z")
                    tweet_date = tweet_date.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

        # 媒体
        media_urls: list[str] = []
        for img in item.select(".attachment.image img, .still-image img"):
            src = img.get("src", "")
            if src:
                media_urls.append(urljoin(instance, src))

        # 互动数据
        stats = {}
        for stat_el in item.select(".tweet-stat .icon-container"):
            stat_text = stat_el.get_text(strip=True).replace(",", "")
            parent = stat_el.parent
            if parent:
                classes = parent.get("class", [])
                if any("retweet" in c for c in classes):
                    stats["retweet"] = int(stat_text) if stat_text.isdigit() else 0
                elif any("heart" in c or "like" in c for c in classes):
                    stats["like"] = int(stat_text) if stat_text.isdigit() else 0
                elif any("comment" in c or "reply" in c for c in classes):
                    stats["reply"] = int(stat_text) if stat_text.isdigit() else 0

        # 推文类型
        tweet_type = "original"
        if item.select_one(".retweet-header"):
            tweet_type = "retweet"
        elif item.select_one(".quote"):
            tweet_type = "quote"
        elif item.select_one(".replying-to"):
            tweet_type = "reply"

        return Tweet(
            tweet_id=tweet_id,
            player_name=player.name,
            player_handle=player.handle,
            content=content,
            url=f"https://x.com/{player.handle}/status/{tweet_id}",
            tweet_date=tweet_date,
            media_urls=media_urls,
            retweet_count=stats.get("retweet", 0),
            like_count=stats.get("like", 0),
            reply_count=stats.get("reply", 0),
            tweet_type=tweet_type,
        )

    # ── 截图 ──────────────────────────────────────────

    async def _batch_screenshot(self, tweets: list[Tweet]) -> None:
        """批量截取推文封面图。"""
        self._covers_dir.mkdir(parents=True, exist_ok=True)

        for tweet in tweets:
            output_path = self._covers_dir / f"{tweet.tweet_id}.jpg"
            # 优先用 Nitter URL 截图（无需登录）
            nitter_url = ""
            for inst in self._nitter_instances:
                nitter_url = f"{inst}/{tweet.player_handle}/status/{tweet.tweet_id}"
                break

            screenshot_url = nitter_url or tweet.url
            selector = TWEET_SELECTOR_NITTER if nitter_url else TWEET_SELECTOR_TWITTER

            result = await self._screenshot.capture(
                url=screenshot_url,
                selector=selector,
                output_path=output_path,
                timeout=15000,
            )
            if result:
                # 存储相对路径
                tweet.cover_image_path = f"covers/{tweet.tweet_id}.jpg"

    async def close(self) -> None:
        """清理资源。"""
        if hasattr(self._screenshot, "close"):
            await self._screenshot.close()
