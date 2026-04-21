"""篮球资讯爬虫 — Flask Web 仪表板"""

from __future__ import annotations

import json
import threading
import asyncio
import os
import re
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ── 全局状态 ──────────────────────────────────────────
_articles: list[dict] = []
_tweets: list[dict] = []
_status: str = "idle"  # idle / running / stopped
_tweet_status: str = "idle"  # idle / running
_screenshot_status: str = "idle"  # idle / running
_tweet_source_mode: str = "idle"  # idle / api / nitter / cache / failed
_tweet_source_message: str = ""
_enabled_sites: list[str] = ["yahoo_nba", "espn_nba", "cbs_nba"]
_scraper_thread: threading.Thread | None = None
_tweet_scraper_thread: threading.Thread | None = None
_stop_event = threading.Event()
_tweet_stop_event = threading.Event()
_tweets_lock = threading.Lock()

# ── 运行日志 ─────────────────────────────────────────
_service_logs: list[dict] = []  # {time, level, msg}
_MAX_LOGS = 500

def _log(msg: str, level: str = "info"):
    """记录服务日志（线程安全）。"""
    from datetime import datetime
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    _service_logs.append(entry)
    if len(_service_logs) > _MAX_LOGS:
        _service_logs.pop(0)
    print(f"[{entry['time']}] [{level.upper()}] {msg}")

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "output" / "demo_results.json"
TWEETS_FILE = Path(__file__).resolve().parent.parent / "output" / "tweets.json"

# Nitter 多实例（自动降级）
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://xcancel.com",
]


def _set_tweet_source(mode: str, message: str = "") -> None:
    """更新推文来源状态，供接口与前端展示。"""
    global _tweet_source_mode, _tweet_source_message
    _tweet_source_mode = mode
    _tweet_source_message = message


def _get_cached_tweets(limit: int = 30) -> list[dict]:
    """返回当前内存中的最新缓存推文。"""
    with _tweets_lock:
        snapshot = list(_tweets)
    snapshot.sort(key=lambda t: t.get("tweet_date", ""), reverse=True)
    return snapshot[:limit]


