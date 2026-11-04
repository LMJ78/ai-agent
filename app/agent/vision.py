"""拍照讲题的视觉转写。

只做一件事：把图片里的题目文字转成可编辑文本，**不解答**。
用户确认转写结果后，再走正常的讲题流程。

视觉模型走阿里云百炼的 OpenAI 兼容接口（默认 qwen3-vl-plus）。
没有配置 Key 时，图片接口返回 503；文字/PDF/PPTX 不受影响。
"""

from base64 import b64encode
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from openai import AsyncOpenAI
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings


class VisionNotConfiguredError(RuntimeError):
    """没填视觉 Key。"""


class VisionError(RuntimeError):
    """图片读不了，或模型没有返回可用文字。"""


VISION_PROMPT = """你是一个题目转写助手。只转写图片里可见的题目文字，不要解答，不要总结。
要求：
1. 保留题号、题干、选项、单位、上下标；
2. 数学公式用 LaTeX，行内公式用 $...$；
3. 图片模糊或看不清的地方写 [看不清]，不要猜；
4. 只输出转写结果，不要加“以下是题目”之类的说明。"""


@lru_cache
def get_vision_client() -> AsyncOpenAI:
    key = settings.vision_api_key.strip()
    if not key or key.startswith("sk-xxx"):
        raise VisionNotConfiguredError(
            "还没有配置 VISION_API_KEY：在 .env 里填入阿里云百炼的 Key 后重启。"
            "文字、PDF、PPTX 题目不受影响，只有拍照需要它。"
        )
    return AsyncOpenAI(
        api_key=key,
        base_url=settings.vision_base_url,
        timeout=60.0,
        max_retries=1,
    )


def _image_data_url(path: Path) -> str:
    """压到最长边 1600px、JPEG 85，控制上传体积和 token。"""
    try:
        with Image.open(path) as image:
            # 手机照片常带 EXIF 旋转信息，先转正再压缩，避免模型看到横着的题。
            rgb = ImageOps.exif_transpose(image).convert("RGB")
            rgb.thumbnail((1600, 1600))
            buffer = BytesIO()
            rgb.save(buffer, format="JPEG", quality=85, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise VisionError("这张图片打不开，请换 JPG/PNG 再试") from exc

    encoded = b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _clean_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def transcribe_image(path: Path) -> str:
    """调用视觉模型，返回图片里的题目文字。"""
    client = get_vision_client()
    data_url = _image_data_url(path)

    try:
        response = await client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=2000,
        )
    except Exception as exc:  # noqa: BLE001 - 统一转成可读的 502
        raise VisionError(f"视觉模型调用失败：{exc}") from exc

    text = _clean_text(response.choices[0].message.content or "")
    if not text:
        raise VisionError("没有从图片里识别出文字，请拍清楚一点或换一张图")
    return text
