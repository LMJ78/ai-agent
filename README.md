# 伴学 · AI Agent

一个面向大学生的 AI Agent：**学习助手 + 生活伴侣**。

当前进度：**V3 前端 MVP（React）+ 扫描版 PDF OCR + 历史体验优化**。
本阶段目标：邀请码注册、JWT 登录、所有接口按用户隔离；React 前端能登录、聊天、按科目/模式看历史、折叠侧边栏、删除历史、管知识库/题库；扫描版 PDF 上传后自动逐页 OCR 入库。

---

## 已经实现

| 能力 | 说明 |
|---|---|
| `GET /health` | 健康检查，会真的查一次数据库 |
| 注册 / 登录 | `POST /api/auth/register`（必须邀请码）/ `POST /api/auth/login`，bcrypt + JWT 7 天 |
| 用户隔离 | 所有业务接口都从 `Authorization: Bearer <token>` 取当前用户；A 的会话/题目给 B → 404 |
| 邀请码 | `scripts/create_invite.py` 生成一次性/多次邀请码 |
| React 前端 | `web/`：登录/注册、聊天、按科目分组历史、知识库、题库；学习/生活双主题；侧边栏可折叠；历史按学习/生活模式隔离、支持删除；原 Streamlit 保留在 `ui/` 作旧入口 |
| `POST /api/chat` | 对话接口，SSE 返回 |
| 工具循环 | 模型要调工具 → 执行 → 结果回填 → 再问，最多 5 轮 |
| 六个工具 | 时间、计算器、待办、`search_notes`（课程资料检索）、`web_search`（Tavily 联网检索）、`memory`（长期记忆） |
| 课程资料 | 上传 PDF / DOCX / PPTX / MD / TXT，解析后存入 `chunks` 表；扫描版 PDF 自动逐页 OCR |
| 扫描版 PDF OCR | 文字层为空时用 pypdfium2 渲染页面，Qwen-VL 逐页转写；默认最多 80 页、150 DPI |
| 本地检索 | BM25 + 中文二元组分词；按 `user_id` / `course` 隔离，回答带 `[L1]` 出处 |
| 科目维度 | 每个会话绑定一个 `course`；检索默认只查这门课，不再把不同科目混在一起 |
| 学习记录 | `GET /api/sessions?course=...&mode=study|life` 按科目/模式列会话，`?q=...` 按关键词搜历史；`DELETE` 删除会话时题目保留在题库 |
| 题目入口 | 粘贴文字、上传 PDF/Word/PPTX、拍照；先存 `draft`，确认/改错后变 `confirmed` |
| 拍照转写 | Qwen-VL 只做「图 → 文字 + LaTeX」，不解答；图片压缩到长边 1600px |
| 题目讲解 | `POST /api/chat` 带 `question_id`；未确认的题接口层直接 409 |
| 解题节奏 | 默认只给提示；说「继续」给下一步；说「直接看答案」才给完整解答 |
| 生活模式 | 情绪标签 + 温和人格；先接住情绪，不诊断、不说教 |
| 长期记忆 | 记住/查看/搜索/删除；「记住…」会兜底落库；按 `user_id` 隔离，不串人 |
| 待办提醒 | 加 `remind_at`，支持今天/本周；后台每 30 秒扫描到点待办 |
| 手机推送 | PushPlus token 配置、测试发送；失败重试 3 次，成功写 `reminded_at` 去重 |
| L3 自测 | 按课程/章节出 1–10 道选择题，提交后判分 + 解析 + `[L]` 出处 |
| 联网检索 | 本地课件没覆盖时调用 `web_search`（Tavily），回答带 `[W1]` 出处；本地优先，冲突以课件为准 |
| 批量导入 | `scripts/ingest_course.py` 导入 ch01–ch10 课件，优先 PPTX |
| 扩展自检 | `scripts/check_w3_extras.py` 检查拍照/联网 Key，并可真实跑一张图/一次搜索 |
| W3 验收 | `scripts/w3_acceptance.py` 生成 10 张印刷体题目截图、跑 6 个问题，报告写到 `data/acceptance/w3_report.md` |
| 工具 trace | SSE 里会发 `tool_call` / `tool_result` 事件 |
| 会话与消息落库 | `chat_sessions` / `messages`，都带 `user_id` |
| 友好错误 | 没配 Key 返回 503；工具报错转成文本，不崩整个请求 |
| 测试 | 59 个用例：健康检查、流式落库、工具循环、计算器、待办、RAG、上传/删除、学习记录、题目确认、解题阶段、自测判分、联网检索、图片压缩、扫描 PDF OCR、情绪、记忆、推送、提醒、注册登录、邀请码、越权隔离 |