def _is_nitter_fallback_enabled() -> bool:
    """仅在显式开启时才尝试不稳定的 Nitter 降级。"""
    return os.environ.get("TWITTER_ALLOW_NITTER_FALLBACK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _filter_latest_tweets(all_tweets: list[dict], limit: int = 30, days: int = 1) -> list[dict]:
    """按时间、去重和账号配额筛选最终展示推文。优先最近 days 天，不足则取每人最新一条。"""
    from datetime import datetime, timedelta, timezone

    media_handles = {"NBA", "ESPNNBA", "BleacherReport", "ShamsCharania"}
    max_per_player = 1
    max_media = 5
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    ranked = sorted(all_tweets, key=lambda t: t.get("tweet_date", ""), reverse=True)

    # 第一轮：只取 days 天内的
    seen_ids: set[str] = set()
    player_counts: dict[str, int] = {}
    media_count = 0
    filtered: list[dict] = []

    for tweet in ranked:
        tweet_id = str(tweet.get("tweet_id", "")).strip()
        handle = str(tweet.get("player_handle", "")).strip()
        if not tweet_id or not handle or tweet_id in seen_ids:
            continue

        tweet_date_str = tweet.get("tweet_date", "")
        if tweet_date_str:
            try:
                td = datetime.fromisoformat(str(tweet_date_str))
                if td < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        if handle in media_handles:
            if media_count >= max_media:
                continue
            media_count += 1
        else:
            current = player_counts.get(handle, 0)
            if current >= max_per_player:
                continue
            player_counts[handle] = current + 1
        seen_ids.add(tweet_id)
        filtered.append(tweet)
        if len(filtered) >= limit:
            break

    # 第二轮：如果 days 天内没有结果，取每人最新一条（不限日期）
    if not filtered:
        _log(f"最近 {days} 天无推文，回退到每人最新一条。", "warn")
        seen_ids.clear()
        player_counts.clear()
        media_count = 0
        for tweet in ranked:
            tweet_id = str(tweet.get("tweet_id", "")).strip()
            handle = str(tweet.get("player_handle", "")).strip()
            if not tweet_id or not handle or tweet_id in seen_ids:
                continue
            if handle in media_handles:
                if media_count >= max_media:
                    continue
                media_count += 1
            else:
                current = player_counts.get(handle, 0)
                if current >= max_per_player:
                    continue
                player_counts[handle] = current + 1
            seen_ids.add(tweet_id)
            filtered.append(tweet)
            if len(filtered) >= limit:
                break

    _log(
        f"去重筛选: {len(all_tweets)} -> {len(filtered)} 条（球星≤{max_per_player}条/人, 媒体≤{max_media}条）"
    )
    return filtered


async def _translate_tweets(tweets: list[dict]) -> int:
    """翻译推文内容并回填中文字段。"""
    if not tweets:
        return 0

    translated = 0
    _log(f"开始翻译 {len(tweets)} 条推文...")
    try:
        from translator.google_translator import DeepTranslatorBackend
        from config.glossary import expand_twitter_slang, POST_TRANSLATION_FIXES

        backend = DeepTranslatorBackend()
        for tweet in tweets:
            try:
                text = expand_twitter_slang(tweet["content"])
                content_cn = await backend.translate(text)
                for wrong, right in POST_TRANSLATION_FIXES.items():
                    content_cn = content_cn.replace(wrong, right)
                tweet["content_cn"] = content_cn
                tweet["translation_status"] = "completed"
                translated += 1
            except Exception:
                tweet["translation_status"] = "failed"
        _log(f"翻译完成: {translated}/{len(tweets)}", "success")
    except Exception as exc:
        _log(f"翻译初始化失败: {exc}", "error")

    return translated


async def _fetch_tweets_via_twitter_api(players) -> list[dict]:
    """优先使用官方 API v2 抓取实时推文。"""
    bearer_token = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    if not bearer_token:
        _log("未配置 TWITTER_BEARER_TOKEN，跳过官方 API 实时抓取。", "warn")
        return []

    from scraper.twitter_scraper import TwitterScraper

    scraper = TwitterScraper(
        bearer_token=bearer_token,
        nitter_instances=[],
        enable_screenshots=False,
    )
    try:
        _log(f"使用 Twitter API v2 抓取 {len(players)} 个账号...")
        tweets = await scraper.scrape_all(players=players, limit=5)
        payload = [tweet.to_dict() for tweet in tweets if tweet.content.strip()]
        if payload:
            _log(f"Twitter API 返回 {len(payload)} 条候选推文。", "success")
        else:
            _log("Twitter API 本次未返回可用推文。", "warn")
        return payload
    except Exception as exc:
        _log(f"Twitter API 抓取失败: {exc}", "warn")
        return []
    finally:
        await scraper.close()


async def _fetch_tweets_via_syndication(players) -> list[dict]:
    """通过 Twitter Syndication + fxtwitter 组合拉取最新推文（无需 token）。"""
    import urllib.request
    import urllib.error
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    FXTWITTER_API = "https://api.fxtwitter.com"
    SYNDICATION_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    MAX_IDS_PER_PLAYER = 1  # 每人取最新 1 条 ID
    SYNDICATION_DELAY = 3.0  # Syndication 请求间隔（避免 429）
    FX_DELAY = 0.5  # fxtwitter 请求间隔
    RETRY_DELAY = 15.0  # 429 后的等待时间

    all_tweets: list[dict] = []
    success_count = 0
    fail_count = 0
    rate_limited = False
    consecutive_429 = 0
    MAX_CONSECUTIVE_429 = 3  # 连续限频 3 次就放弃剩余

    _log(f"使用 Syndication+fxtwitter 抓取 {len(players)} 个账号...")

    for index, player in enumerate(players):
        handle = player.handle

        # 如果被限频了，等待后再尝试
        if rate_limited:
            consecutive_429 += 1
            if consecutive_429 >= MAX_CONSECUTIVE_429:
                _log(f"连续 {consecutive_429} 次 429 限频，放弃剩余 Syndication 请求。", "warn")
                break
            _log(f"等待 {int(RETRY_DELAY)}s 后重试 (429 冷却 {consecutive_429}/{MAX_CONSECUTIVE_429})...", "warn")
            await asyncio.sleep(RETRY_DELAY)
            rate_limited = False

        try:
            # Step 1: 从 Syndication 获取推文 ID
            req = urllib.request.Request(
                f"{SYNDICATION_URL}/{handle}",
                headers={"User-Agent": UA, "Accept": "text/html"},
            )
            try:
                resp = urllib.request.urlopen(req, timeout=15)
            except urllib.error.HTTPError as http_err:
                if http_err.code == 429:
                    rate_limited = True
                    _log(f"[{index+1}/{len(players)}] @{handle}: Syndication 429 限频", "warn")
                    fail_count += 1
                    continue
                raise

            # 成功请求后重置连续 429 计数
            consecutive_429 = 0
            html = resp.read().decode("utf-8", errors="replace")
            raw_ids = list(dict.fromkeys(re.findall(r'/status/(\d{15,25})', html)))
            # 按数值降序排序（最大 = 最新）
            raw_ids.sort(key=lambda x: int(x), reverse=True)
            candidate_ids = raw_ids[:MAX_IDS_PER_PLAYER]

            if not candidate_ids:
                _log(f"[{index+1}/{len(players)}] @{handle}: Syndication 未发现推文 ID", "warn")
                fail_count += 1
                await asyncio.sleep(SYNDICATION_DELAY)
                continue

            # Step 2: 用 fxtwitter 获取每条推文的完整数据
            player_count = 0
            for tid in candidate_ids:
                try:
                    fx_req = urllib.request.Request(
                        f"{FXTWITTER_API}/{handle}/status/{tid}",
                        headers={"User-Agent": UA, "Accept": "application/json"},
                    )
                    fx_resp = urllib.request.urlopen(fx_req, timeout=12)
                    fx_data = json.loads(fx_resp.read().decode("utf-8", errors="replace"))

                    tweet_obj = fx_data.get("tweet", {})
                    text = (tweet_obj.get("text") or "").strip()
                    if not text or len(text) < 5:
                        continue

                    # 解析日期
                    tweet_date = datetime.now(timezone.utc)
                    created_at = tweet_obj.get("created_at", "")
                    if created_at:
                        try:
                            tweet_date = parsedate_to_datetime(created_at)
                        except Exception:
                            try:
                                tweet_date = datetime.strptime(
                                    created_at, "%a %b %d %H:%M:%S %z %Y"
                                )
                            except Exception:
                                pass

                    # 提取媒体 URL
                    media_urls = []
                    for m in tweet_obj.get("media", {}).get("all", []):
                        u = m.get("url") or m.get("thumbnail_url", "")
                        if u:
                            media_urls.append(u)

                    all_tweets.append({
                        "tweet_id": str(tid),
                        "player_name": player.name,
                        "player_handle": handle,
                        "content": text[:500],
                        "content_cn": None,
                        "url": f"https://x.com/{handle}/status/{tid}",
                        "media_urls": media_urls,
                        "cover_image_path": None,
                        "retweet_count": int(tweet_obj.get("retweets", 0)),
                        "like_count": int(tweet_obj.get("likes", 0)),
                        "reply_count": int(tweet_obj.get("replies", 0)),
                        "tweet_type": "original",
                        "tweet_date": tweet_date.isoformat(),
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "translation_status": "pending",
                    })
                    player_count += 1
                except Exception:
                    continue  # 单条失败不影响整体
                await asyncio.sleep(FX_DELAY)

            if player_count > 0:
                success_count += 1
            _log(f"[{index+1}/{len(players)}] @{handle}: {player_count} 条推文")

        except Exception as exc:
            fail_count += 1
            _log(f"[{index+1}/{len(players)}] @{handle}: 失败 ({str(exc)[:50]})", "warn")

        await asyncio.sleep(SYNDICATION_DELAY)

    _log(
        f"Syndication+fxtwitter 抓取完成: 成功 {success_count}/{len(players)}, "
        f"失败 {fail_count}, 总推文 {len(all_tweets)}"
    )
    return all_tweets


async def _fetch_tweets_via_fxtwitter_refresh(players) -> list[dict]:
    """用 fxtwitter 刷新已知推文数据（不需要 Syndication 或 token）。

    从已有的 tweets.json 中提取每个球星的已知推文 ID，
    用 fxtwitter API 逐条刷新其最新内容和数据。
    """
    import urllib.request
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    FXTWITTER_API = "https://api.fxtwitter.com"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    FX_DELAY = 0.5
    MAX_PER_PLAYER = 3

    # 从缓存中获取每个球星的已知推文 ID
    with _tweets_lock:
        cached = list(_tweets)

    player_ids: dict[str, list[str]] = {}
    for t in cached:
        handle = t.get("player_handle", "")
        tid = str(t.get("tweet_id", ""))
        if handle and tid:
            player_ids.setdefault(handle, []).append(tid)

    # 如果没有缓存推文 ID 可用，额外从 players 列表提供一些 handles
    if not player_ids:
        _log("无缓存推文 ID 可供刷新，跳过 fxtwitter 模式。", "warn")
        return []

    # 对每个球星的 ID 按数值降序拿最新的
    for handle in player_ids:
        player_ids[handle] = sorted(
            list(set(player_ids[handle])),
            key=lambda x: int(x),
            reverse=True,
        )[:MAX_PER_PLAYER]

    # 从 players 列表构建 handle -> player 映射
    player_map = {p.handle: p for p in players}

    all_tweets: list[dict] = []
    success_count = 0
    fail_count = 0

    handles = list(player_ids.keys())
    _log(f"使用 fxtwitter 刷新 {len(handles)} 个球星的已知推文...")

    for index, handle in enumerate(handles):
        player = player_map.get(handle)
        player_name = player.name if player else handle
        player_count = 0

        for tid in player_ids[handle]:
            try:
                fx_req = urllib.request.Request(
                    f"{FXTWITTER_API}/{handle}/status/{tid}",
                    headers={"User-Agent": UA, "Accept": "application/json"},
                )
                fx_resp = urllib.request.urlopen(fx_req, timeout=12)
                fx_data = json.loads(fx_resp.read().decode("utf-8", errors="replace"))

                tweet_obj = fx_data.get("tweet", {})
                text = (tweet_obj.get("text") or "").strip()
                if not text or len(text) < 5:
                    continue

                tweet_date = datetime.now(timezone.utc)
                created_at = tweet_obj.get("created_at", "")
                if created_at:
                    try:
                        tweet_date = parsedate_to_datetime(created_at)
                    except Exception:
                        try:
                            tweet_date = datetime.strptime(
                                created_at, "%a %b %d %H:%M:%S %z %Y"
                            )
                        except Exception:
                            pass

                media_urls = []
                media_block = tweet_obj.get("media")
                if isinstance(media_block, dict):
                    for m in media_block.get("all", []):
                        u = m.get("url") or m.get("thumbnail_url", "")
                        if u:
                            media_urls.append(u)

                all_tweets.append({
                    "tweet_id": str(tid),
                    "player_name": player_name,
                    "player_handle": handle,
                    "content": text[:500],
                    "content_cn": None,
                    "url": f"https://x.com/{handle}/status/{tid}",
                    "media_urls": media_urls,
                    "cover_image_path": None,
                    "retweet_count": int(tweet_obj.get("retweets", 0)),
                    "like_count": int(tweet_obj.get("likes", 0)),
                    "reply_count": int(tweet_obj.get("replies", 0)),
                    "tweet_type": "original",
                    "tweet_date": tweet_date.isoformat(),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "translation_status": "pending",
                })
                player_count += 1
            except Exception:
                continue
            await asyncio.sleep(FX_DELAY)

        if player_count > 0:
            success_count += 1
        _log(f"[{index+1}/{len(handles)}] @{handle}: {player_count} 条刷新")

    _log(
        f"fxtwitter 刷新完成: 成功 {success_count}/{len(handles)}, "
        f"失败 {fail_count}, 总推文 {len(all_tweets)}"
    )
    return all_tweets


async def _fetch_tweets_via_nitter_rss(players) -> list[dict]:
    """兼容历史链路的 Nitter RSS 抓取，仅在显式开启时使用。"""
    if not _is_nitter_fallback_enabled():
        _log("已停用 Nitter 降级；如需强制尝试，请设置 TWITTER_ALLOW_NITTER_FALLBACK=1。", "warn")
        return []

    import urllib.request
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    from html import unescape

    all_tweets: list[dict] = []
    working_instance = None

    _log(f"正在检测 {len(NITTER_INSTANCES)} 个 Nitter 实例...")
    for inst in NITTER_INSTANCES:
        try:
            test_req = urllib.request.Request(
                f"{inst}/NBA/rss",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            test_resp = urllib.request.urlopen(test_req, timeout=8)
            test_body = test_resp.read().decode("utf-8", errors="replace").strip()
            # 验证返回的确有真实推文条目
            if (test_resp.status == 200
                    and len(test_body) > 500
                    and "<item>" in test_body
                    and "not yet whitelisted" not in test_body.lower()):
                working_instance = inst
                _log(f"找到可用 Nitter 实例: {inst}", "success")
                break
            else:
                _log(f"实例内容无效: {inst} (len={len(test_body)})", "warn")
        except Exception as exc:
            _log(f"实例不可用: {inst} ({str(exc)[:40]})", "warn")
        await asyncio.sleep(0.5)

    if not working_instance:
        _log("Nitter 降级链路不可用。", "warn")
        return []

    success_count = 0
    fail_count = 0
    _log(f"使用 {working_instance} 抓取 {len(players)} 个账号...")

    for index, player in enumerate(players):
        url = f"{working_instance}/{player.handle}/rss"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/rss+xml, text/xml",
                },
            )
            resp = urllib.request.urlopen(req, timeout=15)
            xml_text = resp.read().decode("utf-8", errors="replace").strip()

            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                continue

            count = 0
            for item in channel.findall("item"):
                link_el = item.find("link")
                desc_el = item.find("description")
                pub_el = item.find("pubDate")
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                match = re.search(r"/status/(\d+)", link)
                if not match:
                    continue

                content = ""
                if desc_el is not None and desc_el.text:
                    content = re.sub(r"<br\s*/?>", "\n", desc_el.text)
                    content = re.sub(r"<[^>]+>", "", content)
                    content = unescape(content).strip()[:500]
                if len(content.strip()) < 5:
                    continue

                tweet_date = datetime.now(timezone.utc)
                if pub_el is not None and pub_el.text:
                    try:
                        tweet_date = parsedate_to_datetime(pub_el.text)
                    except Exception:
                        pass

                all_tweets.append({
                    "tweet_id": match.group(1),
                    "player_name": player.name,
                    "player_handle": player.handle,
                    "content": content,
                    "content_cn": None,
                    "url": f"https://x.com/{player.handle}/status/{match.group(1)}",
                    "media_urls": [],
                    "cover_image_path": None,
                    "retweet_count": 0,
                    "like_count": 0,
                    "reply_count": 0,
                    "tweet_type": "original",
                    "tweet_date": tweet_date.isoformat(),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "translation_status": "pending",
                })
                count += 1

            if count > 0:
                success_count += 1
            _log(f"[{index + 1}/{len(players)}] @{player.handle}: {count} 条推文")
        except Exception as exc:
            fail_count += 1
            _log(f"[{index + 1}/{len(players)}] @{player.handle}: 失败 ({str(exc)[:40]})", "warn")
        await asyncio.sleep(1.5)

    _log(f"Nitter RSS 抓取完成: 成功 {success_count}/{len(players)}, 失败 {fail_count}, 总推文 {len(all_tweets)}")
    return all_tweets


