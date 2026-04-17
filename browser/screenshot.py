"""推文截图服务 — 协议与 Playwright 实现。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# 截图标准尺寸（Twitter Card 16:9 比例）
SCREENSHOT_WIDTH = 1200
SCREENSHOT_HEIGHT = 675
SCREENSHOT_QUALITY = 80


class ScreenshotService(Protocol):
    """推文截图协议。"""

    async def capture(
        self,
        url: str,
        selector: str,
        output_path: Path,
        timeout: float = 15000,
    ) -> Path | None:
        """截取页面指定元素的截图，返回保存路径或 None。"""


class PlaywrightScreenshot:
    """使用 Playwright 截取推文截图。"""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._browser = None
        self._context = None

    async def _ensure_browser(self):
        """懒初始化浏览器（复用单个 context）。"""
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self._headless,
                channel="msedge",
            )
            self._context = await self._browser.new_context(
                viewport={"width": SCREENSHOT_WIDTH, "height": SCREENSHOT_HEIGHT},
                locale="en-US",
            )
        except Exception as exc:
            logger.error("Playwright 浏览器初始化失败: %s", exc)
            raise

    async def capture(
        self,
        url: str,
        selector: str,
        output_path: Path,
        timeout: float = 15000,
    ) -> Path | None:
        """截取推文元素截图并保存为 JPEG。"""

        # 缓存检查：文件已存在则跳过
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info("截图缓存命中: %s", output_path.name)
            return output_path

        try:
            await self._ensure_browser()
            page = await self._context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout)
                await page.wait_for_selector(selector, timeout=timeout / 2)

                element = await page.query_selector(selector)
                if element is None:
                    logger.warning("未找到截图元素 '%s' @ %s", selector, url)
                    return None

                output_path.parent.mkdir(parents=True, exist_ok=True)

                # 使用 JPEG 格式，质量 80%，控制文件大小
                await element.screenshot(
                    path=str(output_path),
                    type="jpeg",
                    quality=SCREENSHOT_QUALITY,
                )

                logger.info("截图保存: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
                return output_path

            finally:
                await page.close()

        except Exception as exc:
            logger.warning("截图失败 %s: %s", url, exc)
            return None

    async def close(self) -> None:
        """关闭浏览器实例。"""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()
            self._pw = None


class StubScreenshot:
    """测试用截图桩实现。"""

    async def capture(
        self,
        url: str,
        selector: str,
        output_path: Path,
        timeout: float = 15000,
    ) -> Path | None:
        """返回 None，不实际截图。"""
        return None
