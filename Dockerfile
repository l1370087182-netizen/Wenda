# 后端纯 API 镜像（前端已独立成 frontend/ 自己的 nginx 镜像）
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /srv/app

# 国内 PyPI 镜像（服务器在境内时显著加速依赖下载；境外部署可删）
ENV UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# 先装依赖（利用层缓存）
# uv.lock 锁的是 files.pythonhosted.org 原始地址（境内极慢），构建时改写为阿里云镜像（同一文件、hash 校验不受影响）；境外部署可删这行 sed
COPY pyproject.toml uv.lock ./
RUN sed -i 's|https://files.pythonhosted.org|https://mirrors.aliyun.com/pypi|g' uv.lock \
    && uv sync --frozen --no-install-project

# 拷贝应用
COPY app ./app

# ⚠️ 必须单进程：APScheduler 多 worker 会重复触发定时任务
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