def _get_available_sources() -> list[str]:
    """返回稳定的可选来源列表。"""
    from config.sites import SITE_CONFIGS

    configured_sources = [
        SITE_CONFIGS[key].source
        for key in _enabled_sites
        if key in SITE_CONFIGS and SITE_CONFIGS[key].feed_type == "rss"
    ]
    loaded_sources = [
        article.get("source")
        for article in _articles
        if isinstance(article, dict) and article.get("source")
    ]
    return list(dict.fromkeys(configured_sources + loaded_sources))


def _load_existing() -> None:
    """从 JSON 文件加载已有数据。"""
    global _articles, _tweets
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                _articles = json.load(f)
        except Exception:
            _articles = []
    if TWEETS_FILE.exists():
        try:
            with open(TWEETS_FILE, encoding="utf-8") as f:
                _tweets = json.load(f)
        except Exception:
            _tweets = []


def _save_articles() -> None:
    """保存文章到 JSON。"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(_articles, f, ensure_ascii=False, indent=2)


def _run_scraper() -> None:
    """在后台线程中运行 RSS 爬虫。"""
    global _status, _articles
    _status = "running"
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        articles = loop.run_until_complete(_async_scrape())
        if articles:
            _articles = articles
            _save_articles()
    except Exception as e:
        print(f"爬虫错误: {e}")
    finally:
        _status = "idle"
        _stop_event.clear()


async def _async_scrape() -> list[dict]:
    """异步抓取所有启用的 RSS 源。"""
    from scraper.rss_scraper import RssScraper
    from config.sites import SITE_CONFIGS
    from translator.google_translator import DeepTranslatorBackend

    scraper = RssScraper()
    all_articles = []

    for key in _enabled_sites:
        if _stop_event.is_set():
            break
        cfg = SITE_CONFIGS.get(key)
        if not cfg or cfg.feed_type != "rss":
            continue
        try:
            articles = await scraper.fetch_rss(cfg.news_url, cfg.source)
            all_articles.extend(articles[:20])
        except Exception as e:
            print(f"抓取 {cfg.name} 失败: {e}")

    # 翻译
    if all_articles and not _stop_event.is_set():
        try:
            backend = DeepTranslatorBackend()
            from config.glossary import POST_TRANSLATION_FIXES
            for i, a in enumerate(all_articles):
                if _stop_event.is_set():
                    break
                try:
                    title_cn = await backend.translate(a.get("title", ""))
                    summary_cn = await backend.translate(a.get("summary", ""))
                    # 应用术语后处理
                    for wrong, right in POST_TRANSLATION_FIXES.items():
                        title_cn = title_cn.replace(wrong, right)
                        summary_cn = summary_cn.replace(wrong, right)
                    a["title_cn"] = title_cn
                    a["summary_cn"] = summary_cn
                    a["translation_status"] = "completed"
                except Exception:
                    a["translation_status"] = "failed"
        except Exception as e:
            print(f"翻译初始化失败: {e}")

    return [a if isinstance(a, dict) else a.__dict__ for a in all_articles]


# ── 路由 ──────────────────────────────────────────────
@app.route("/")
def index():
    """主页。"""
    from config.sites import SITE_CONFIGS

    rss_sites = [
        {"key": k, "name": v.name, "source": v.source, "enabled": k in _enabled_sites}
        for k, v in SITE_CONFIGS.items()
        if v.feed_type == "rss"
    ]
    return render_template(
        "index.html",
        rss_sites=rss_sites,
        available_sources=_get_available_sources(),
    )


@app.route("/api/status")
def api_status():
    """爬虫状态。"""
    return jsonify({"status": _status, "article_count": len(_articles)})


@app.route("/api/articles")
def api_articles():
    """文章列表，支持 ?source= 筛选。"""
    source = request.args.get("source", "")
    if source:
        return jsonify([a for a in _articles if a.get("source") == source])
    return jsonify(_articles)


@app.route("/api/sources")
def api_sources():
    """返回稳定的来源选项。"""
    return jsonify({"sources": _get_available_sources()})


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """启动爬虫。"""
    global _scraper_thread, _status
    if _status == "running":
        return jsonify({"error": "爬虫正在运行中"}), 409
    _stop_event.clear()
    _scraper_thread = threading.Thread(target=_run_scraper, daemon=True)
    _scraper_thread.start()
    return jsonify({"status": "running", "article_count": len(_articles)})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """暂停爬虫。"""
    global _status
    if _status != "running":
        return jsonify({"error": "爬虫未在运行"}), 409
    _stop_event.set()
    _status = "stopped"
    return jsonify({"status": "stopped", "article_count": len(_articles)})


@app.route("/api/config", methods=["POST"])
def api_config():
    """配置启用的数据源。"""
    global _enabled_sites
    from config.sites import SITE_CONFIGS

    data = request.get_json(silent=True) or {}
    sites = data.get("sites", [])
    if not isinstance(sites, list):
        return jsonify({"error": "sites 必须是数组"}), 400
    invalid_sites = [site for site in sites if site not in SITE_CONFIGS]
    if invalid_sites:
        return jsonify({"error": f"未知站点: {', '.join(invalid_sites)}"}), 400
    _enabled_sites = sites
    return jsonify({"enabled": _enabled_sites, "sources": _get_available_sources()})


@app.route("/api/tweets")
def api_tweets():
    """推文列表，支持 ?player= 和 ?type= 和 ?days= 筛选。按时间倒序排列。"""
    from datetime import datetime, timezone, timedelta
    player = request.args.get("player", "")
    tweet_type = request.args.get("type", "")
    days = request.args.get("days", "0")  # 默认返回全部
    filtered = list(_tweets)
    if player:
        filtered = [t for t in filtered if t.get("player_handle", "").lower() == player.lower()]
    if tweet_type:
        filtered = [t for t in filtered if t.get("tweet_type") == tweet_type]
    # 时效性过滤：默认只返回最近 N 天的推文
    try:
        max_days = int(days)
    except (ValueError, TypeError):
        return jsonify({"error": "参数 days 必须是整数"}), 400
    if max_days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat()
        filtered = [t for t in filtered if t.get("tweet_date", "") >= cutoff]
    # 按时间倒序排列（最新在前）
    filtered.sort(key=lambda t: t.get("tweet_date", ""), reverse=True)
    return jsonify(filtered)


@app.route("/api/tweet-status")
def api_tweet_status():
    """推文爬虫状态（含最新日志）。"""
    recent_logs = _service_logs[-500:] if _service_logs else []
    errors = [l for l in _service_logs[-50:] if l["level"] == "error"]
    all_tweets = list(_tweets)
    return jsonify({
        "status": _tweet_status,
        "screenshot_status": _screenshot_status,
        "source_mode": _tweet_source_mode,
        "source_message": _tweet_source_message,
        "tweet_count": len(all_tweets),
        "recent_logs": recent_logs,
        "error_count": len(errors),
        "stats": {
            "total": len(all_tweets),
            "players": len(set(t.get("player_handle", "") for t in all_tweets)),
            "videos": len([t for t in all_tweets if t.get("video_url")]),
            "translated": len([t for t in all_tweets if t.get("translation_status") == "completed"]),
        },
    })


@app.route("/api/logs")
def api_logs():
    """返回服务运行日志。"""
    limit = request.args.get("limit", "50")
    try:
        limit = min(int(limit), 200)  # 最大 200 条
    except ValueError:
        limit = 50
    return jsonify(_service_logs[-limit:])


@app.route("/api/scrape-tweets", methods=["POST"])
def api_scrape_tweets():
    """启动推文爬虫。"""
    global _tweet_scraper_thread, _tweet_status
    if _tweet_status == "running":
        return jsonify({"error": "推文爬虫正在运行中"}), 409
    _tweet_stop_event.clear()
    _log("推文抓取已启动")
    _tweet_scraper_thread = threading.Thread(target=_run_tweet_scraper, daemon=True)
    _tweet_scraper_thread.start()
    return jsonify({"status": "running", "tweet_count": len(_tweets)})


@app.route("/api/stop-tweets", methods=["POST"])
def api_stop_tweets():
    """停止推文爬虫。"""
    global _tweet_status
    if _tweet_status != "running":
        return jsonify({"error": "推文爬虫未在运行"}), 409
    _tweet_stop_event.set()
    _tweet_status = "idle"
    _log("推文抓取已请求停止。", "warn")
    return jsonify({"status": "stopped"})


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """关闭服务器。"""
    import os, signal
    _log("服务器正在关闭...", "warn")
    func = request.environ.get('werkzeug.server.shutdown')
    if func:
        func()
    else:
        os.kill(os.getpid(), signal.SIGTERM)
    return jsonify({"message": "服务器正在关闭..."})


@app.route("/api/restart", methods=["POST"])
def api_restart():
    """重启服务器（通过退出进程让外部监控重新启动）。"""
    import os, sys, signal, subprocess
    _log("服务器正在重启...", "warn")
    # 启动新进程
    subprocess.Popen(
        [sys.executable, "-m", "web.app", "--host", "0.0.0.0", "--port", "5000"],
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    # 关闭当前进程
    os.kill(os.getpid(), signal.SIGTERM)
    return jsonify({"message": "服务器正在重启..."})


# ── Video 服务器代理 ──────────────────────────────────────
VIDEO_SERVER = "http://localhost:8000"


@app.route("/api/video-server/health")
def api_video_server_health():
    """检查 Video 服务器状态。"""
    import urllib.request, urllib.error
    try:
        resp = urllib.request.urlopen(f"{VIDEO_SERVER}/health", timeout=2)
        data = json.loads(resp.read().decode("utf-8"))
        # 验证返回的是有效的 health response
        if data.get("status") == "ok":
            return jsonify({"online": True, **data})
        return jsonify({"online": False})
    except Exception:
        return jsonify({"online": False})


@app.route("/api/video-server/start", methods=["POST"])
def api_video_server_start():
    """启动 Video 服务器。"""
    import subprocess, sys
    video_dir = Path(__file__).resolve().parent.parent.parent / "NBAVedio"
    if not video_dir.exists():
        _log(f"NBAVedio 目录不存在: {video_dir}", "error")
        return jsonify({"error": f"NBAVedio 目录不存在: {video_dir}"}), 404
    # 检查是否已经在运行
    import urllib.request, urllib.error
    try:
        urllib.request.urlopen(f"{VIDEO_SERVER}/health", timeout=3)
        _log("Video 服务器已在运行。")
        return jsonify({"message": "Video 服务器已在运行"})
    except Exception:
        pass
    try:
        # 先测试 import 是否正常
        check = subprocess.run(
            [sys.executable, "-c", "from tweet_api import app"],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
            cwd=str(video_dir),
        )
        if check.returncode != 0:
            err_msg = check.stderr.strip().split("\n")[-1] if check.stderr else "未知错误"
            _log(f"Video 服务器启动失败: {err_msg}", "error")
            return jsonify({"error": f"Video 服务器启动失败: {err_msg}"}), 500
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tweet_api:app",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=str(video_dir),
        )
        _log("Video 服务器已启动。")
        return jsonify({"message": "Video 服务器启动中..."})
    except Exception as e:
        _log(f"Video 服务器启动异常: {e}", "error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/video-server/shutdown", methods=["POST"])
def api_video_server_shutdown():
    """关闭 Video 服务器（通过查找端口占用进程并终止）。"""
    import subprocess
    try:
        # 查找占用 8000 端口的进程及其所有子进程
        ps_cmd = (
            "$conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; "
            "if ($conns) { "
            "  $pids = @($conns | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique); "
            "  # 找到这些进程的子进程\n"
            "  $children = @(Get-CimInstance Win32_Process | Where-Object { $pids -contains $_.ParentProcessId } | "
            "    ForEach-Object { $_.ProcessId }); "
            "  $allPids = @($pids + $children) | Sort-Object -Unique; "
            "  foreach ($p in $allPids) { & taskkill /F /PID $p 2>&1 | Out-Null }; "
            "  ($allPids -join ',') "
            "} else { 'NONE' }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
        )
        output = (result.stdout or "").strip()
        if output == "NONE" or not output:
            return jsonify({"message": "Video 服务器未在运行"})
        _log(f"Video 服务器已关闭 (PID={output})。", "warn")
        return jsonify({"message": f"Video 服务器已关闭 (PID={output})"})
    except Exception as e:
        _log(f"关闭 Video 服务器失败: {e}", "error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/video-server/restart", methods=["POST"])
def api_video_server_restart():
    """重启 Video 服务器。"""
    import time as _time
    api_video_server_shutdown()
    _time.sleep(2)
    return api_video_server_start()


@app.route("/api/video-server/logs")
def api_video_server_logs():
    """获取 Video 服务器日志（优先读本地日志文件，fallback 到 API）。"""
    log_file = Path(__file__).resolve().parent.parent.parent / "NBAVedio" / "output" / "logs" / "video.log"
    if log_file.exists():
        try:
            content = log_file.read_text(encoding="utf-8").strip()
            if content:
                return jsonify(content)
            return jsonify("")
        except Exception:
            pass
    # fallback: 从 video server API 获取
    import urllib.request, urllib.error
    try:
        resp = urllib.request.urlopen(f"{VIDEO_SERVER}/logs", timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        return jsonify(data)
    except Exception:
        return jsonify("")


@app.route("/api/generated-videos", methods=["GET", "DELETE"])
def api_generated_videos():
    """代理获取或删除全部已生成的视频。"""
    import urllib.request, urllib.error
    if request.method == "DELETE":
        try:
            req = urllib.request.Request(f"{VIDEO_SERVER}/videos", method="DELETE")
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    try:
        resp = urllib.request.urlopen(f"{VIDEO_SERVER}/videos", timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        return jsonify(data)
    except Exception:
        return jsonify([])


@app.route("/api/generated-video/<filename>", methods=["GET", "DELETE"])
def api_generated_video(filename):
    """代理获取或删除已生成的视频文件。"""
    import urllib.request, urllib.error
    if ".." in filename or "/" in filename or "\\" in filename:
        return "非法文件名", 400
    if request.method == "DELETE":
        try:
            req = urllib.request.Request(f"{VIDEO_SERVER}/video/{filename}", method="DELETE")
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    try:
        resp = urllib.request.urlopen(f"{VIDEO_SERVER}/video/{filename}", timeout=30)
        from flask import Response
        return Response(resp.read(), mimetype="video/mp4")
    except Exception:
        return "视频未找到", 404


def _run_tweet_scraper() -> None:
    """在后台线程中运行推文爬虫。"""
    global _tweet_status, _tweets
    _tweet_status = "running"
    _set_tweet_source("running", "正在刷新推文来源...")
    _log("开始抓取推文...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tweets = loop.run_until_complete(_async_scrape_tweets())
        if tweets:
            with _tweets_lock:
                old_by_id = {t["tweet_id"]: t for t in _tweets}
                # 合并时保留旧条目的本地媒体字段（视频、封面等）
                LOCAL_FIELDS = ("video_url", "video_path", "video_duration",
                                "video_resolution", "cover_image_path")
                for t in tweets:
                    tid = t["tweet_id"]
                    if tid in old_by_id:
                        old = old_by_id[tid]
                        for field in LOCAL_FIELDS:
                            if old.get(field) and not t.get(field):
                                t[field] = old[field]
                    old_by_id[tid] = t
                _tweets.clear()
                merged = sorted(old_by_id.values(), key=lambda t: t.get("tweet_date", ""), reverse=True)
                # 每个球星只保留最新一条
                seen_handles = set()
                kept = []
                for t in merged:
                    h = t.get("player_handle", "")
                    if h not in seen_handles:
                        seen_handles.add(h)
                        kept.append(t)
                _tweets.extend(kept)
            _save_tweets()
            if _tweet_source_mode == "cache":
                _log(f"实时源不可用，继续显示缓存数据 {len(tweets)} 条。", "warn")
            else:
                _log(f"抓取完成: 获取 {len(tweets)} 条，去重后总计 {len(_tweets)} 条", "success")
        else:
            _log(_tweet_source_message or "抓取完成但未获取到可用推文。", "error")
    except Exception as e:
        import traceback
        _set_tweet_source("failed", f"推文爬虫错误: {e}")
        _log(f"推文爬虫错误: {e}", "error")
        traceback.print_exc()
    finally:
        _tweet_stop_event.clear()
        _tweet_status = "idle"


def _save_tweets() -> None:
    """保存推文到 JSON。"""
    TWEETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TWEETS_FILE, "w", encoding="utf-8") as f:
        json.dump(_tweets, f, ensure_ascii=False, indent=2)


async def _fetch_tweets_via_nitter_rss_v2(players) -> list[dict]:
    """通过 Nitter RSS 获取最新推文，逐条：抓取→翻译→保存→异步截图（与下一条抓取并行）。

    反爬策略：多实例轮换、UA轮换、随机延迟、429退避、连续失败熔断。
    """
    import random
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    from xml.etree import ElementTree
    import urllib.request
    import urllib.error
    from config.settings import get_settings
    global _screenshot_status

    settings = get_settings()
    covers_dir = settings.output_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)

    NITTER_RSS_INSTANCES = [
        "https://nitter.net",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ]
    UA_LIST = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    ]
    MAX_PER_PLAYER = 1
    RSS_DELAY_MIN = 4.0
    RSS_DELAY_MAX = 8.0
    RSS_429_DELAY = 20.0
    MAX_CONSECUTIVE_FAIL = 5

    # 初始化翻译器
    translator_backend = None
    expand_twitter_slang = None
    POST_TRANSLATION_FIXES = {}
    try:
        from translator.google_translator import DeepTranslatorBackend
        from config.glossary import expand_twitter_slang as _expand, POST_TRANSLATION_FIXES as _fixes
        translator_backend = DeepTranslatorBackend()
        expand_twitter_slang = _expand
        POST_TRANSLATION_FIXES = _fixes
    except Exception as exc:
        _log(f"翻译器初始化失败: {exc}", "error")

    # 初始化 Playwright（后台截图共享）
    pw_instance = None
    browser = None
    try:
        from playwright.async_api import async_playwright
        pw_instance = await async_playwright().start()
        browser = await pw_instance.chromium.launch(
            headless=True, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"],
        )
        _log("Playwright 已启动（截图与抓取并行）。")
    except Exception as exc:
        _log(f"Playwright 初始化失败，截图将被跳过: {exc}", "warn")

    all_tweets = []
    screenshot_tasks = []  # 收集异步截图任务
    consecutive_fail = 0
    current_instance_idx = 0
    translated_count = 0
    _screenshot_status = "running" if browser else "idle"

    _log(f"使用 NitterRSS 抓取 {len(players)} 个账号（抓取+截图并行）...")

    async def _screenshot_one(tid, covers_dir, browser):
        """单条推文异步截图。"""
        import random
        output_path = covers_dir / f"{tid}.jpg"
        if output_path.exists() and output_path.stat().st_size > 0:
            with _tweets_lock:
                for t in _tweets:
                    if t.get("tweet_id") == tid:
                        t["cover_image_path"] = f"covers/{tid}.jpg"
                        break
            _save_tweets()
            _log(f"截图缓存命中: {tid}")
            return

        try:
            page = await browser.new_page(viewport={"width": 550, "height": 800})
            embed_url = f"https://platform.twitter.com/embed/Tweet.html?id={tid}"
            await page.goto(embed_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_selector("article", timeout=15000)
            await page.screenshot(
                path=str(output_path), type="jpeg", quality=85, full_page=True,
            )
            await page.close()
            with _tweets_lock:
                for t in _tweets:
                    if t.get("tweet_id") == tid:
                        t["cover_image_path"] = f"covers/{tid}.jpg"
                        break
            _save_tweets()
            _log(f"截图完成: {tid}")
        except Exception as exc:
            _log(f"截图失败 {tid}: {str(exc)[:60]}", "warn")
            try:
                await page.close()
            except Exception:
                pass

    async def _download_video_one(tid, handle, videos_dir):
        """通过 fxtwitter API 获取视频 URL 并下载。"""
        video_filename = f"tweet_{tid}.mp4"
        video_path = videos_dir / video_filename
        if video_path.exists() and video_path.stat().st_size > 0:
            with _tweets_lock:
                for t in _tweets:
                    if t.get("tweet_id") == tid:
                        t["video_url"] = f"/video/{video_filename}"
                        break
            _save_tweets()
            _log(f"视频缓存命中: {tid}")
            return

        try:
            fx_url = f"https://api.fxtwitter.com/{handle}/status/{tid}"
            fx_req = urllib.request.Request(fx_url, headers={
                "User-Agent": random.choice(UA_LIST),
                "Accept": "application/json",
            })
            fx_resp = urllib.request.urlopen(fx_req, timeout=15)
            fx_data = json.loads(fx_resp.read().decode("utf-8", errors="replace"))
            tweet_obj = fx_data.get("tweet", {})
            media_all = tweet_obj.get("media", {}).get("all", [])

            video_url = None
            for m in media_all:
                if m.get("type") == "video" and m.get("url"):
                    video_url = m["url"]
                    break

            if not video_url:
                return

            # 下载视频
            vid_req = urllib.request.Request(video_url, headers={
                "User-Agent": random.choice(UA_LIST),
            })
            vid_resp = urllib.request.urlopen(vid_req, timeout=60)
            with open(str(video_path), "wb") as f:
                while True:
                    chunk = vid_resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

            with _tweets_lock:
                for t in _tweets:
                    if t.get("tweet_id") == tid:
                        t["video_url"] = f"/video/{video_filename}"
                        break
            _save_tweets()
            size_mb = video_path.stat().st_size / 1024 / 1024
            _log(f"视频下载完成: {tid} ({size_mb:.1f}MB)")

        except Exception as exc:
            _log(f"视频下载失败 {tid}: {str(exc)[:60]}", "warn")

    try:
        for index, player in enumerate(players):
            if _tweet_stop_event.is_set():
                _log("用户已停止抓取。", "warn")
                break

            handle = player.handle

            if consecutive_fail >= MAX_CONSECUTIVE_FAIL:
                _log(f"连续 {consecutive_fail} 次 RSS 失败，熔断停止。", "warn")
                break

            fetched = False
            tried_instances = 0

            while tried_instances < len(NITTER_RSS_INSTANCES):
                instance = NITTER_RSS_INSTANCES[current_instance_idx % len(NITTER_RSS_INSTANCES)]
                try:
                    ua = random.choice(UA_LIST)
                    rss_url = f"{instance}/{handle}/rss"
                    req = urllib.request.Request(rss_url, headers={
                        "User-Agent": ua,
                        "Accept": "application/rss+xml, application/xml, text/xml",
                    })
                    resp = urllib.request.urlopen(req, timeout=15)
                    data = resp.read().decode("utf-8", errors="replace")
                    root = ElementTree.fromstring(data)
                    items = root.findall(".//item")

                    player_count = 0
                    fallback_rt_item = None  # 备用：第一条 RT

                    for item in items:
                        if player_count >= MAX_PER_PLAYER:
                            break

                        link = item.find("link")
                        link_text = link.text.strip() if link is not None and link.text else ""
                        if "/status/" not in link_text:
                            continue
                        tid = link_text.split("/status/")[-1].split("#")[0].split("?")[0]
                        if not tid.isdigit():
                            continue

                        title_el = item.find("title")
                        title_text = title_el.text.strip() if title_el is not None and title_el.text else ""

                        if title_text.startswith("RT by"):
                            # 记住第一条 RT 作为备用
                            if fallback_rt_item is None:
                                fallback_rt_item = item
                            continue

                        content = title_text
                        if not content or len(content) < 5:
                            continue

                        # 检测是否有视频
                        desc_el = item.find("description")
                        desc_text = desc_el.text if desc_el is not None and desc_el.text else ""
                        has_video = ">Video<" in desc_text

                        pubdate_el = item.find("pubDate")
                        tweet_date = datetime.now(timezone.utc).isoformat()
                        if pubdate_el is not None and pubdate_el.text:
                            try:
                                tweet_date = parsedate_to_datetime(pubdate_el.text.strip()).isoformat()
                            except Exception:
                                pass

                        # 1. 翻译
                        content_cn = None
                        translation_status = "pending"
                        if translator_backend and expand_twitter_slang:
                            try:
                                text_expanded = expand_twitter_slang(content)
                                content_cn = await translator_backend.translate(text_expanded)
                                for wrong, right in POST_TRANSLATION_FIXES.items():
                                    content_cn = content_cn.replace(wrong, right)
                                translation_status = "completed"
                                translated_count += 1
                            except Exception:
                                translation_status = "failed"

                        # 2. 组装数据
                        tweet_data = {
                            "tweet_id": str(tid),
                            "player_name": player.name,
                            "player_handle": handle,
                            "content": content[:500],
                            "content_cn": content_cn,
                            "url": f"https://x.com/{handle}/status/{tid}",
                            "media_urls": [],
                            "cover_image_path": None,
                            "video_url": None,
                            "retweet_count": 0,
                            "like_count": 0,
                            "reply_count": 0,
                            "tweet_type": "original",
                            "tweet_date": tweet_date,
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "translation_status": translation_status,
                        }
                        all_tweets.append(tweet_data)
                        player_count += 1

                        _log(f"[{index+1}/{len(players)}] @{handle}: 抓取+翻译({translation_status}){' [有视频]' if has_video else ''} 完成")

                        # 3. 实时保存
                        with _tweets_lock:
                            old_by_id = {t["tweet_id"]: t for t in _tweets}
                            old_by_id[tweet_data["tweet_id"]] = tweet_data
                            _tweets.clear()
                            merged = sorted(old_by_id.values(), key=lambda t: t.get("tweet_date", ""), reverse=True)
                            _tweets.extend(merged)
                        _save_tweets()

                        # 4. 异步提交截图（不等待，与下一条抓取并行）
                        if browser:
                            task = asyncio.ensure_future(_screenshot_one(tid, covers_dir, browser))
                            screenshot_tasks.append(task)

                        # 5. 有视频则异步下载
                        if has_video:
                            videos_dir = settings.output_dir / "videos"
                            videos_dir.mkdir(parents=True, exist_ok=True)
                            task = asyncio.ensure_future(_download_video_one(tid, handle, videos_dir))
                            screenshot_tasks.append(task)

                    if player_count == 0 and fallback_rt_item is not None:
                        # 没有原创推文，用第一条 RT
                        rt_item = fallback_rt_item
                        rt_link = rt_item.find("link")
                        rt_link_text = rt_link.text.strip() if rt_link is not None and rt_link.text else ""
                        rt_tid = rt_link_text.split("/status/")[-1].split("#")[0].split("?")[0]

                        rt_title_el = rt_item.find("title")
                        rt_title_text = rt_title_el.text.strip() if rt_title_el is not None and rt_title_el.text else ""
                        # "RT by @handle: original content" -> 取 original content
                        rt_content = rt_title_text
                        if ": " in rt_content:
                            rt_content = rt_content.split(": ", 1)[1]

                        rt_desc_el = rt_item.find("description")
                        rt_desc_text = rt_desc_el.text if rt_desc_el is not None and rt_desc_el.text else ""
                        rt_has_video = ">Video<" in rt_desc_text

                        rt_pubdate_el = rt_item.find("pubDate")
                        rt_tweet_date = datetime.now(timezone.utc).isoformat()
                        if rt_pubdate_el is not None and rt_pubdate_el.text:
                            try:
                                rt_tweet_date = parsedate_to_datetime(rt_pubdate_el.text.strip()).isoformat()
                            except Exception:
                                pass

                        # 翻译 RT 内容
                        rt_content_cn = None
                        rt_translation_status = "pending"
                        if translator_backend and expand_twitter_slang and rt_content and len(rt_content) >= 5:
                            try:
                                rt_text_expanded = expand_twitter_slang(rt_content)
                                rt_content_cn = await translator_backend.translate(rt_text_expanded)
                                for wrong, right in POST_TRANSLATION_FIXES.items():
                                    rt_content_cn = rt_content_cn.replace(wrong, right)
                                rt_translation_status = "completed"
                                translated_count += 1
                            except Exception:
                                rt_translation_status = "failed"

                        rt_tweet_data = {
                            "tweet_id": str(rt_tid),
                            "player_name": player.name,
                            "player_handle": handle,
                            "content": rt_content[:500] if rt_content else "",
                            "content_cn": rt_content_cn,
                            "url": f"https://x.com/{handle}/status/{rt_tid}",
                            "media_urls": [],
                            "cover_image_path": None,
                            "video_url": None,
                            "retweet_count": 0,
                            "like_count": 0,
                            "reply_count": 0,
                            "tweet_type": "retweet",
                            "tweet_date": rt_tweet_date,
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "translation_status": rt_translation_status,
                        }
                        all_tweets.append(rt_tweet_data)
                        player_count += 1

                        _log(f"[{index+1}/{len(players)}] @{handle}: 无原创推文，使用 RT ({rt_translation_status}){' [有视频]' if rt_has_video else ''}")

                        with _tweets_lock:
                            old_by_id = {t["tweet_id"]: t for t in _tweets}
                            old_by_id[rt_tweet_data["tweet_id"]] = rt_tweet_data
                            _tweets.clear()
                            merged = sorted(old_by_id.values(), key=lambda t: t.get("tweet_date", ""), reverse=True)
                            _tweets.extend(merged)
                        _save_tweets()

                        if browser:
                            task = asyncio.ensure_future(_screenshot_one(rt_tid, covers_dir, browser))
                            screenshot_tasks.append(task)

                        if rt_has_video:
                            videos_dir = settings.output_dir / "videos"
                            videos_dir.mkdir(parents=True, exist_ok=True)
                            task = asyncio.ensure_future(_download_video_one(rt_tid, handle, videos_dir))
                            screenshot_tasks.append(task)

                    if player_count > 0:
                        fetched = True
                        consecutive_fail = 0
                    else:
                        _log(f"[{index+1}/{len(players)}] @{handle}: RSS 无可用推文 ({instance})", "warn")

                    break

                except urllib.error.HTTPError as http_err:
                    if http_err.code == 429:
                        _log(f"[{index+1}/{len(players)}] @{handle}: {instance} 429 限频，切换实例...", "warn")
                        current_instance_idx += 1
                        tried_instances += 1
                        await asyncio.sleep(RSS_429_DELAY)
                        continue
                    else:
                        _log(f"[{index+1}/{len(players)}] @{handle}: {instance} HTTP {http_err.code}", "warn")
                        current_instance_idx += 1
                        tried_instances += 1
                        continue

                except Exception as exc:
                    _log(f"[{index+1}/{len(players)}] @{handle}: {instance} 失败 ({str(exc)[:50]})", "warn")
                    current_instance_idx += 1
                    tried_instances += 1
                    continue

            if not fetched:
                consecutive_fail += 1
                _log(f"[{index+1}/{len(players)}] @{handle}: 所有实例均失败 (连续失败 {consecutive_fail}/{MAX_CONSECUTIVE_FAIL})", "warn")

            delay = random.uniform(RSS_DELAY_MIN, RSS_DELAY_MAX)
            await asyncio.sleep(delay)

        _log(f"NitterRSS 抓取完成: {len(all_tweets)} 条推文, {translated_count} 条翻译", "success" if all_tweets else "warn")

        # 等待所有截图任务完成
        if screenshot_tasks:
            _log(f"等待 {len(screenshot_tasks)} 个截图任务完成...")
            await asyncio.gather(*screenshot_tasks, return_exceptions=True)

    finally:
        _screenshot_status = "idle"
        if browser:
            await browser.close()
        if pw_instance:
            await pw_instance.stop()

    _log(f"全部完成: {len(all_tweets)} 条推文+翻译+截图", "success" if all_tweets else "warn")
    return all_tweets


async def _background_screenshot(tweets, covers_dir) -> None:
    """后台为推文截图（不阻塞主流程）。逐条截图，每完成一条立刻同步保存。"""
    global _screenshot_status
    import random

    EMBED_DELAY_MIN = 2.0
    EMBED_DELAY_MAX = 5.0

    _screenshot_status = "running"

    pw_instance = None
    browser = None
    screenshot_count = 0
    total = len(tweets)

    _log(f"后台截图开始: {total} 条推文...")

    try:
        from playwright.async_api import async_playwright
        pw_instance = await async_playwright().start()
        browser = await pw_instance.chromium.launch(
            headless=True, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"],
        )

        for tweet_data in tweets:
            tid = tweet_data.get("tweet_id", "")
            if not tid:
                continue

            output_path = covers_dir / f"{tid}.jpg"
            if output_path.exists() and output_path.stat().st_size > 0:
                tweet_data["cover_image_path"] = f"covers/{tid}.jpg"
                screenshot_count += 1
                with _tweets_lock:
                    for t in _tweets:
                        if t.get("tweet_id") == tid:
                            t["cover_image_path"] = f"covers/{tid}.jpg"
                            break
                _save_tweets()
                continue

            try:
                page = await browser.new_page(viewport={"width": 550, "height": 800})
                embed_url = f"https://platform.twitter.com/embed/Tweet.html?id={tid}"
                await page.goto(embed_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_selector("article", timeout=15000)
                await page.screenshot(
                    path=str(output_path), type="jpeg", quality=85, full_page=True,
                )
                await page.close()
                tweet_data["cover_image_path"] = f"covers/{tid}.jpg"
                screenshot_count += 1
                _log(f"截图 {screenshot_count}/{total}: {tid}")
                # 每截一张就同步到全局并保存
                with _tweets_lock:
                    for t in _tweets:
                        if t.get("tweet_id") == tid:
                            t["cover_image_path"] = f"covers/{tid}.jpg"
                            break
                _save_tweets()
            except Exception as exc:
                _log(f"截图失败 {tid}: {str(exc)[:60]}", "warn")
                try:
                    await page.close()
                except Exception:
                    pass

            delay = random.uniform(EMBED_DELAY_MIN, EMBED_DELAY_MAX)
            await asyncio.sleep(delay)

    except Exception as exc:
        _log(f"Playwright 初始化失败: {exc}", "error")
    finally:
        if browser:
            await browser.close()
        if pw_instance:
            await pw_instance.stop()

    # 截图完成后同步到全局 _tweets 并保存 JSON
    with _tweets_lock:
        tweets_by_id = {t["tweet_id"]: t for t in tweets if t.get("cover_image_path")}
        for t in _tweets:
            tid = t.get("tweet_id")
            if tid in tweets_by_id:
                t["cover_image_path"] = tweets_by_id[tid]["cover_image_path"]
    _save_tweets()
    _screenshot_status = "idle"
    _log(f"后台截图完成: {screenshot_count}/{total} 张", "success" if screenshot_count else "warn")


async def _async_scrape_tweets() -> list[dict]:
    """抓取最新推文。NitterRSS 方案：逐条抓取→翻译→保存，截图与抓取并行。"""
    from config.players import load_players

    players = load_players()

    # 方案 A: 官方 Twitter API v2（需要 Bearer Token）
    all_tweets = await _fetch_tweets_via_twitter_api(players)
    if all_tweets:
        _set_tweet_source("api", "实时推文来自 Twitter API v2。")
        filtered = _filter_latest_tweets(all_tweets)
        await _translate_tweets(filtered)
        return filtered

    # 方案 B: Nitter RSS（逐条抓取+翻译+并行截图）
    all_tweets = await _fetch_tweets_via_nitter_rss_v2(players)
    if all_tweets:
        _set_tweet_source("rss", "实时推文来自 NitterRSS（抓取+截图并行）。")
        return all_tweets

    # 方案 C-E: 降级方案（批量翻译，无截图）
    all_tweets = await _fetch_tweets_via_syndication(players)
    if all_tweets:
        _set_tweet_source("syndication", "实时推文来自 Syndication+fxtwitter 聚合。")
    else:
        all_tweets = await _fetch_tweets_via_fxtwitter_refresh(players)
        if all_tweets:
            _set_tweet_source("fxtwitter", "推文数据已通过 fxtwitter 刷新。")
        else:
            all_tweets = await _fetch_tweets_via_nitter_rss(players)
            if all_tweets:
                _set_tweet_source("nitter", "实时推文来自兼容 RSS 源。")

    if not all_tweets:
        cached = _get_cached_tweets(limit=30)
        if cached:
            message = "外部实时源当前不可用，继续显示上次成功抓取的缓存数据。"
            _set_tweet_source("cache", message)
            _log(message, "warn")
            return cached

        message = "未能获取实时推文：请配置 TWITTER_BEARER_TOKEN，或稍后重试外部兼容源。"
        _set_tweet_source("failed", message)
        _log(message, "error")
        return []

    filtered = _filter_latest_tweets(all_tweets)
    translated = await _translate_tweets(filtered)
    _log(f"抓取流程完成: {len(filtered)} 条推文，{translated} 条已翻译", "success")
    return filtered


@app.route("/api/players")
def api_players():
    """返回球星列表。"""
    try:
        from config.players import load_players
        players = load_players()
        return jsonify([{"name": p.name, "handle": p.handle, "team": p.team} for p in players])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/covers/<path:filename>")
def serve_cover(filename):
    """提供推文封面图片（仅允许 .jpg 文件名）。"""
    import re
    # 安全校验：只允许 ASCII 字母/数字/下划线/横线 + .jpg
    if not re.fullmatch(r'[a-zA-Z0-9_\-]+\.jpg', filename):
        from flask import abort
        abort(404)
    covers_dir = Path(__file__).resolve().parent.parent / "output" / "covers"
    from flask import send_from_directory
    return send_from_directory(str(covers_dir), filename)


@app.route("/video/<path:filename>")
def serve_video(filename):
    """提供视频文件（从视频 API 输出目录）。"""
    import re
    from flask import abort, send_from_directory
    # 安全校验：只允许 tweet_xxxxx.mp4 格式
    if not re.fullmatch(r'tweet_[a-zA-Z0-9_\-]+\.mp4', filename):
        abort(404)
    # 视频存储目录
    video_dir = Path("d:/vedio/output/tweet_videos")
    if not video_dir.exists():
        # 降级到本地 output 目录
        video_dir = Path(__file__).resolve().parent.parent / "output" / "videos"
    if not (video_dir / filename).exists():
        abort(404)
    return send_from_directory(str(video_dir), filename, mimetype="video/mp4")


@app.route("/api/generate-videos", methods=["POST"])
def api_generate_videos():
    """启动视频生成流程（后台线程）。支持 JSON body: {tweet_ids: [...]} 选择性生成。"""
    global _video_gen_thread, _video_gen_status
    if _video_gen_status == "running":
        return jsonify({"error": "视频生成正在运行中"}), 409
    data = request.get_json(silent=True) or {}
    tweet_ids = data.get("tweet_ids", [])
    backend = data.get("backend", None)
    _video_gen_thread = threading.Thread(target=_run_video_generation, args=(tweet_ids, backend), daemon=True)
    _video_gen_thread.start()
    with _tweets_lock:
        if tweet_ids:
            count = len(tweet_ids)
        else:
            count = sum(1 for t in _tweets if not t.get("video_url"))
    return jsonify({"status": "running", "count": count})


@app.route("/api/video-status")
def api_video_status():
    """视频生成状态。"""
    with_video = sum(1 for t in _tweets if t.get("video_url") and len(str(t.get("video_url", ""))) > 5)
    return jsonify({
        "status": _video_gen_status,
        "total": len(_tweets),
        "with_video": with_video,
        "pending": len(_tweets) - with_video,
        "gen_current": _video_gen_progress["current"],
        "gen_total": _video_gen_progress["total"],
    })


_video_gen_status: str = "idle"
_video_gen_thread: threading.Thread | None = None
_video_gen_progress: dict = {"current": 0, "total": 0}


def _run_video_generation(tweet_ids=None, backend=None):
    """后台执行视频生成（使用 urllib）。tweet_ids 为空则生成所有无视频的推文。backend: claude/gpt。"""
    global _video_gen_status, _tweets, _video_gen_progress
    _video_gen_status = "running"
    start_time = time.time()
    MAX_TIMEOUT = 1800  # 30分钟，每条视频可能需要几分钟

    try:
        import urllib.request
        import urllib.error

        with _tweets_lock:
            if tweet_ids:
                tid_set = set(tweet_ids)
                pending = [t for t in _tweets if t.get("tweet_id") in tid_set]
            else:
                pending = [t for t in _tweets if not t.get("video_url")]
        _video_gen_progress = {"current": 0, "total": len(pending)}
        print(f"Video generation: {len(pending)} tweets pending")

        for i, tweet in enumerate(pending):
            _video_gen_progress["current"] = i
            if time.time() - start_time > MAX_TIMEOUT:
                print(f"  Video generation timeout")
                break

            cover_path = tweet.get("cover_image_path", "")
            if not cover_path:
                continue
            image_file = Path(__file__).resolve().parent.parent / "output" / cover_path
            if not image_file.exists():
                continue

            content_cn = tweet.get("content_cn") or tweet.get("content", "")
            content_en = tweet.get("content", "")
            author = tweet.get("player_name", "")

            # Build multipart with urllib
            boundary = f"----FormBoundary{int(time.time()*1000)}"
            body = b""
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="images"; filename="{image_file.name}"\r\n'.encode()
            body += b"Content-Type: image/jpeg\r\n\r\n"
            body += image_file.read_bytes()
            body += b"\r\n"
            for key, val in [("translations", content_cn), ("authors", author), ("original_texts", content_en), ("duration", "8")] + ([("backend", backend)] if backend else []):
                body += f"--{boundary}\r\n".encode()
                body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                body += val.encode("utf-8")
                body += b"\r\n"

            # 如果推文有本地下载的原始视频，附加上传
            tweet_id = tweet.get("tweet_id", "")
            if tweet_id:
                source_video = Path(__file__).resolve().parent.parent / "output" / "videos" / f"tweet_{tweet_id}.mp4"
                if source_video.exists():
                    body += f"--{boundary}\r\n".encode()
                    body += f'Content-Disposition: form-data; name="video"; filename="{source_video.name}"\r\n'.encode()
                    body += b"Content-Type: video/mp4\r\n\r\n"
                    body += source_video.read_bytes()
                    body += b"\r\n"
                    print(f"  Video [{i+1}/{len(pending)}] 附带推文视频: {source_video.name}")

            body += f"--{boundary}--\r\n".encode()

            try:
                req = urllib.request.Request(
                    "http://localhost:8000/generate-ai",
                    data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=600)
                result = json.loads(resp.read().decode("utf-8"))

                with _tweets_lock:
                    tweet["video_url"] = result.get("video_url", "")
                    tweet["video_path"] = result.get("video_path", "")
                    tweet["video_duration"] = result.get("duration", 0)
                    tweet["video_resolution"] = result.get("resolution", "")
                _save_tweets()
                score = result.get("ai_enhanced", {}).get("review", {}).get("score", "")
                print(f"  Video [{i+1}/{len(pending)}] @{tweet.get('player_handle')}: OK (score: {score})")
                _video_gen_progress["current"] = i + 1
            except urllib.error.HTTPError as e:
                print(f"  Video [{i+1}/{len(pending)}] FAIL: HTTP {e.code}")
                _video_gen_progress["current"] = i + 1
            except Exception as e:
                print(f"  Video [{i+1}/{len(pending)}] ERR: {e}")
                _video_gen_progress["current"] = i + 1

            time.sleep(2)

    except Exception as e:
        print(f"Video generation error: {e}")
    finally:
        _video_gen_status = "idle"


# ── 入口 ──────────────────────────────────────────────
def main(host: str = "127.0.0.1", port: int = 5000) -> None:
    """启动 Web 服务。"""
    _load_existing()
    print(f"Basketball News Web Dashboard: http://{host}:{port}")
    app.run(host=host, port=port)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    main(host=args.host, port=args.port)
