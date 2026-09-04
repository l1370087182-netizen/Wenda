# 多阶段构建：阶段1 Node 构建前端 → 阶段2 Python 运行时（同源托管 dist）
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend/ .
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /srv/app

# 先装依赖（利用层缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# 拷贝应用 + 前端构建产物
COPY app ./app
COPY --from=frontend /build/dist ./frontend/dist

# ⚠️ 必须单进程：APScheduler 多 worker 会重复触发定时任务
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
