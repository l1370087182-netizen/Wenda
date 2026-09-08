# 六类资讯日报系统

每天定时采集六类资讯（科技 / 地缘 / 财经 / AI 技术 / 最新 AI 资讯 / GitHub 热点），多 Agent 编排完成去重、评分、摘要、影响分析、跨类关联洞察，08:00 发送每日一封订阅日报；网页看板 + 多轮研究问答。管理员后台提供系统概览、用户管理、任务运维、发送日志与 **Agent 轨迹可视化**（每步决策/工具调用可回溯）。

架构设计详见《六类资讯日报系统-架构设计文档.md》，开发过程见《开发记录.md》。

## 技术栈

FastAPI · SQLAlchemy(async) · PostgreSQL(pgvector) · Redis（LangGraph 检查点）· APScheduler · LangGraph（多 Agent）· Agent Skills · Vue 3（全手写设计系统，深/浅双主题）+ ECharts

前后端分离：`frontend/` 为独立 Vue 3 工程，生产部署为独立 nginx 容器（托管静态文件 + 反代 `/api`、`/mcp`），后端为纯 API，仅内网可达。

## 本地开发（Windows）

```bash
# 后端
docker compose -f docker-compose.dev.yml up -d   # postgres + redis（需先启动 Docker Desktop）
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100 --workers 1   # 8000 在 Windows 上常被系统保留段占用，故用 8100

# 前端（独立工程，开发期热更新）
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 代理到 8100（VITE_API_TARGET 可覆盖）
```

## 生产部署（2C2G 服务器）

四个容器：`frontend`（nginx，对外 8000 端口）→ `app`（纯 API，仅内网）+ `postgres` + `redis`。

```bash
# 1. 配置 .env（含管理员账号、SMTP、LLM Key）
# 2. 加 2G swap 防 OOM（推荐）
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile \
  && sudo mkswap /swapfile && sudo swapon /swapfile

# 3. 构建启动
docker compose up -d --build        # 标准版（对外 8000）
# 或 2G 内存共存版（对外 8100，限流更紧）：
docker compose -f docker-compose.prod.yml up -d
```

小内存服务器免构建部署（本地构建镜像后传上去）：

```bash
docker compose -f docker-compose.prod.yml build app frontend
docker compose -f docker-compose.prod.yml save app frontend | gzip > wenda-images.tar.gz
# 上传后：gunzip -c wenda-images.tar.gz | docker load && docker compose -f docker-compose.prod.yml up -d
```

## 环境变量（项目根目录创建 `.env`，运行时读取）

```env
# 管理员（唯一修改途径：编辑本文件）
ADMIN_USERNAME=adminljj
ADMIN_PASSWORD=

# 会话
COOKIE_DAYS=7

# SMTP（发件邮箱）
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=
SMTP_PASS=

# LLM / Embedding（系统默认模型；provider 可选 openai / anthropic）
LLM_PROVIDER=openai
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL_FAST=
LLM_MODEL_STRONG=
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=
EMBEDDING_MODEL=
EMBEDDING_DIM=1024

# 存储（本地开发连 localhost；容器内连服务名）
DATABASE_URL=postgresql+asyncpg://news:news@localhost:5432/news
REDIS_URL=redis://localhost:6379/0

# 前端（开发期 Vite 独立服务器）
CORS_ORIGINS=http://localhost:5173

# MCP（管理工具鉴权，留空=管理工具禁用）
MCP_ADMIN_TOKEN=
```

注意：

- `ADMIN_USERNAME` / `ADMIN_PASSWORD`：管理员唯一创建途径，启动时自动同步，不走注册/找回
- `LLM_MODEL_FAST` / `LLM_MODEL_STRONG`：模型分层（评分摘要走 fast，洞察/审查/问答走 strong）
- SMTP 未配置时验证码邮件会失败；LLM 未配置时流水线降级运行（无向量去重/评分）

## 定时任务（Asia/Shanghai）

| 时间 | 任务 | 说明 |
|---|---|---|
| 01:00 | collect_daily | 多 Agent 流水线：采集（异常自动换源）→ 去重 → 分析 → digest → 交叉洞察 → 主编审查 |
| 08:00 | send_daily | 活跃用户（7 天内登录过）发送每日一封合并日报 |
| 03:30 | cleanup | 过期会话清理 |

失败兜底：某分类采集失败 → 邮件中该板块显示原因与建议；管理员可 `POST /api/tasks/run` 重跑、`POST /api/tasks/send` 补发。

## API 一览

认证：`/api/auth/*`（send-code / register / login / logout / reset-password / me）
用户：`PUT /api/users/me/settings`　BYOK：`GET/PUT/DELETE /api/users/me/llm-config`（+ `/test` 连通性测试）　看板：`GET /api/dashboard/top|insight|articles/{id}`
问答：`POST /api/chat`、`GET /api/chats[/{id}]`　任务：`GET /api/tasks/status`
管理（管理员专属后台，前端侧栏「管理后台」入口）：`GET /api/admin/users|stats|send-logs|trace-runs|traces`、`PATCH/DELETE /api/admin/users/{id}`、`POST /api/tasks/run|send`

## MCP Server

系统同时是一个 MCP 服务器（端点 `/mcp`），任何 MCP 客户端可接入：

```bash
# Claude Code 接入
claude mcp add news-daily --transport http http://localhost:8000/mcp
```

只读工具：看板 Top5 / 跨类洞察 / 知识库检索 / 研究问答 / 流水线状态。
管理工具（重跑 / 补发）：需在 `.env` 配置 `MCP_ADMIN_TOKEN`，调用时传相同 token。

