"""拍照转写的本地测试：不调用真实 Qwen，只验证压缩和请求组装。"""

import asyncio
from base64 import b64decode
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from app.agent import vision as vision_module
from app.agent.vision import VisionNotConfiguredError, _image_data_url, transcribe_image
from app.config import settings


def test_image_data_url_downscales_to_jpeg(tmp_path) -> None:
    path = tmp_path / "big.png"
    Image.new("RGB", (3000, 1000), "white").save(path, format="PNG")

    data_url = _image_data_url(path)

    assert data_url.startswith("data:image/jpeg;base64,")
    raw = b64decode(data_url.split(",", 1)[1])
    with Image.open(BytesIO(raw)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 1600


def test_vision_client_without_key_is_readable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vision_api_key", "")
    vision_module.get_vision_client.cache_clear()

    try:
        try:
            vision_module.get_vision_client()
        except VisionNotConfiguredError as exc:
            assert "VISION_API_KEY" in str(exc)
        else:
            raise AssertionError("没有 Key 时应该报 VisionNotConfiguredError")
    finally:
        vision_module.get_vision_client.cache_clear()


def test_transcribe_image_builds_openai_vision_request(monkeypatch, tmp_path) -> None:
    path = tmp_path / "question.png"
    Image.new("RGB", (200, 80), "white").save(path, format="PNG")
    captured: dict = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="1. 0-1 背包的状态转移方程是 $f[i][j]=...$")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(vision_module, "get_vision_client", lambda: FakeClient())

    text = asyncio.run(transcribe_image(path))

    assert "状态转移方程" in text
    assert captured["model"] == settings.vision_model
    content = captured["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
