"""快速演示脚本 — 抓取 RSS 源并展示结果"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

# 修复 Windows 终端 GBK 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config.sites import SITE_CONFIGS, get_rss_site_keys
from config.glossary import POST_TRANSLATION_FIXES
from scraper.rss_scraper import RssScraper


OUTPUT_DIR = Path("output")


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "demo_results.json"

    scraper = RssScraper()
    all_articles: list[dict] = []

    # 抓取所有 RSS 源
    for key in get_rss_site_keys():
        cfg = SITE_CONFIGS[key]
        print(f"INFO 抓取 {cfg.name} ({cfg.news_url}) ...")
        try:
            articles = await scraper.fetch_rss(cfg.news_url, cfg.source)
            articles = articles[:20]
            all_articles.extend(articles)
            print(f"INFO   获取 {len(articles)} 篇文章")
        except Exception as e:
            print(f"WARNING   抓取 {cfg.name} 失败: {e}")

    if not all_articles:
        print("ERROR 未抓取到任何文章")
        return

    # 翻译
    print(f"INFO 开始翻译 {len(all_articles)} 篇文章...")
    try:
        from translator.google_translator import DeepTranslatorBackend
        backend = DeepTranslatorBackend()

        success = 0
        fail = 0
        for i, a in enumerate(all_articles):
            try:
                title_cn = await backend.translate(a.get("title", ""))
                summary_cn = await backend.translate(a.get("summary", ""))
                # 术语后处理
                for wrong, right in POST_TRANSLATION_FIXES.items():
                    title_cn = title_cn.replace(wrong, right)
                    summary_cn = summary_cn.replace(wrong, right)
                a["title_cn"] = title_cn
                a["summary_cn"] = summary_cn
                a["translation_status"] = "completed"
                success += 1
            except Exception as e:
                a["translation_status"] = "failed"
                fail += 1
            if (i + 1) % 10 == 0:
                print(f"INFO 翻译进度: {i + 1}/{len(all_articles)}")
                await asyncio.sleep(1)  # 速率限制
    except Exception as e:
        print(f"ERROR 翻译初始化失败: {e}")
        success, fail = 0, len(all_articles)

    # 保存
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"INFO 完成! 共 {len(all_articles)} 篇, 翻译成功 {success}, 失败 {fail}")
    print(f"INFO 结果已保存到 {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
