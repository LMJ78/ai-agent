"""轻量情绪识别：只测标签和提示词，不测模型回答。"""

from app.agent.emotion import detect_emotion, emotion_hint


def test_detect_emotion_hits_common_labels() -> None:
    assert detect_emotion("明天考试，我好焦虑，睡不着") == "焦虑"
    assert detect_emotion("今天真的很难过，想哭") == "难过"
    assert detect_emotion("气死我了，怎么又这样") == "生气"
    assert detect_emotion("最近好累，撑不住") == "疲惫"
    assert detect_emotion("终于做完了，太开心了") == "开心"
    assert detect_emotion("今天食堂的饭还行") == "neutral"


def test_emotion_hint_asks_to_listen_first() -> None:
    text = emotion_hint("焦虑")
    assert "焦虑" in text
    assert "先接住" in text
    assert "不要用「你应该」" in text
    assert "平静" in emotion_hint("neutral")