> 已在 Python 3.14 + FastAPI 0.162 下验证：59 个测试全过；ch01–ch03 共 18 份课件已入库（390 个 chunk），真实提问「0-1 背包的状态转移方程」会先调 `search_notes`，回答带 `[L3]` 引用；真实 DeepSeek 已能按 ch03 出 2 道自测题。
>
> V3 前端已用 React + Vite 重写；扫描版 PDF 已用 PIL 生成的图片型 PDF 跑通真实 OCR（1 页入库）。W5 的邀请码、JWT、用户隔离；W3 的拍照与联网验收仍有效：10 张印刷体截图 **10/10 可读**，6 个问题 **6/6 通过**，本地 `[L]` 引用 **4/4**。

---

## 快速开始

### 0. 准备

- Python 3.11+（3.14 也可以）
- Git（提交代码用；没装也能先跑，安装方法见文末「附录：安装 Git」）

### 1. 创建虚拟环境并安装依赖

> 下面的命令都在 **Windows PowerShell** 里执行（不是 cmd，也不是 Git Bash）。

```powershell
# 先进入项目目录（requirements-dev.txt 在这里）
cd "C:\Users\梁明健\Desktop\deepseek harness 工作区\ai-agent开发工作区\ai-agent"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

> 这里**不用** `pip install -e .`。项目直接在当前目录运行，不需要安装成包；
> 用 `requirements-dev.txt` 还能避开 setuptools 构建依赖的问题。

激活成功后，提示符前面会多出 `(.venv)`。如果没看到，就说明没激活成功。

如果 PowerShell 提示「禁止运行脚本」：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

然后再执行一次 `.\.venv\Scripts\Activate.ps1`。

**不想激活也可以**，直接调用 venv 里的 Python，效果一样：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

后面所有 `python`、`pip`、`uvicorn` 命令，都可以用
`.\.venv\Scripts\python.exe -m ...` 代替，例如：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

macOS / Linux 才用下面这段（Windows 不要用）：

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. 配置密钥

```powershell
copy .env.example .env
```

打开 `.env`，把 `DEEPSEEK_API_KEY` 换成真实 Key。没有 Key 时服务也能启动，只是 `/api/chat` 会返回 503。

> 注意：Key 必须是 **DeepSeek 开放平台**（platform.deepseek.com）创建的，不是阿里云百炼/Qwen 的 Key。
> 本地开发时项目会优先读 `.env`，即使系统里还残留旧的 `DEEPSEEK_API_KEY` 也不会覆盖它。

拍照讲题另外需要 `VISION_API_KEY`（阿里云百炼 Qwen-VL）。不填也能启动，只是上传图片会返回 503；文字/PDF/PPTX 正常。

联网检索需要 `TAVILY_API_KEY`（<https://app.tavily.com> 注册后创建，免费额度够用）。不填也能启动，只是模型调用 `web_search` 时会收到「未配置」提示，本地 `search_notes` 照常工作。

### 3. 启动

```powershell
uvicorn app.main:app --reload
```

> 这个窗口会一直被服务占用，**不要关，也不要在里面按 Ctrl+C**。
> 看到 `Uvicorn running on http://127.0.0.1:8000` 就说明启动成功。
> 下面的第 4 步请**另开一个 PowerShell 窗口**执行。

打开：

- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

### 3.5 注册、登录与 React 前端

**先生成一个邀请码**（另开一个窗口，在 `ai-agent` 目录下）：

```powershell
.\.venv\Scripts\python.exe scripts\create_invite.py --uses 1 --days 30 --note "算法班同学"
```

把输出的 `AI-XXXXXXXX` 填进注册表单。用 PowerShell 注册并拿到 token：

