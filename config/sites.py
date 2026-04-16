"""站点配置。"""

from __future__ import annotations

from dataclasses import dataclass, field

from utils.exceptions import ConfigurationError


@dataclass(frozen=True)
class SiteSelectors:
    """列表页解析选择器。"""

    item: str
    title: str
    summary: str
    author: str
    publish_time: str
    link: str
    tags: str


@dataclass(frozen=True)
class SiteConfig:
    """单站点配置。"""

    key: str
    name: str
    base_url: str
    news_url: str
    source: str
    selectors: SiteSelectors | None = None
    headers: dict[str, str] = field(default_factory=dict)
    feed_type: str = "html"


NBA_SITE = SiteConfig(
    key="nba",
    name="NBA News",
    base_url="https://www.nba.com",
    news_url="https://www.nba.com/news",
    source="NBA News",
    selectors=SiteSelectors(
        item=(
            ".nba-card, article, div[class*='Card'], div[class*='Article'], "
            "section article"
        ),
        title=".nba-card__title, [class*='title'], h2, h3",
        summary=".nba-card__summary, [class*='summary'], p",
        author=".nba-card__author, [class*='author']",
        publish_time="time, [class*='date']",
        link="a[href]",
        tags=".nba-card__tag, [class*='tag'] li, [class*='tag'] span",
    ),
    headers={"Referer": "https://www.nba.com/"},
)

SITE_CONFIGS: dict[str, SiteConfig] = {
    "nba": NBA_SITE,
    "yahoo_nba": SiteConfig(
        key="yahoo_nba",
        name="Yahoo Sports NBA",
        base_url="https://sports.yahoo.com",
        news_url="https://sports.yahoo.com/nba/rss/",
        source="Yahoo Sports NBA",
        feed_type="rss",
    ),
    "espn_nba": SiteConfig(
        key="espn_nba",
        name="ESPN NBA",
        base_url="https://www.espn.com",
        news_url="https://www.espn.com/espn/rss/nba/news",
        source="ESPN NBA",
        feed_type="rss",
    ),
    "cbs_nba": SiteConfig(
        key="cbs_nba",
        name="CBS Sports NBA",
        base_url="https://www.cbssports.com",
        news_url="https://www.cbssports.com/rss/headlines/nba/",
        source="CBS Sports NBA",
        feed_type="rss",
    ),
}


def get_rss_site_keys() -> list[str]:
    """返回所有 RSS 类型站点的键。"""
    return [k for k, v in SITE_CONFIGS.items() if v.feed_type == "rss"]


def get_site_config(site_key: str) -> SiteConfig:
    """按站点键获取配置。"""

    try:
        return SITE_CONFIGS[site_key]
    except KeyError as exc:
        raise ConfigurationError(f"不支持的站点: {site_key}") from exc
