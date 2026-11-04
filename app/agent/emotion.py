"""轻量情绪识别：用关键词给一个「可能的情绪标签」，不替代专业判断。

标签只用于提示模型「先接住情绪」，不直接展示给用户，也不做诊断。
"""

from __future__ import annotations

EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "焦虑": ("焦虑", "紧张", "担心", "害怕", "慌", "压力大", "睡不着", "心慌"),
    "难过": ("难过", "伤心", "想哭", "失落", "委屈", "崩溃", "难受", "低落"),
    "生气": ("生气", "愤怒", "气死", "烦死", "火大", "讨厌", "恶心"),
    "疲惫": ("累", "疲惫", "没力气", "困", "熬不动", "撑不住", " burnout"),
    "开心": ("开心", "高兴", "太好了", "兴奋", "快乐", "爽", "幸福"),
}

EMOTION_LABELS = {
    "焦虑": "焦虑/紧张",
    "难过": "难过/低落",
    "生气": "生气/烦躁",
    "疲惫": "疲惫",
    "开心": "开心",
    "neutral": "平静/未明显表露",
}


def detect_emotion(text: str) -> str:
    """返回中文情绪键；没命中就返回 neutral。"""
    value = (text or "").strip().lower()
    if not value:
        return "neutral"

    scores: dict[str, int] = {}
    for emotion, words in EMOTION_KEYWORDS.items():
        hits = sum(1 for word in words if word in value)
        if hits:
            scores[emotion] = hits
    if not scores:
        return "neutral"
    return max(scores, key=scores.get)


def emotion_hint(emotion: str) -> str:
    label = EMOTION_LABELS.get(emotion, EMOTION_LABELS["neutral"])
    if emotion == "neutral":
        return (
            f"用户当前情绪可能：{label}。先按普通聊天回应；如果对方明显在倾诉，"
            "先听完，不要急着给方案。"
        )
    return (
        f"用户当前情绪可能：{label}。先接住情绪（一句话即可），再决定要不要给建议；"
        "不要用「你应该」开头，也不要说「我完全理解你」。"
    )