```powershell
$body = @{
  username = "yourname"
  password = "password123"
  display_name = "你的昵称"
  invite_code = "AI-XXXXXXXX"
} | ConvertTo-Json -Compress
$login = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/register" `
  -Method Post -ContentType "application/json; charset=utf-8" -Body $body
$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }
```

之后所有 `/api/*` 业务接口都要带 `-Headers $headers`。没带或 token 过期会返回 **401**。

**启动 React 前端**（再开一个窗口，进入 `web/`）：

```powershell
cd web
pnpm install
pnpm dev
```

浏览器打开 <http://127.0.0.1:5173>。用刚才注册的账号登录；token 存在 localStorage，刷新不会掉登录。
页面：聊天、按科目分组的会话历史、知识库、题库；右上角切换学习/生活模式。侧栏可折叠；历史只显示当前模式；会话右侧垃圾桶可删除（题目会保留在题库）。

> `pnpm dev` 会把 `/api` 和 `/health` 代理到 `http://127.0.0.1:8000`，所以先启动后端。
> 生产构建：`pnpm build`，产物在 `web/dist/`。
>
> 旧 Streamlit 入口仍在 `ui/app.py`，命令是
> `.\.venv\Scripts\python.exe -m streamlit run ui/app.py`（8501），仅作兼容保留。

### 4. 试一次对话

> W5 起所有 `/api/*` 都要登录。下面的 `Invoke-RestMethod` 请加上 `-Headers $headers`；
> `curl.exe` 请加 `-H "Authorization: Bearer <token>"`。`$headers` 怎么来见 3.5。

新开一个 PowerShell 窗口（不需要激活 venv）。

Windows PowerShell 5.1 对 JSON 引号非常敏感，先用手头最稳的方式验证接口：

```powershell
$body = @{ message = "用一句话解释什么是递归"; mode = "study" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body $body -Headers $headers
```

> 它会等模型答完一次性返回（不是逐字流式），但能确认整条链路是通的。

想逐字看流式输出，用 `curl.exe`，并在前面加 `--%`，让 PowerShell 原样传参、不要动引号：

```powershell
curl.exe --% -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d "{\"message\":\"用一句话解释什么是递归\",\"mode\":\"study\"}"
```

如果还是报 422 或 `URL rejected`，用 JSON 文件（最稳，支持流式）：

```powershell
$json = '{"message":"用一句话解释什么是递归","mode":"study"}'
[IO.File]::WriteAllText("$PWD\body.json", $json, (New-Object Text.UTF8Encoding($false)))
curl.exe -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" --data-binary "@body.json"
```

返回是一行行 SSE：

```
data: {"session_id": 1}

data: {"delta": "递归"}

data: {"delta": "就是"}

...

data: [DONE]
```

第二轮带上 `session_id`，它就能接着上文聊：

```powershell
curl.exe --% -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d "{\"message\":\"再举个例子\",\"session_id\":1}"
```

### 5. 试工具

W2 之后，这几句话会真正触发工具：

| 用户说 | 调用的工具 |
|---|---|
| 「现在几点了？」 | `get_current_time` |
| 「2+3*4 等于多少？」 | `calculator` |
| 「帮我记一下周五交实验报告」 | `get_current_time` + `todo(add)` |
| 「我有哪些待办？」 | `todo(list)` |

工具调用时，SSE 会先出现两类事件，再出现 `delta`：

```
data: {"type": "tool_call", "name": "get_current_time", "arguments": "{}"}

data: {"type": "tool_result", "name": "get_current_time", "result": "当前时间：2026-11-02 08:53（UTC+8，星期一）"}

data: {"delta": "现在是 **2026 年 11 月 2 日 星期一 早上 8:53**"}
```

快速验证：

```powershell
$body = @{ message = "现在几点了？"; mode = "study" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

### 6. 上传课件 / 建知识库

单个文件走上传接口：

```powershell
curl.exe --% -X POST http://127.0.0.1:8000/api/documents -F "file=@C:\Users\梁明健\Desktop\deepseek harness 工作区\ai-agent开发工作区\ai-agent\data\course_materials\算法设计与分析\ch01\ch01算法概述.pptx" -F "course=算法设计与分析" -F "chapter=ch01"
```

返回里会有 `chunks` 数量。批量导入 ch01–ch03：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_course.py --chapters ch01,ch02,ch03
```

然后问：

```powershell
$body = @{ message = "0-1背包的状态转移方程是什么？"; mode = "study"; course = "算法设计与分析" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

Agent 会先调 `search_notes`，回答里带 `[L3]` 这样的出处。

### 7. 按科目找学习记录

传了 `course` 的会话会绑定这门课，检索默认只查这门课：

```powershell
curl.exe --get http://127.0.0.1:8000/api/sessions --data-urlencode "course=算法设计与分析"
```

按关键词搜历史（标题或消息内容）：

```powershell
curl.exe --get http://127.0.0.1:8000/api/sessions --data-urlencode "q=背包"
```

只看学习或生活模式的历史：

```powershell
curl.exe --get http://127.0.0.1:8000/api/sessions --data-urlencode "mode=study"
curl.exe --get http://127.0.0.1:8000/api/sessions --data-urlencode "mode=life"
```

删除一条历史（题目会保留在题库）：

```powershell
curl.exe -X DELETE http://127.0.0.1:8000/api/sessions/15
```

回看某个会话：

```powershell
curl.exe http://127.0.0.1:8000/api/sessions/15/messages
```

> 一个会话只属于一门课和一个模式。带着 `session_id` 换科目或换学习/生活模式，接口都会返回 409，提示新建会话，避免历史记录串在一起。

### 8. 录题：粘贴 / 上传 / 拍照

题目不会直接拿去讲：先存成 `draft`，你确认（可以顺手改错字）之后才变 `confirmed`，接口层会拦住未确认的题。

**粘贴文字：**

```powershell
$body = @{
  text = "0-1 背包问题的状态转移方程是什么？"
  course = "算法设计与分析"
  chapter = "ch03"
} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/questions/text" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

**上传 PDF / Word / PPTX / 图片：**

```powershell
curl.exe --% -X POST http://127.0.0.1:8000/api/questions/upload -F "file=@C:\path\to\题目.png" -F "course=算法设计与分析" -F "chapter=ch03"
```

图片支持 JPG/PNG/WebP、≤10MB；文档支持 PDF/PPTX/DOCX/MD/TXT、≤20MB。图片会先压缩到长边 1600px，再交给 Qwen-VL 只做转写（文字 + LaTeX），不会解答。

> 没配 `VISION_API_KEY` 时，图片入口返回 503，并提示去 `.env` 配置；文字/文档入口不受影响。

**确认题干（可改错字）：**

```powershell
$body = @{ text = "改好的题干……" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/questions/1/confirm" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

**带题讲解：**

```powershell
$body = @{ message = "请讲解这道题"; mode = "study"; question_id = 1 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

后端会把已确认的题干拼进这次提问，前端不用重复传题干。题目图存在 `data/uploads/questions/{user_id}/`，**不会进入 chunks**。

**控制解题节奏：**

默认是「先提示」，不会一上来给答案。也可以显式传：

```json
{"message": "请讲解这道题", "mode": "study", "question_id": 1, "teaching_stage": "hint"}
```

- `hint`：最多 3 句话 + 一个问题，只给思路
- `step`：只推进一步，还不给最终答案
- `answer`：完整解答，按「课程 / 题型 / 知识点 / 思路 / 步骤 / 答案 / 依据 / 易错点」输出

不传 `teaching_stage` 时，说「继续 / 下一步 / 然后呢」会自动进 `step`，说「直接看答案 / 给答案」会自动进 `answer`。

### 9. L3 考前自测

按课程/章节从本地课件出选择题（1–10 道），出题前不返回答案：

```powershell
$body = @{
  course = "算法设计与分析"
  chapter = "ch03"
  topic = "0-1背包"
  count = 2
} | ConvertTo-Json -Compress
$quiz = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/quizzes/generate" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
$quiz.items | Format-Table id, question, options
```

提交答案（key 是题目 id，value 是 A/B/C/D）：

```powershell
$answers = @{}
$quiz.items | ForEach-Object { $answers[$_.id] = "A" }
$body = @{ answers = $answers } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/quizzes/$($quiz.id)/submit" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

提交后会返回 `score` / `percent` / 每题 `your_answer`、`correct_answer`、`explanation` 和 `[L]` 出处。`GET /api/quizzes/{id}` 永远不返回答案。

### 10. 联网检索（web_search）

Agent 的默认顺序是：**先查本地课件 `search_notes`，本地不够才联网**。
如果问题涉及最新信息，或者你明确说「联网查一下」，它会调用 `web_search`（Tavily），回答里用 `[W1]`、`[W2]` 标网页出处。

```powershell
$body = @{
  message = "先查本地课件，再用网上资料补充：0-1 背包的状态转移方程怎么推？"
  mode = "study"
  course = "算法设计与分析"
} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

配置真实 Key：

```powershell
# 打开 .env，把下面这行改成自己的 Key
TAVILY_API_KEY=tvly-xxxxxxxx
```

然后重启 uvicorn，先单独跑一次搜索自检（不经过模型，最快确认 Key 和网络都通）：

```powershell
.\.venv\Scripts\python.exe scripts\check_w3_extras.py --web "0-1 背包 动态规划 状态转移方程"
```

看到 `[W1] 标题 / URL / 摘要` 就说明联网通了。拍照也能一起自检：

```powershell
.\.venv\Scripts\python.exe scripts\check_w3_extras.py --image "C:\path\to\题目.jpg" --web "动态规划"
```

> `TAVILY_API_KEY` 没配时，`web_search` 不会让整个请求崩掉，而是返回一句「还没有配置 TAVILY_API_KEY」，模型会据此告诉你先补 Key；本地 `search_notes` 不受影响。
>
> 联网结果可能过时，关键结论仍以课程课件为准；两者冲突时提示词要求「以课件为准，并说明差异」。

---

## 目录结构

```
ai-agent/
├── app/
│   ├── main.py            # FastAPI 入口、/health
│   ├── config.py          # 读 .env，集中配置
│   ├── api/chat.py        # 对话接口 + SSE
│   ├── api/documents.py   # 课件上传/列表/删除
│   ├── api/questions.py   # 题目粘贴/上传/转写/确认
│   ├── api/quizzes.py     # L3 自测出题/判分
│   ├── api/sessions.py    # 学习记录：按科目筛选、回看
│   ├── api/auth.py        # 注册/登录/当前用户
│   ├── api/todos.py       # 待办 CRUD
│   ├── api/courses.py     # 按科目汇总
│   ├── core/deps.py       # 当前用户（JWT Bearer）
│   ├── agent/
│   │   ├── llm.py         # DeepSeek 客户端
│   │   ├── vision.py      # Qwen-VL 图片转写
│   │   ├── loop.py        # 模型 ↔ 工具循环
│   │   └── prompts.py     # 系统提示词
│   ├── tools/
│   │   ├── base.py        # 工具协议
│   │   ├── time.py        # 当前时间
│   │   ├── calculator.py  # 安全计算器
│   │   ├── todo.py        # 待办 CRUD
│   │   ├── search_notes.py# 课程资料检索
│   │   └── web_search.py  # Tavily 联网检索
│   ├── rag/
│   │   ├── parser.py      # PDF/PPTX/DOCX/MD/TXT 解析；扫描 PDF 走 OCR
│   │   ├── tokenizer.py   # 中文二元组分词
│   │   ├── retriever.py   # BM25 检索
│   │   └── ingest.py      # 入库（documents + chunks）
│   └── db/
│       ├── base.py        # 引擎、Session、WAL
│       ├── models.py      # 所有表
│       └── init.py        # 建表 + demo 用户
├── web/                   # React + Vite 前端（V3 主入口）
│   ├── src/components/    # 侧栏、聊天、Markdown
│   ├── src/pages/         # 登录、知识库、题库
│   └── src/lib/api.ts     # Bearer + SSE 封装
├── ui/                    # 旧 Streamlit 入口（兼容保留）
├── scripts/
│   ├── ingest_course.py   # 批量导入课件
│   └── check_w3_extras.py # 拍照/联网 Key 与真实调用自检
├── tests/
├── data/                  # SQLite、课件、chunks（自动生成，已 gitignore）
├── .env.example
└── pyproject.toml
```

## 数据表

| 表 | 用途 | 什么时候用 |
|---|---|---|
| `users` | 用户 | W1 起 |
| `chat_sessions` | 会话，绑定 `course` 科目 | W1 起 |
| `messages` | 消息 | W1 起 |
| `documents` | 课程资料 | W3 |
| `chunks` | 课件切分后的检索单元 | W3 |
| `questions` | 题目草稿/确认后的题干 | W3 |
| `quizzes` | 一套自测 | W3 |
| `quiz_questions` | 自测里的题、选项、答案 | W3 |
| `todos` | 待办 | W2 |
| `memories` | 长期记忆 | W4 |
| `usage_daily` | 每日用量 | W6 |

所有业务表都有 `user_id`，查询时记得带上——这是第 5 周多用户隔离的基础。

---

## 本周验收（W3）

- [x] `pytest -q` 显示 `48 passed`
- [ ] 启动服务后，`POST /api/documents` 能上传一份 PPTX/MD 并返回 chunk 数
- [ ] `GET /api/documents` 能看到刚上传的资料
- [ ] 带 `course` 提问后，会话绑定这门课；`GET /api/sessions?course=...` 能查到
- [ ] 同一会话换科目返回 409，提示新建会话
- [ ] `GET /api/sessions?q=...` 能按关键词搜到历史消息
- [ ] 问「0-1 背包的状态转移方程是什么？」，Agent 先调 `search_notes`，回答带 `[L]` 引用
- [ ] 问一个资料里没有的问题，回答明确说「资料里没有」，不编造
- [ ] 删除资料后，再问同样的问题检索不到
- [ ] 批量导入 ch01–ch03 后，`data/app.db` 的 `chunks` 表有数据
- [ ] 粘贴一段题 → draft；确认后 `POST /api/chat` 带 `question_id` 能讲解
- [ ] 未确认的题直接带 `question_id` 提问 → 409，接口层拦住
- [ ] 上传 PDF/PPTX/图片 → 返回可编辑题干；题目图不出现在 `chunks`
- [ ] 没配 `VISION_API_KEY` 时图片入口 → 503，文字/文档入口正常
- [ ] 生成一套 2 题自测 → 提交 → 返回分数和解析；`GET` 不泄露答案
- [ ] 本地资料没有时，Agent 调用 `web_search`，回答带 `[W1]` 引用
- [x] 10 张印刷体题目截图，10/10 转写可读；6 个问题 6/6 通过；本地 `[L]` 4/4（报告：`data/acceptance/w3_report.md`）
- [x] `python scripts/w3_acceptance.py` 能复跑整套验收
- [x] `python scripts/check_w3_extras.py --image ... --web ...` 两项都真实跑通
- [x] `.env` 没有被提交（`git status` 里看不到）

> 验收已通过；`w3_acceptance.py` 的 10 张是 PIL 生成的印刷体，真实手机照片用 `check_w3_extras.py --image` 单张验证。复跑整套：

```powershell
python scripts/w3_acceptance.py
```

## 本周验收（W4）

- [x] `python scripts/w4_acceptance.py`：10 道题都走完 hint → step → answer，三阶段 10/10，本地 `[L]` 8/8
- [x] 人工核对 10 道答案 10/10 通过（验收单 `docs/W4-10题验收单.md`；完整对话 `data/acceptance/w4/q01.md` … `q10.md`）
- [x] PushPlus 测试消息能收到
- [x] 连续 10 条待办到点提醒都能收到（10/10）
- [x] `pytest -q` 显示 `48 passed`

W4 十题报告：`data/acceptance/w4_report.md`；每道题的完整 hint/step/answer 在 `data/acceptance/w4/`；人工核对用 `docs/W4-10题验收单.md`。

```powershell
# 10 道题（会真实调用模型，约 1–2 分钟）
python scripts/w4_acceptance.py

# PushPlus：先设置 token，再配置通道、发测试消息、创建 10 条到点待办
$env:PUSHPLUS_TOKEN = "你的 PushPlus token"
python scripts/w4_push_acceptance.py --count 10 --interval 10 --wait 240
```

> PushPlus token 在 https://www.pushplus.plus/ 微信扫码登录后复制。脚本不会打印 token；token 存在本地数据库 `push_channels` 表里，`.env` 和 `data/` 都被 git 忽略。

---

## 常见问题

**Q：`source .venv/bin/activate` 报「无法将 source 项识别为...」**
A：`source` 是 macOS / Linux 的写法，Windows PowerShell 用：

```powershell
.\.venv\Scripts\Activate.ps1
```

或者干脆不激活，直接用 `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`。

**Q：`ERROR: Could not open requirements file: ... requirements-dev.txt`**
A：终端不在项目目录。`requirements-dev.txt` 在 `ai-agent` 目录下，先 `cd` 过去再执行：

```powershell
cd "C:\Users\梁明健\Desktop\deepseek harness 工作区\ai-agent开发工作区\ai-agent"
```

**Q：`pip install` 提示 `Defaulting to user installation because normal site-packages is not writeable`**
A：说明当前用的是**系统 Python**，不是 venv。先激活，或直接用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

**Q：`pip install -e ".[dev]"` 报 `Could not find a version that satisfies the requirement setuptools>=68`**
A：这是 pip 在「构建隔离环境」里没拉到 setuptools，常见于镜像或 Python 3.14 的组合。本项目**不需要** editable 安装，直接用：

```powershell
pip install -r requirements-dev.txt
```

如果确实想以可编辑模式安装，先 `pip install setuptools`，再：

```powershell
pip install -e ".[dev]" --no-build-isolation
```

**Q：启动报 `ModuleNotFoundError: No module named 'app'`**
A：确认终端在 `ai-agent` 目录下，且虚拟环境已激活、执行过 `pip install -r requirements-dev.txt`。

**Q：`/api/chat` 返回 503**
A：`.env` 里没填 `DEEPSEEK_API_KEY`，或填的还是 `sk-xxxxxxxx`。改完重启服务。

**Q：401 `Authentication Fails, Your api key ... is invalid`**
A：Key 本身无效，不是网络问题。常见原因：

1. 用了**阿里云百炼/Qwen** 的 Key，不是 DeepSeek 的；
2. Key 被删除/重置过，或复制时漏了字符；
3. Key 是从别的项目/旧账号复制的。

去 <https://platform.deepseek.com> 重新创建一个 Key，更新 `.env` 后**重启 uvicorn**。可以用下面的命令单独验证 Key：

```powershell
Invoke-RestMethod -Uri "https://api.deepseek.com/models" -Headers @{ Authorization = "Bearer sk-你的新Key" }
```

返回模型列表就说明 Key 有效；命令里的 Key 不要发到公开地方。

**Q：`/api/chat` 返回 422，或 curl 报 `URL rejected: Port number was not a decimal number`**
A：Windows PowerShell 5.1 把 JSON 拆成了多个参数。最稳的是 `Invoke-RestMethod`：

```powershell
$body = @{ message = "用一句话解释什么是递归"; mode = "study" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

想流式输出，用 `curl.exe --%` 或 JSON 文件，见「试一次对话」。

**Q：curl 报 `Failed to connect to 127.0.0.1:8000`**
A：服务没在运行。如果 uvicorn 窗口里出现 `Shutting down`，说明你按了 Ctrl+C 或关了窗口。重新运行 `uvicorn app.main:app --reload`，保持这个窗口不关，再另开一个 PowerShell 窗口执行 curl。

**Q：端口被占用**
A：换端口：`uvicorn app.main:app --reload --port 8001`。

**Q：`pip install` 很慢或超时**
A：换国内镜像：

```powershell
pip install -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

如果清华镜像也报找不到包，换阿里云：

```powershell
pip install -r requirements-dev.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**Q：某个依赖装不上、提示要编译**
A：优先用 Python 3.12 / 3.13。本项目在 3.14 上验证过，但个别依赖可能还没发布 3.14 的预编译包。

**Q：数据库锁住（`database is locked`）**
A：确认没有同时开多个写入进程；本项目已开启 WAL。实在不行删掉 `data/app.db` 重启（会丢本地数据）。

**Q：PowerShell 里中文显示乱码**
A：先执行 `chcp 65001`，或用 Windows Terminal。

---

## 附录：安装 Git（Windows）

> 判断有没有装：在 PowerShell 里输入 `git --version`。提示「无法将 git 项识别为 cmdlet」就是没装。
> 装完必须**关掉终端重新打开**，PATH 才会生效。

### 方式一：安装包（推荐）

1. 打开清华镜像（国内下载快）：
   <https://mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/LatestRelease/>
2. 下载 `Git-2.56.0.4-64-bit.exe`（以页面上的最新版为准，认准 `64-bit.exe`）。
   官网地址：<https://git-scm.com/download/win>
3. 双击安装包，UAC 弹窗点「是」。
4. 一路 Next，基本保持默认。只有两处确认一下：
   - PATH 选项选 **Git from the command line and also from 3rd-party software**
   - 换行符选 **Checkout Windows-style, commit Unix-style**
5. 装完重开 PowerShell，执行：

```powershell
git --version
```

看到 `git version 2.56.0.4` 这类输出就成功了。

### 方式二：便携版（没有管理员权限时）

- 在同一镜像页下载 `MinGit-2.56.0.4-64-bit.zip`，解压到 `C:\Tools\MinGit`
- 把 `C:\Tools\MinGit\cmd` 加入用户环境变量 `Path`
- 重开终端，`git --version` 能输出版本即可
- 说明：MinGit 只有命令行，没有 Git Bash；`init` / `commit` / `push` 完全够用

### 装完后的初始化配置

把名字和邮箱换成你自己的（邮箱建议和 GitHub 一致）：

```powershell
git config --global user.name "梁明健"
git config --global user.email "你的邮箱@example.com"
git config --global init.defaultBranch main
git config --global core.quotepath false
git config --global --list
```

- `init.defaultBranch main`：以后新建仓库默认分支叫 `main`
- `core.quotepath false`：中文文件名不显示成 `\346\226...`

### 提交记录

仓库从 W1 到 V3 的主要提交是：

```text
661b04b feat(ui): 侧边栏折叠、学习生活历史隔离与删除
4f50aca docs: 补 V3 提交记录
3a41b09 fix(ui): 桌面端隐藏侧栏关闭按钮
5bf806e V3: React 前端与扫描版 PDF OCR
dbf286b fix(ui): 录题确认后用 pending_nav 跳转
4613ffd W5: 多用户 JWT 鉴权、邀请码与 Streamlit 前端
e7e569f W4: 完成十题与 PushPlus 验收，补验收脚本
6db1956 W4: 生活模式、长期记忆、待办提醒与 PushPlus
4b28486 W4: 解题老师三阶段提示 + W3 复盘
321ecec W3: 完成拍照与问题验收，修复视觉模型名
851dfb3 W2/W3: 工具循环、本地 RAG、题目与联网检索
42cad00 W1: FastAPI 骨架与流式对话
```

查看历史：

```powershell
cd "C:\Users\梁明健\Desktop\deepseek harness 工作区\ai-agent开发工作区\ai-agent"
git --no-pager log --oneline
git status
```

以后每完成一周，再 `git add` + `git commit` 一次即可，不用再 `git init`。`git status` 里应该**看不到 `.env`**（本项目已在 `.gitignore` 里排除）。

### 小技巧：`git log` 卡住不动

如果执行 `git log` 后光标停在 `:`（或左下角显示 `:`），不是卡死，是进了分页器：

- 按 `q` 退出
- 或者以后用 `git --no-pager log --oneline`
- 想让它只有一屏时自动退出：`git config --global core.pager "less -F"`

---

## 接下来

W3 的代码、测试、文档和验收都已完成：`w3_acceptance.py` 的 10 张截图 **10/10 可读**、6 个问题 **6/6 通过**、本地 `[L]` **4/4**，报告在 `data/acceptance/w3_report.md`。真实手机拍照可再用 `check_w3_extras.py --image` 验证单张。

W4 主线：

1. 解题老师：先提示、再分步、最后答案。
2. 生活模式：人格、长期记忆、待办日期。
3. 手机推送：PushPlus 到点提醒。

具体验收标准见工作区上一级的 `AI-Agent开发大纲.md` 第 3、4 周。
