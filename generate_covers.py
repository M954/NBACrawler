"""推文卡片截图生成器 — 用 Pillow 从推文数据生成精美卡片图。"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 卡片尺寸 (16:9)
CARD_WIDTH = 1200
CARD_HEIGHT = 675
CARD_QUALITY = 85

# 颜色主题
COLORS = {
    "bg": (21, 32, 43),           # Twitter 深色背景
    "card_bg": (30, 39, 50),      # 卡片内区
    "text": (231, 233, 234),      # 主文字白色
    "text_muted": (139, 152, 165),# 次要文字灰
    "accent": (29, 161, 242),     # Twitter 蓝
    "handle": (29, 161, 242),     # @handle 蓝
    "metric_reply": (139, 152, 165),
    "metric_rt": (0, 186, 124),   # 转推绿
    "metric_like": (249, 24, 128),# 红心粉
    "divider": (56, 68, 77),      # 分割线
    "badge_bg": (29, 161, 242),   # 徽章背景
}

# 球队颜色
TEAM_COLORS: dict[str, tuple[int, int, int]] = {
    "Lakers": (85, 37, 130),
    "Warriors": (29, 66, 138),
    "Suns": (29, 17, 96),
    "Bucks": (0, 71, 27),
    "Celtics": (0, 122, 51),
    "76ers": (0, 107, 182),
    "Timberwolves": (12, 35, 64),
    "Thunder": (0, 125, 195),
    "Grizzlies": (93, 118, 164),
    "Cavaliers": (134, 0, 56),
}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """获取字体，优先用系统中文字体。"""
    font_paths = [
        # Windows 中文字体
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑粗体
        "C:/Windows/Fonts/simhei.ttf",     # 黑体
        "C:/Windows/Fonts/segoeui.ttf",    # Segoe UI
        "C:/Windows/Fonts/arial.ttf",      # Arial
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
    ]
    if bold:
        bold_paths = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        font_paths = bold_paths + font_paths

    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """智能换行：先按字符宽度估算，再精确测量。"""
    lines: list[str] = []
    # 粗略估算每行字符数
    avg_char_width = font.getlength("W")
    chars_per_line = max(10, int(max_width / avg_char_width * 1.5))

    for paragraph in text.split("\n"):
        wrapped = textwrap.wrap(paragraph, width=chars_per_line) if paragraph.strip() else [""]
        # 精确测量并二次分割
        for line in wrapped:
            if font.getlength(line) <= max_width:
                lines.append(line)
            else:
                # 逐字符分割
                current = ""
                for ch in line:
                    test = current + ch
                    if font.getlength(test) > max_width:
                        if current:
                            lines.append(current)
                        current = ch
                    else:
                        current = test
                if current:
                    lines.append(current)
    return lines or [""]


def _format_count(n: int) -> str:
    """格式化数字: 1234 → 1.2K, 12345 → 12.3K"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


def _format_time(iso_date: str) -> str:
    """格式化时间。"""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


