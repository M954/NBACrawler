"""项目异常定义。"""


class ProjectError(Exception):
    """项目基础异常。"""


class ConfigurationError(ProjectError):
    """配置异常。"""


class ValidationError(ProjectError):
    """数据校验异常。"""


class ScraperError(ProjectError):
    """抓取异常。"""


class FetchError(ScraperError):
    """网络抓取异常。"""


class ParseError(ScraperError):
    """解析异常。"""


class RobotsDeniedError(ScraperError):
    """robots 拒绝异常。"""


class TranslationError(ProjectError):
    """翻译异常。"""


class StorageError(ProjectError):
    """存储异常。"""


class BrowserError(ProjectError):
    """浏览器接口异常。"""
