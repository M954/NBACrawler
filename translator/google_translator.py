"""deep-translator 适配层。"""

from __future__ import annotations

import asyncio

from deep_translator import GoogleTranslator

from config.glossary import POST_TRANSLATION_FIXES
from utils.exceptions import TranslationError


class DeepTranslatorBackend:
    """GoogleTranslator 的项目内适配器。"""

    def __init__(self, source_language: str = "en", target_language: str = "zh-CN") -> None:
        self._translator = GoogleTranslator(
            source=source_language,
            target=target_language,
        )

    def _apply_glossary(self, text: str) -> str:
        """后处理：将机翻常见错误替换为正确的篮球术语。"""

        for wrong, correct in POST_TRANSLATION_FIXES.items():
            text = text.replace(wrong, correct)
        return text

    async def translate(self, text: str) -> str:
        """翻译文本，并应用术语词典后处理。"""

        if not text or not text.strip():
            raise TranslationError("空文本不应送入翻译后端")
        try:
            result = await asyncio.to_thread(self._translator.translate, text)
            return self._apply_glossary(result)
        except Exception as exc:
            raise TranslationError("翻译失败") from exc