def generate_tweet_card(tweet: dict, output_path: Path) -> Path | None:
    """为单条推文生成卡片截图。"""
    try:
        img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), COLORS["bg"])
        draw = ImageDraw.Draw(img)

        # 字体
        font_name = _get_font(28, bold=True)
        font_handle = _get_font(22)
        font_content = _get_font(26)
        font_content_cn = _get_font(28)
        font_metric = _get_font(20)
        font_time = _get_font(18)
        font_badge = _get_font(16, bold=True)

        player_name = tweet.get("player_name", "")
        player_handle = tweet.get("player_handle", "")
        content = tweet.get("content", "")
        content_cn = tweet.get("content_cn", "")
        reply_count = tweet.get("reply_count", 0)
        retweet_count = tweet.get("retweet_count", 0)
        like_count = tweet.get("like_count", 0)
        tweet_date = tweet.get("tweet_date", "")
        tweet_type = tweet.get("tweet_type", "original")

        # 内边距
        pad_x = 60
        pad_y = 40
        content_width = CARD_WIDTH - 2 * pad_x

        # ─── 顶部色带 ───
        team = tweet.get("team", "")
        # 查找球队颜色
        accent_color = COLORS["accent"]
        for team_name, color in TEAM_COLORS.items():
            if team_name.lower() in player_name.lower() or team_name.lower() == team.lower():
                accent_color = color
                break

        draw.rectangle([(0, 0), (CARD_WIDTH, 6)], fill=accent_color)

        # ─── 头像占位圆 ───
        avatar_x, avatar_y = pad_x, pad_y + 10
        avatar_r = 30
        draw.ellipse(
            [avatar_x - avatar_r, avatar_y - avatar_r,
             avatar_x + avatar_r, avatar_y + avatar_r],
            fill=accent_color
        )
        # 头像首字母
        initial = player_name[0] if player_name else "?"
        bbox = font_name.getbbox(initial)
        iw = bbox[2] - bbox[0]
        ih = bbox[3] - bbox[1]
        draw.text(
            (avatar_x - iw // 2, avatar_y - ih // 2 - 4),
            initial, fill=(255, 255, 255), font=font_name
        )

        # ─── 名字和 handle ───
        name_x = avatar_x + avatar_r + 20
        draw.text((name_x, avatar_y - avatar_r + 2), player_name, fill=COLORS["text"], font=font_name)
        handle_text = f"@{player_handle}"
        draw.text((name_x, avatar_y + 4), handle_text, fill=COLORS["handle"], font=font_handle)

        # ─── 推文类型徽章 ───
        type_labels = {"original": "原创", "retweet": "转推", "quote": "引用", "reply": "回复"}
        type_label = type_labels.get(tweet_type, tweet_type)
        badge_bbox = font_badge.getbbox(type_label)
        badge_w = badge_bbox[2] - badge_bbox[0] + 16
        badge_h = badge_bbox[3] - badge_bbox[1] + 8
        badge_x = CARD_WIDTH - pad_x - badge_w
        badge_y = pad_y + 10
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=4, fill=COLORS["badge_bg"]
        )
        draw.text((badge_x + 8, badge_y + 2), type_label, fill=(255, 255, 255), font=font_badge)

        # ─── X logo ───
        x_logo = "𝕏"
        try:
            draw.text((CARD_WIDTH - pad_x - 20, pad_y - 5), x_logo, fill=COLORS["text_muted"], font=font_name)
        except Exception:
            pass

        # ─── 分割线 ───
        y_cursor = avatar_y + avatar_r + 20
        draw.line([(pad_x, y_cursor), (CARD_WIDTH - pad_x, y_cursor)], fill=COLORS["divider"], width=1)
        y_cursor += 15

        # ─── 推文内容（中文优先）───
        display_text = content_cn if content_cn else content
        lines = _wrap_text(display_text, font_content_cn, content_width)
        max_content_lines = 6
        for i, line in enumerate(lines[:max_content_lines]):
            draw.text((pad_x, y_cursor), line, fill=COLORS["text"], font=font_content_cn)
            y_cursor += 36
        if len(lines) > max_content_lines:
            draw.text((pad_x, y_cursor), "...", fill=COLORS["text_muted"], font=font_content_cn)
            y_cursor += 36

        # ─── 英文原文（小字） ───
        if content_cn and content:
            y_cursor += 8
            en_lines = _wrap_text(content, font_time, content_width)[:2]
            for line in en_lines:
                draw.text((pad_x, y_cursor), line, fill=COLORS["text_muted"], font=font_time)
                y_cursor += 24

        # ─── 底部区域（固定在卡片底部） ───
        bottom_y = CARD_HEIGHT - 90

        # 分割线
        draw.line([(pad_x, bottom_y), (CARD_WIDTH - pad_x, bottom_y)], fill=COLORS["divider"], width=1)

        # ─── 互动数据 ───
        metric_y = bottom_y + 15
        metrics = [
            ("💬", _format_count(reply_count), COLORS["metric_reply"]),
            ("🔁", _format_count(retweet_count), COLORS["metric_rt"]),
            ("❤️", _format_count(like_count), COLORS["metric_like"]),
        ]

        mx = pad_x
        for icon, count, color in metrics:
            try:
                draw.text((mx, metric_y), icon, fill=color, font=font_metric)
            except Exception:
                pass
            mx += 30
            draw.text((mx, metric_y + 2), count, fill=color, font=font_metric)
            mx += font_metric.getlength(count) + 40

        # ─── 时间 ───
        time_str = _format_time(tweet_date)
        if time_str:
            tw = font_time.getlength(time_str)
            draw.text(
                (CARD_WIDTH - pad_x - tw, metric_y + 4),
                time_str, fill=COLORS["text_muted"], font=font_time
            )

        # ─── 底部品牌 ───
        brand = "Basketball News · Tweet Card"
        bw = font_time.getlength(brand)
        draw.text(
            (CARD_WIDTH - pad_x - bw, CARD_HEIGHT - 30),
            brand, fill=COLORS["divider"], font=font_time
        )

        # 保存
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "JPEG", quality=CARD_QUALITY)
        return output_path

    except Exception as e:
        print(f"  Cover failed [{tweet.get('player_handle')}]: {e}")
        return None


def generate_all_covers(tweets_file: Path | None = None) -> int:
    """为所有推文生成封面卡片。"""
    if tweets_file is None:
        tweets_file = Path(__file__).resolve().parent / "output" / "tweets.json"

    if not tweets_file.exists():
        print(f"Tweets file not found: {tweets_file}")
        return 0

    with open(tweets_file, encoding="utf-8") as f:
        tweets = json.load(f)

    covers_dir = tweets_file.parent / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    for i, tweet in enumerate(tweets):
        tweet_id = tweet.get("tweet_id", f"unknown_{i}")
        output_path = covers_dir / f"{tweet_id}.jpg"

        # 跳过已有
        if output_path.exists() and output_path.stat().st_size > 0:
            tweet["cover_image_path"] = f"covers/{tweet_id}.jpg"
            generated += 1
            continue

        result = generate_tweet_card(tweet, output_path)
        if result:
            tweet["cover_image_path"] = f"covers/{tweet_id}.jpg"
            generated += 1

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{len(tweets)} ({generated} ok)")

    # 更新 tweets.json
    with open(tweets_file, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)

    print(f"Covers done: {generated}/{len(tweets)}")
    return generated


if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    generate_all_covers()
