"""W5 前端：登录、聊天、学习记录、录题、待办、记忆、推送设置。

启动（在 ai-agent 目录）：
    streamlit run ui/app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from ui.api_client import API_BASE, ApiError, request, stream_chat

try:
    from streamlit_cookies_controller import CookieController
except Exception:  # pragma: no cover - 没装 cookie 组件时退化为 session 登录
    CookieController = None

st.set_page_config(page_title="伴学 AI Agent", page_icon="📚", layout="wide")

NAV = ["聊天", "学习记录", "录题", "待办", "记忆", "推送设置"]
COOKIE_NAME = "ai_agent_token"


def cookies():
    """CookieController 内部是自定义组件，不能放进 cache_resource。"""
    if "_cookie_controller" not in st.session_state:
        if CookieController is None:
            st.session_state._cookie_controller = None
        else:
            try:
                st.session_state._cookie_controller = CookieController()
            except Exception:
                st.session_state._cookie_controller = None
    return st.session_state._cookie_controller


def cookie_get(name: str) -> str | None:
    c = cookies()
    if c is None:
        return None
    try:
        return c.get(name)
    except Exception:
        return None


def cookie_set(name: str, value: str) -> None:
    c = cookies()
    if c is None:
        return
    try:
        c.set(name, value, max_age=7 * 24 * 3600)
    except Exception:
        pass


def cookie_remove(name: str) -> None:
    c = cookies()
    if c is None:
        return
    try:
        c.remove(name)
    except Exception:
        pass


def set_auth(data: dict) -> None:
    st.session_state.token = data["access_token"]
    st.session_state.user = data["user"]
    st.session_state.auth_checked = True
    cookie_set(COOKIE_NAME, data["access_token"])
    st.rerun()


def clear_auth() -> None:
    st.session_state.pop("token", None)
    st.session_state.pop("user", None)
    st.session_state.pop("messages", None)
    st.session_state.pop("session_id", None)
    cookie_remove(COOKIE_NAME)
    st.session_state.auth_checked = True
    st.rerun()


def restore_auth() -> None:
    if st.session_state.get("auth_checked"):
        return
    st.session_state.auth_checked = True
    token = st.session_state.get("token") or cookie_get(COOKIE_NAME)
    if not token:
        return
    try:
        user = request("GET", "/api/auth/me", token=token)
    except ApiError:
        cookie_remove(COOKIE_NAME)
        return
    st.session_state.token = token
    st.session_state.user = user


def api_error(exc: ApiError) -> None:
    if exc.status == 401:
        st.warning("登录已过期，请重新登录")
        clear_auth()
    st.error(exc.detail)


def login_page() -> None:
    st.title("📚 伴学 AI Agent")
    st.caption("学习助手 + 生活伴侣 · 本地开发版")
    st.info(f"后端地址：{API_BASE}。如果页面报「连不上后端」，先在另一个终端启动 uvicorn。")

    tab_login, tab_register = st.tabs(["登录", "注册（需要邀请码）"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", type="primary")
        if submitted:
            try:
                data = request(
                    "POST",
                    "/api/auth/login",
                    json_body={"username": username, "password": password},
                )
                set_auth(data)
            except ApiError as exc:
                st.error(exc.detail)

    with tab_register:
        with st.form("register_form"):
            r_username = st.text_input("用户名", help="3–32 位字母、数字、下划线")
            r_display = st.text_input("昵称（可空）")
            r_password = st.text_input("密码", type="password", help="至少 8 位")
            r_invite = st.text_input("邀请码")
            r_submit = st.form_submit_button("注册并登录", type="primary")
        if r_submit:
            try:
                data = request(
                    "POST",
                    "/api/auth/register",
                    json_body={
                        "username": r_username,
                        "display_name": r_display,
                        "password": r_password,
                        "invite_code": r_invite,
                    },
                )
                set_auth(data)
            except ApiError as exc:
                st.error(exc.detail)

    st.divider()
    st.caption("管理员生成邀请码：`python scripts/create_invite.py --uses 1 --days 30`")


def sidebar() -> str:
    with st.sidebar:
        st.title("📚 伴学")
        user = st.session_state.get("user", {})
        st.caption(f"已登录：{user.get('display_name') or user.get('username', '')}")
        st.caption("剩余额度：W6 接入真实统计")
        page = st.radio("导航", NAV, key="nav")
        st.divider()
        if st.button("退出登录", use_container_width=True):
            try:
                request("POST", "/api/auth/logout", token=st.session_state.token)
            except ApiError:
                pass
            clear_auth()
    return page


def _session_options() -> list[dict]:
    try:
        rows = request("GET", "/api/sessions?limit=50", token=st.session_state.token)
        return rows or []
    except ApiError:
        return []


def _load_messages(session_id: int) -> None:
    try:
        data = request(
            "GET", f"/api/sessions/{session_id}/messages", token=st.session_state.token
        )
    except ApiError as exc:
        api_error(exc)
        return
    st.session_state.session_id = session_id
    st.session_state.messages = [
        {"role": item["role"], "content": item["content"]}
        for item in data.get("messages", [])
        if item["role"] in {"user", "assistant"}
    ]
    st.query_params["session_id"] = str(session_id)


def chat_page() -> None:
    st.header("聊天")
    col_mode, col_course = st.columns([1, 2])
    with col_mode:
        mode_label = st.radio("模式", ["学习", "生活"], horizontal=True, key="chat_mode")
    mode = "study" if mode_label == "学习" else "life"
    with col_course:
        course = st.text_input(
            "科目（学习模式）",
            value=st.session_state.get("course", "算法设计与分析"),
            key="course",
            disabled=(mode == "life"),
        )

    sessions = _session_options()
    labels = ["新对话"] + [
        f"#{s['id']} · {s['course'] or '未分类'} · {s['title']}"
        for s in sessions
    ]
    current = st.session_state.get("session_id")
    index = 0
    for i, s in enumerate(sessions, start=1):
        if s["id"] == current:
            index = i
            break
    picked = st.selectbox("历史会话", labels, index=index, key="session_pick")
    if picked != "新对话":
        picked_id = int(picked.split("·")[0].strip().lstrip("#"))
        if picked_id != current:
            _load_messages(picked_id)
    if st.button("＋ 新对话"):
        st.session_state.session_id = None
        st.session_state.messages = []
        if "session_id" in st.query_params:
            del st.query_params["session_id"]
        st.rerun()

    if "messages" not in st.session_state:
        query_id = st.query_params.get("session_id")
        if query_id:
            _load_messages(int(query_id))
        else:
            st.session_state.messages = []

    active_q = st.session_state.get("active_question_id")
    if active_q:
        st.caption(f"当前题目 #{active_q} 已确认；直接提问即可讲解。")
        if st.button("取消当前题目"):
            st.session_state.pop("active_question_id", None)
            st.rerun()

    teaching_labels = ["自动", "给我提示", "继续", "直接看答案"]
    teaching = st.radio("讲解方式", teaching_labels, horizontal=True, key="teaching")
    teaching_stage = {
        "自动": None,
        "给我提示": "hint",
        "继续": "step",
        "直接看答案": "answer",
    }[teaching]

    for msg in st.session_state.messages:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])

    prompt = st.chat_input("说点什么…（学习模式可先录题，再让我提示/讲解）")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    payload = {
        "message": prompt,
        "session_id": st.session_state.get("session_id"),
        "mode": mode,
        "course": course if mode == "study" else None,
        "teaching_stage": teaching_stage,
    }
    if active_q:
        payload["question_id"] = int(active_q)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        status = st.empty()
        text = ""
        try:
            for event in stream_chat(payload, st.session_state.token):
                if event.get("session_id"):
                    st.session_state.session_id = event["session_id"]
                    st.query_params["session_id"] = str(event["session_id"])
                elif event.get("error"):
                    text += f"\n\n⚠️ {event['error']}"
                    placeholder.markdown(text)
                elif event.get("delta"):
                    text += event["delta"]
                    placeholder.markdown(text)
                elif event.get("type") == "tool_call":
                    status.caption(f"正在调用工具：{event.get('name', '')}…")
                elif event.get("type") == "tool_result":
                    status.caption("工具返回了结果，继续整理…")
            status.empty()
            if not text:
                text = "（没有返回内容）"
                placeholder.markdown(text)
        except ApiError as exc:
            if exc.status == 401:
                clear_auth()
            st.error(exc.detail)
            text = text or "请求失败"
    st.session_state.messages.append({"role": "assistant", "content": text})


def history_page() -> None:
    st.header("学习记录")
    col1, col2 = st.columns(2)
    with col1:
        course = st.text_input("按科目筛选（留空=全部）", key="history_course")
    with col2:
        keyword = st.text_input("关键词（标题或消息内容）", key="history_q")
    try:
        params = []
        if course.strip():
            params.append(f"course={course.strip()}")
        if keyword.strip():
            params.append(f"q={keyword.strip()}")
        rows = request(
            "GET",
            "/api/sessions" + (("?" + "&".join(params)) if params else ""),
            token=st.session_state.token,
        )
    except ApiError as exc:
        api_error(exc)
        return

    if not rows:
        st.info("还没有会话。去「聊天」里问第一个问题吧。")
        return

    for row in rows:
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.markdown(f"**#{row['id']} {row['title']}**")
                st.caption(
                    f"{row['course'] or '未分类'} · {row['mode']} · "
                    f"{row['message_count']} 条消息 · {row['updated_at'][:16]}"
                )
            with c2:
                if st.button("打开", key=f"open_{row['id']}"):
                    _load_messages(row["id"])
                    st.session_state.nav = "聊天"
                    st.rerun()
            with c3:
                if st.button("删除", key=f"del_{row['id']}"):
                    try:
                        request(
                            "DELETE",
                            f"/api/sessions/{row['id']}",
                            token=st.session_state.token,
                        )
                        st.rerun()
                    except ApiError as exc:
                        api_error(exc)


def questions_page() -> None:
    st.header("录题")
    course = st.text_input("科目", value="算法设计与分析", key="q_course")
    tab_text, tab_upload = st.tabs(["粘贴文字", "上传 PDF / Word / 图片"])

    with tab_text:
        with st.form("question_text_form"):
            text = st.text_area("题目文字", height=180)
            ok = st.form_submit_button("保存草稿", type="primary")
        if ok:
            try:
                q = request(
                    "POST",
                    "/api/questions/text",
                    token=st.session_state.token,
                    json_body={"text": text, "course": course},
                )
                st.session_state.pending_question = q
                st.rerun()
            except ApiError as exc:
                api_error(exc)

    with tab_upload:
        file = st.file_uploader(
            "选择文件（图片会先 OCR，PDF/Word/PPTX 会抽文字）",
            type=["png", "jpg", "jpeg", "webp", "pdf", "docx", "pptx"],
        )
        if st.button("上传并转写", type="primary"):
            if file is None:
                st.warning("先选一个文件")
            else:
                try:
                    q = request(
                        "POST",
                        "/api/questions/upload",
                        token=st.session_state.token,
                        data={"course": course},
                        files={"file": (file.name, file.getvalue(), file.type)},
                    )
                    st.session_state.pending_question = q
                    st.rerun()
                except ApiError as exc:
                    api_error(exc)

    q = st.session_state.get("pending_question")
    if not q:
        return

    st.subheader(f"确认题目 #{q['id']}（{q['source_type']}）")
    if q.get("source_path") and q["source_type"] == "image":
        try:
            st.image(q["source_path"], caption="原图", width=420)
        except Exception:
            st.caption("原图预览不可用")
    edited = st.text_area("题干（可改错字）", value=q["parsed_text"], height=220)
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("确认题目", type="primary"):
            try:
                updated = request(
                    "POST",
                    f"/api/questions/{q['id']}/confirm",
                    token=st.session_state.token,
                    json_body={"text": edited},
                )
                st.session_state.pending_question = None
                st.session_state.active_question_id = updated["id"]
                st.session_state.nav = "聊天"
                st.rerun()
            except ApiError as exc:
                api_error(exc)
    with c2:
        if st.button("放弃"):
            try:
                request(
                    "DELETE",
                    f"/api/questions/{q['id']}",
                    token=st.session_state.token,
                )
            except ApiError:
                pass
            st.session_state.pending_question = None
            st.rerun()


def todos_page() -> None:
    st.header("待办")
    with st.form("todo_add"):
        title = st.text_input("待办内容")
        c1, c2 = st.columns(2)
        with c1:
            due = st.text_input("截止时间（可空，如 2026-11-06 23:59）")
        with c2:
            remind = st.text_input("提醒时间（可空，默认截止时间）")
        add = st.form_submit_button("添加", type="primary")
    if add and title.strip():
        try:
            request(
                "POST",
                "/api/todos",
                token=st.session_state.token,
                json_body={
                    "title": title.strip(),
                    "due_at": due.strip() or None,
                    "remind_at": remind.strip() or None,
                },
            )
            st.rerun()
        except ApiError as exc:
            api_error(exc)

    status = st.radio("显示", ["pending", "done", "all"], horizontal=True)
    try:
        rows = request(
            "GET", f"/api/todos?status={status}", token=st.session_state.token
        )
    except ApiError as exc:
        api_error(exc)
        return

    if not rows:
        st.info("没有待办。")
        return
    for todo in rows:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 1, 1])
            with c1:
                mark = "✅" if todo["done"] else "○"
                st.markdown(f"{mark} **{todo['title']}**")
                st.caption(
                    f"截止：{todo['due_at'][:16] or '无'} · "
                    f"提醒：{todo['remind_at'][:16] or '无'} · "
                    f"已提醒：{todo['reminded_at'][:16] or '否'}"
                )
            with c2:
                if st.button("恢复" if todo["done"] else "完成", key=f"done_{todo['id']}"):
                    try:
                        request(
                            "PATCH",
                            f"/api/todos/{todo['id']}",
                            token=st.session_state.token,
                            json_body={"done": not todo["done"]},
                        )
                        st.rerun()
                    except ApiError as exc:
                        api_error(exc)
            with c3:
                if st.button("删除", key=f"todo_del_{todo['id']}"):
                    try:
                        request(
                            "DELETE",
                            f"/api/todos/{todo['id']}",
                            token=st.session_state.token,
                        )
                        st.rerun()
                    except ApiError as exc:
                        api_error(exc)


def memories_page() -> None:
    st.header("长期记忆")
    st.caption("这里是我记住的关于你的事；可以手动添加或删除。")
    with st.form("memory_add"):
        content = st.text_input("记住一件事")
        kind = st.selectbox("类型", ["other", "identity", "preference", "plan", "relationship"])
        add = st.form_submit_button("添加", type="primary")
    if add and content.strip():
        try:
            request(
                "POST",
                "/api/memories",
                token=st.session_state.token,
                json_body={"content": content.strip(), "kind": kind},
            )
            st.rerun()
        except ApiError as exc:
            api_error(exc)

    try:
        rows = request("GET", "/api/memories?limit=100", token=st.session_state.token)
    except ApiError as exc:
        api_error(exc)
        return
    if not rows:
        st.info("还没有记忆。")
        return
    for memory in rows:
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f"- **{memory['kind']}**：{memory['content']}")
        with c2:
            if st.button("删除", key=f"mem_{memory['id']}"):
                try:
                    request(
                        "DELETE",
                        f"/api/memories/{memory['id']}",
                        token=st.session_state.token,
                    )
                    st.rerun()
                except ApiError as exc:
                    api_error(exc)


def push_page() -> None:
    st.header("推送设置")
    try:
        state = request("GET", "/api/push/channel", token=st.session_state.token)
    except ApiError as exc:
        api_error(exc)
        return

    if state.get("configured"):
        st.success(
            f"已配置 PushPlus：{state.get('token_masked')}，"
            f"当前{'开启' if state.get('enabled') else '关闭'}"
        )
    else:
        st.info("还没有配置 PushPlus。到 https://www.pushplus.plus/ 微信扫码登录后复制 token。")

    with st.form("push_form"):
        token = st.text_input("PushPlus token", type="password")
        enabled = st.checkbox("启用推送", value=bool(state.get("enabled", True)))
        save = st.form_submit_button("保存", type="primary")
    if save and token.strip():
        try:
            request(
                "PUT",
                "/api/push/channel",
                token=st.session_state.token,
                json_body={"token": token.strip(), "enabled": enabled},
            )
            st.success("已保存")
            st.rerun()
        except ApiError as exc:
            api_error(exc)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("发送测试消息"):
            try:
                request("POST", "/api/push/test", token=st.session_state.token)
                st.success("已发送，请检查微信")
            except ApiError as exc:
                api_error(exc)
    with c2:
        if st.button("删除推送配置"):
            try:
                request("DELETE", "/api/push/channel", token=st.session_state.token)
                st.rerun()
            except ApiError as exc:
                api_error(exc)


def main() -> None:
    restore_auth()
    if not st.session_state.get("token"):
        login_page()
        return

    page = sidebar()
    if page == "聊天":
        chat_page()
    elif page == "学习记录":
        history_page()
    elif page == "录题":
        questions_page()
    elif page == "待办":
        todos_page()
    elif page == "记忆":
        memories_page()
    elif page == "推送设置":
        push_page()


main()
