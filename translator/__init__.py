"""翻译导出。"""

from .base import ArticleTranslator, TranslatorBackend
from .google_translator import DeepTranslatorBackend

__all__ = ["ArticleTranslator", "TranslatorBackend", "DeepTranslatorBackend"]
