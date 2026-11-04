"""PushPlus 微信推送：一个用户一个 token，服务端不保存明文到日志。"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PushChannel

PUSHPLUS_URL = "https://www.pushplus.plus/send"


class PushError(Exception):
    """推送失败，调用方可以把 message 直接展示给用户。"""


class PushNotConfiguredError(PushError):
    """用户还没配置推送通道；这不是故障，调度器应跳过。"""


def mask_token(token: str) -> str:
    value = (token or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def get_channel(db: Session, user_id: int) -> PushChannel | None:
    return db.scalar(
        select(PushChannel).where(
            PushChannel.user_id == user_id,
            PushChannel.provider == "pushplus",
        )
    )


def upsert_channel(db: Session, user_id: int, token: str, enabled: bool = True) -> PushChannel:
    token = token.strip()
    if not token:
        raise ValueError("PushPlus token 不能为空")

    channel = get_channel(db, user_id)
    if channel is None:
        channel = PushChannel(user_id=user_id, provider="pushplus", token=token, enabled=enabled)
        db.add(channel)
    else:
        channel.token = token
        channel.enabled = enabled
    db.commit()
    db.refresh(channel)
    return channel


def delete_channel(db: Session, user_id: int) -> bool:
    channel = get_channel(db, user_id)
    if channel is None:
        return False
    db.delete(channel)
    db.commit()
    return True


async def send_pushplus(
    token: str,
    title: str,
    content: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """发一条 PushPlus；失败抛 PushError，不把 token 写进错误信息。"""
    token = (token or "").strip()
    if not token:
        raise PushNotConfiguredError("还没有配置 PushPlus token")

    payload = {
        "token": token,
        "title": title[:100],
        "content": content[:2000],
        "template": "txt",
    }

    async def _send(http: httpx.AsyncClient) -> dict[str, Any]:
        try:
            response = await http.post(PUSHPLUS_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise PushError("推送超时，检查手机网络或稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            raise PushError(f"PushPlus 返回 HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise PushError("连不上 PushPlus，检查网络后重试") from exc

        if int(data.get("code", 0)) != 200:
            message = str(data.get("msg") or data.get("message") or "PushPlus 返回失败")
            raise PushError(f"PushPlus：{message}")
        return data

    if client is not None:
        return await _send(client)

    async with httpx.AsyncClient(timeout=15) as http:
        return await _send(http)


async def send_to_user(
    db: Session, user_id: int, title: str, content: str
) -> dict[str, Any]:
    channel = get_channel(db, user_id)
    if channel is None or not channel.enabled or not channel.token:
        raise PushNotConfiguredError("这个用户还没有配置可用的 PushPlus 通道")
    return await send_pushplus(channel.token, title, content)
