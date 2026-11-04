"""时间工具：给模型一个可信的「现在」。"""

from datetime import datetime, timedelta, timezone
from typing import Any

from app.tools.base import BaseTool

# 中国没有夏令时，直接用固定 UTC+8，避免 Windows 上 zoneinfo 找不到时区库。
CHINA_TZ = timezone(timedelta(hours=8), name="CST")
WEEKDAYS = "一二三四五六日"


def format_now(now: datetime | None = None) -> str:
    now = now or datetime.now(CHINA_TZ)
    return f"{now:%Y-%m-%d %H:%M}（UTC+8，星期{WEEKDAYS[now.weekday()]}）"


class TimeTool(BaseTool):
    name = "get_current_time"
    description = (
        "获取当前日期、时间和星期（中国标准时间 UTC+8）。"
        "当用户问现在几点、今天几号、今天星期几，"
        "或者需要把「周五」「明天」换算成具体日期时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def run(self, user_id: int, arguments: dict[str, Any]) -> str:
        return f"当前时间：{format_now()}"
