"""RSS/Atom Feed 爬虫模块。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
import re

import httpx

from utils.headers import HeaderProvider


class RssScraper:
    """抓取并解析 RSS/Atom feed。"""

    def __init__(self) -> None:
        self._headers = HeaderProvider()

    async def fetch_rss(self, url: str, source: str, timeout: float = 30.0) -> list[dict]:
        """获取并解析 RSS feed，返回文章字典列表。"""
        async with httpx.AsyncClient(
            headers=self._headers.get_headers(),
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            xml_text = resp.text

        return self._parse_rss(xml_text, source, url)

    def _parse_rss(self, xml_text: str, source: str, feed_url: str) -> list[dict]:
        """解析 RSS/Atom XML 为文章列表。"""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise ValueError(f"RSS 解析失败: {feed_url} -> {e}") from e

        # 检测 Atom 或 RSS 2.0
        ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/",
              "content": "http://purl.org/rss/1.0/modules/content/"}

        articles: list[dict] = []

        if root.tag == "{http://www.w3.org/2005/Atom}feed" or root.tag == "feed":
            # Atom 格式
            for entry in root.findall("atom:entry", ns) or root.findall("entry"):
                articles.append(self._parse_atom_entry(entry, ns, source))
        else:
            # RSS 2.0
            channel = root.find("channel")
            if channel is None:
                return articles
            for item in channel.findall("item"):
                articles.append(self._parse_rss_item(item, ns, source))

        return [a for a in articles if a.get("title")]

    def _parse_rss_item(self, item: ET.Element, ns: dict, source: str) -> dict:
        """解析单个 RSS 2.0 <item>。"""
        title = self._text(item, "title")
        link = self._text(item, "link") or self._text(item, "guid")
        summary = self._text(item, "description") or ""
        summary = self._strip_html(summary)[:500]
        author = (self._text(item, "dc:creator", ns)
                  or self._text(item, "author")
                  or self._text(item, "managingEditor"))
        pub_date = self._text(item, "pubDate")

        # 提取 tags
        tags = [c.text.strip() for c in item.findall("category") if c.text]

        now = datetime.now(timezone.utc).isoformat()
        return {
            "title": title or "",
            "title_cn": "",
            "summary": summary,
            "summary_cn": "",
            "author": author,
            "publish_date": pub_date or "",
            "url": link or "",
            "source": source,
            "tags": tags,
            "scraped_at": now,
            "translation_status": "pending",
        }

    def _parse_atom_entry(self, entry: ET.Element, ns: dict, source: str) -> dict:
        """解析单个 Atom <entry>。"""
        title = self._text(entry, "title") or self._text(entry, "atom:title", ns)
        link_el = entry.find("link")
        link = link_el.get("href", "") if link_el is not None else ""
        summary = (self._text(entry, "summary") or self._text(entry, "content") or "")
        summary = self._strip_html(summary)[:500]
        author_el = entry.find("author")
        author = None
        if author_el is not None:
            author = self._text(author_el, "name")
        pub_date = self._text(entry, "published") or self._text(entry, "updated")

        tags = [c.get("term", "").strip() for c in entry.findall("category") if c.get("term")]

        now = datetime.now(timezone.utc).isoformat()
        return {
            "title": title or "",
            "title_cn": "",
            "summary": summary,
            "summary_cn": "",
            "author": author,
            "publish_date": pub_date or "",
            "url": link,
            "source": source,
            "tags": tags,
            "scraped_at": now,
            "translation_status": "pending",
        }

    @staticmethod
    def _text(el: ET.Element, tag: str, ns: dict | None = None) -> str | None:
        """安全提取子元素文本。"""
        child = el.find(tag, ns) if ns else el.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None

    @staticmethod
    def _strip_html(text: str) -> str:
        """移除 HTML 标签并解码实体。"""
        text = unescape(text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
