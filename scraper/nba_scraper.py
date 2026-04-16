"""NBA 新闻列表爬虫。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from models.article import Article
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class NbaScraper(BaseScraper):
    """NBA News 列表页解析器。"""

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _extract_from_json_ld(self, soup: BeautifulSoup) -> list[Article]:
        articles: list[Article] = []
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.get_text(strip=True))
            except json.JSONDecodeError:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") not in {"NewsArticle", "Article"}:
                    continue
                title = str(item.get("headline", "")).strip()
                url = str(item.get("url", "")).strip()
                if not title or not url:
                    continue
                author_data = item.get("author")
                author: str | None = None
                if isinstance(author_data, dict):
                    author = author_data.get("name")
                elif isinstance(author_data, list) and author_data:
                    first = author_data[0]
                    if isinstance(first, dict):
                        author = first.get("name")
                articles.append(
                    Article(
                        title=title,
                        summary=item.get("description"),
                        author=author,
                        publish_date=self._parse_datetime(item.get("datePublished")),
                        url=urljoin(self.site_config.base_url, url),
                        source=self.site_config.source,
                        tags=[],
                    )
                )
        return articles

    def _extract_from_cards(self, soup: BeautifulSoup) -> list[Article]:
        selectors = self.site_config.selectors
        articles: list[Article] = []
        seen_urls: set[str] = set()

        for node in soup.select(selectors.item):
            if not isinstance(node, Tag):
                continue
            try:
                link_node = node.select_one(selectors.link)
                title_node = node.select_one(selectors.title)
                if title_node is None and link_node is not None:
                    title_node = link_node

                title = title_node.get_text(" ", strip=True) if title_node else ""
                href = link_node.get("href") if link_node else None
                url = urljoin(self.site_config.base_url, href or "")

                if not title or not href or "/news/" not in url:
                    continue
                if url in seen_urls:
                    continue

                summary_node = node.select_one(selectors.summary)
                author_node = node.select_one(selectors.author)
                time_node = node.select_one(selectors.publish_time)
                tag_nodes = node.select(selectors.tags)

                articles.append(
                    Article(
                        title=title,
                        summary=summary_node.get_text(" ", strip=True)
                        if summary_node
                        else None,
                        author=author_node.get_text(" ", strip=True)
                        if author_node
                        else None,
                        publish_date=self._parse_datetime(
                            (time_node.get("datetime") if time_node else None)
                            or (time_node.get_text(" ", strip=True) if time_node else None)
                        ),
                        url=url,
                        source=self.site_config.source,
                        tags=[item.get_text(" ", strip=True) for item in tag_nodes],
                    )
                )
                seen_urls.add(url)
            except Exception as exc:
                logger.warning("解析单条 NBA 卡片失败: %s", exc)

        return articles

    def parse_articles(self, html: str) -> list[Article]:
        """解析列表页。"""

        soup = BeautifulSoup(html, "lxml")
        json_ld_articles = self._extract_from_json_ld(soup)
        if json_ld_articles:
            return json_ld_articles
        articles = self._extract_from_cards(soup)
        logger.info("解析得到 %s 篇 NBA 文章", len(articles))
        return articles
