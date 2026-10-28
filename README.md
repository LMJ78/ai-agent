# 伴学 · AI Agent

一个面向大学生的 AI Agent：**学习助手 + 生活伴侣**。

当前进度：**第 1 周（骨架 + 流式对话）**。  
本阶段目标：把「请求 → 模型 → 流式返回 → 落库」这条最小链路跑通，并让所有数据表提前带上 `user_id`。

---

## 已经实现

| 能力 | 说明 |
|---|---|
| `GET /health` | 健康检查，会真的查一次数据库 |
| `POST /api/chat` | 对话接口，SSE 流式返回 |
| 会话与消息落库 | `chat_sessions` / `messages`，都带 `user_id` |
| 多轮上下文 | 自动带上最近 16 条消息 |
| 友好错误 | 没配 Key 返回 503，并提示怎么配 |
| 测试 | 4 个用例：健康检查、未配置 Key、流式落库、越权会话 |

> 已在 Python 3.14 + FastAPI 0.162 下验证：`/health` 200、未配 Key 时 `/api/chat` 503、4 个测试全过。
>
> 还没有工具调用、文档上传、登录。这些分别在 W2、W3、W5 做。

---

## 快速开始

### 0. 准备

- Python 3.11+（3.14 也可以）
- Git（提交代码用；没装也能先跑，安装方法见文末「附录：安装 Git」）

### 1. 创建虚拟环境并安装依赖

在 `ai-agent` 目录下打开终端：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

macOS / Linux 用：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. 配置密钥

```powershell
copy .env.example .env
```

打开 `.env`，把 `DEEPSEEK_API_KEY` 换成真实 Key。没有 Key 时服务也能启动，只是 `/api/chat` 会返回 503。

### 3. 启动

```powershell
uvicorn app.main:app --reload
```

打开：

- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

### 4. 试一次对话

PowerShell 里 `curl` 是别名，建议用 `curl.exe`（整条命令复制即可，别换行）：

```powershell
curl.exe -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d '{"message":"用一句话解释什么是递归","mode":"study"}'
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
curl.exe -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d '{"message":"再举个例子","session_id":1}'
```

---

## 目录结构

```
ai-agent/
├── app/
│   ├── main.py            # FastAPI 入口、/health
│   ├── config.py          # 读 .env，集中配置
│   ├── api/chat.py        # 对话接口 + SSE
│   ├── core/deps.py       # 当前用户（W1 固定 demo）
│   ├── agent/
│   │   ├── llm.py         # DeepSeek 客户端
│   │   └── prompts.py     # 系统提示词
│   └── db/
│       ├── base.py        # 引擎、Session、WAL
│       ├── models.py      # 所有表
│       └── init.py        # 建表 + demo 用户
├── tests/
├── data/                  # SQLite（自动生成，已 gitignore）
├── .env.example
└── pyproject.toml
```

## 数据表

| 表 | 用途 | 什么时候用 |
|---|---|---|
| `users` | 用户 | W1 起 |
| `chat_sessions` | 会话 | W1 起 |
| `messages` | 消息 | W1 起 |
| `documents` | 课程资料 | W3 |
| `todos` | 待办 | W2 |
| `memories` | 长期记忆 | W4 |
| `usage_daily` | 每日用量 | W6 |

所有业务表都有 `user_id`，查询时记得带上——这是第 5 周多用户隔离的基础。

---

## 本周验收（W1）

- [ ] `pip install -e ".[dev]"` 无报错
- [ ] `uvicorn app.main:app --reload` 能启动，`/health` 返回 `status: ok`
- [ ] `/docs` 能看到两个接口
- [ ] 填好 Key 后，`/api/chat` 能流式输出中文
- [ ] 不带 `session_id` 发第二轮时，能自动新建会话；带上时能接上文
- [ ] 把 Key 删掉重启，`/api/chat` 返回 503 且提示清楚
- [ ] `pytest` 全绿
- [ ] `data/app.db` 里 `users` / `chat_sessions` / `messages` 三张表都有 `user_id`
- [ ] `.env` 没有被提交（`git status` 里看不到）

---

## 常见问题

**Q：启动报 `ModuleNotFoundError: No module named 'app'`**  
A：确认终端在 `ai-agent` 目录下，且虚拟环境已激活、执行过 `pip install -e .`。

**Q：`/api/chat` 返回 503**  
A：`.env` 里没填 `DEEPSEEK_API_KEY`，或填的还是 `sk-xxxxxxxx`。改完重启服务。

**Q：端口被占用**  
A：换端口：`uvicorn app.main:app --reload --port 8001`。

**Q：`pip install` 很慢或超时**  
A：换国内镜像：`pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple`。

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

### 第一次提交

```powershell
cd "C:\Users\梁明健\Desktop\deepseek harness 工作区\ai-agent开发工作区\ai-agent"
git init
git status
git add .
git commit -m "W1: FastAPI 骨架与流式对话"
git log --oneline
```

`git status` 里应该**看不到 `.env`**（本项目已在 `.gitignore` 里排除）。

---

## 下一周（W2）要做什么

1. 定义工具协议（`name` / `description` / `parameters` / `execute`）。
2. 手写「模型 → 工具 → 模型」循环，最多 5 轮。
3. 加三个工具：时间、计算器、待办（SQLite）。
4. 接口返回这一轮调用了哪些工具，方便调试。

具体验收标准见工作区上一级的 `AI-Agent开发大纲.md` 第 2 周。
