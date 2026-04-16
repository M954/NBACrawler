"""Web 仪表板接口与页面测试。"""

from __future__ import annotations

import asyncio

import web.app as web_app


def _sample_articles() -> list[dict]:
    return [
        {
            "title": "Yahoo headline",
            "title_cn": "雅虎头条",
            "summary": "Yahoo summary",
            "summary_cn": "雅虎摘要",
            "source": "Yahoo Sports NBA",
            "publish_date": "2026-04-11T02:00:00+00:00",
            "scraped_at": "2026-04-11T02:05:00+00:00",
            "translation_status": "completed",
            "url": "https://example.com/yahoo",
        },
        {
            "title": "ESPN headline",
            "title_cn": "ESPN 头条",
            "summary": "ESPN summary",
            "summary_cn": "ESPN 摘要",
            "source": "ESPN NBA",
            "publish_date": "2026-04-11T01:00:00+00:00",
            "scraped_at": "2026-04-11T01:05:00+00:00",
            "translation_status": "failed",
            "url": "https://example.com/espn",
        },
    ]


def _decode(response) -> str:
    return response.get_data(as_text=True)


def setup_function() -> None:
    web_app._articles = _sample_articles()
    web_app._tweets = []
    web_app._enabled_sites = ["yahoo_nba", "espn_nba", "cbs_nba"]
    web_app._status = "idle"
    web_app._tweet_status = "idle"
    web_app._tweet_source_mode = "idle"
    web_app._tweet_source_message = ""
    web_app._stop_event.clear()


def test_sources_api_keeps_enabled_and_loaded_sources() -> None:
    client = web_app.app.test_client()

    response = client.get("/api/sources")

    assert response.status_code == 200
    assert response.get_json() == {
        "sources": ["Yahoo Sports NBA", "ESPN NBA", "CBS Sports NBA"]
    }


def test_articles_api_filters_by_source() -> None:
    client = web_app.app.test_client()

    response = client.get("/api/articles?source=ESPN%20NBA")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload) == 1
    assert payload[0]["source"] == "ESPN NBA"


def test_config_rejects_unknown_site() -> None:
    client = web_app.app.test_client()

    response = client.post("/api/config", json={"sites": ["missing_site"]})

    assert response.status_code == 400
    assert response.get_json()["error"] == "未知站点: missing_site"


def test_index_embeds_stable_initial_sources() -> None:
    client = web_app.app.test_client()

    response = client.get("/")
    html = _decode(response)

    assert response.status_code == 200
    assert 'window.__INITIAL_SOURCES__ = ["Yahoo Sports NBA", "ESPN NBA", "CBS Sports NBA"]' in html
    assert "资讯列表" in html
    assert "Twitter API · Cached Fallback · Video AI" in html


def test_tweet_status_includes_source_state() -> None:
    client = web_app.app.test_client()
    web_app._tweets = [{"tweet_id": "1", "tweet_date": "2026-04-15T10:00:00+00:00"}]
    web_app._tweet_source_mode = "cache"
    web_app._tweet_source_message = "外部实时源当前不可用，继续显示上次成功抓取的缓存数据。"

    response = client.get("/api/tweet-status")

    assert response.status_code == 200
    assert response.get_json()["source_mode"] == "cache"
    assert "缓存数据" in response.get_json()["source_message"]


def test_async_scrape_tweets_falls_back_to_cached_snapshot(monkeypatch) -> None:
    async def fake_api(_players):
        return []

    async def fake_syndication(_players):
        return []

    async def fake_fxtwitter(_players):
        return []

    async def fake_nitter(_players):
        return []

    monkeypatch.setattr(web_app, "_fetch_tweets_via_twitter_api", fake_api)
    monkeypatch.setattr(web_app, "_fetch_tweets_via_syndication", fake_syndication)
    monkeypatch.setattr(web_app, "_fetch_tweets_via_fxtwitter_refresh", fake_fxtwitter)
    monkeypatch.setattr(web_app, "_fetch_tweets_via_nitter_rss", fake_nitter)
    web_app._tweets = [
        {
            "tweet_id": "older",
            "player_handle": "KingJames",
            "tweet_date": "2026-04-14T08:00:00+00:00",
            "content": "older",
        },
        {
            "tweet_id": "newer",
            "player_handle": "KingJames",
            "tweet_date": "2026-04-15T08:00:00+00:00",
            "content": "newer",
        },
    ]

    tweets = asyncio.run(web_app._async_scrape_tweets())

    assert [tweet["tweet_id"] for tweet in tweets] == ["newer", "older"]
    assert web_app._tweet_source_mode == "cache"
    assert "缓存数据" in web_app._tweet_source_message
