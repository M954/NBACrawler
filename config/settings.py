"""项目配置对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) "
    "Gecko/20100101 Firefox/123.0",
)

DEFAULT_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


@dataclass(frozen=True)
class RetrySettings:
    """HTTP 重试设置。"""

    max_attempts: int = 3
    retry_status_codes: tuple[int, ...] = (429, 503)
    backoff_base_seconds: float = 1.0


@dataclass(frozen=True)
class TranslationSettings:
    """翻译设置。"""

    source_language: str = "en"
    target_language: str = "zh-CN"


@dataclass(frozen=True)
class CrawlerSettings:
    """爬虫运行设置。"""

    request_timeout: float = 20.0
    request_delay_min: float = 1.0
    request_delay_max: float = 3.0
    max_requests_per_minute: int = 10
    default_limit: int = 10
    user_agents: tuple[str, ...] = DEFAULT_USER_AGENTS
    default_headers: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_HEADERS)
    )
    retry: RetrySettings = field(default_factory=RetrySettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")

    @property
    def json_output_path(self) -> Path:
        """JSON 默认输出路径。"""

        return self.output_dir / "articles.json"

    @property
    def sqlite_output_path(self) -> Path:
        """SQLite 默认输出路径。"""

        return self.output_dir / "articles.db"


def get_settings() -> CrawlerSettings:
    """返回默认配置对象。"""

    return CrawlerSettings()


# ============================================================
# 模块级别兼容变量 — 供各模块直接 import
# ============================================================
_settings = get_settings()

MAX_RETRIES: int = _settings.retry.max_attempts
RETRY_STATUS_CODES: tuple[int, ...] = _settings.retry.retry_status_codes

TRANSLATION_SOURCE_LANG: str = _settings.translation.source_language
TRANSLATION_TARGET_LANG: str = _settings.translation.target_language
TRANSLATION_DELAY: float = 0.5

OUTPUT_DIR: Path = _settings.output_dir
SQLITE_DB_PATH: Path = _settings.sqlite_output_path

LOG_DIR: Path = PROJECT_ROOT / "logs"
LOG_LEVEL: str = "INFO"
LOG_ROTATION: str = "10 MB"
LOG_RETENTION: str = "7 days"
