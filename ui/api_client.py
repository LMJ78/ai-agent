"""Streamlit 调 FastAPI 的小客户端。"""

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("detail"):
            return str(data["detail"])
    except ValueError:
        pass
    return resp.text[:300] or f"HTTP {resp.status_code}"


def request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.request(
                method,
                f"{API_BASE}{path}",
                headers=headers,
                json=json_body,
                data=data,
                files=files,
            )
    except httpx.RequestError as exc:
        raise ApiError(0, f"连不上后端（{API_BASE}），请先启动 uvicorn") from exc

    if resp.status_code >= 400:
        raise ApiError(resp.status_code, _detail(resp))
    if not resp.content:
        return None
    return resp.json()


def stream_chat(payload: dict, token: str) -> Iterator[dict]:
    """逐条解析 /api/chat 的 SSE；调用方按 type/delta 处理。"""
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            with client.stream(
                "POST", f"{API_BASE}/api/chat", headers=headers, json=payload
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise ApiError(resp.status_code, _detail(resp))
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        return
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue
    except httpx.RequestError as exc:
        raise ApiError(0, f"连不上后端（{API_BASE}），请检查 uvicorn 是否在运行") from exc
