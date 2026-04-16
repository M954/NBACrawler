"""推文情绪检测工具 — 共享模块。"""


def detect_mood(content: str) -> str:
    """根据推文内容检测音乐氛围：hype/emotional/chill。"""
    content_lower = content.lower()
    hype_words = [
        "🔥", "💪", "!!!", "went off", "career-high", "career high", "erupts",
        "monster", "let's go", "bang", "poster", "dunk", "😤", "🤯",
        "walk-off", "bomb", "insane", "crazy", "30 pts", "40 pts", "50 pts",
        "triple-double", "record", "first", "history",
    ]
    emotional_words = [
        "pray", "🙏", "rip", "love", "blessed", "heart", "miss",
        "❤️", "family", "grateful", "peace", "tribute", "honor",
        "rest in peace", "thoughts", "condolences",
    ]

    if any(w in content_lower for w in hype_words):
        return "hype"
    if any(w in content_lower for w in emotional_words):
        return "emotional"
    return "chill"
