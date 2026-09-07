"""FastAPI 入口：API 路由 + APScheduler 生命周期（纯 API，前端由独立 nginx 容器部署）"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.services.db import SessionFactory, engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建表（开发期 create_all，生产用 alembic）+ 管理员引导 + 启动定时任务
    await init_db()
    from app.api.auth import ensure_admin
    from app.services.scheduler import start_scheduler, stop_scheduler

    async with SessionFactory() as db:
        await ensure_admin(db)

    # MCP session manager（挂载的子应用不自动跑 lifespan，需手动接管）
    from app.mcp_server import mcp, mcp_app

    cm = mcp.session_manager.run()
    await cm.__aenter__()
    logger = logging.getLogger("uvicorn.info")
    logger.info("MCP server ready at /mcp")

    scheduler = await start_scheduler()
    yield
    # 关停：停止调度器、释放连接
    if scheduler:
        scheduler.shutdown(wait=False)
    await engine.dispose()
    await cm.__aexit__(None, None, None)


app = FastAPI(title="六类资讯日报系统", version="1.0", lifespan=lifespan)

# CORS（前端独立开发服务器用；生产为同源托管，不需要）
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in settings.cors_origins.split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MCPPathFixMiddleware:
    """/mcp（无尾斜杠）命中不了 Mount（Starlette 1.6 Mount 不匹配空余路径）→ 404/405；统一重写为 /mcp/ 使其命中 MCP 挂载。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
        await self.app(scope, receive, send)


app.add_middleware(MCPPathFixMiddleware)


@app.get("/api/health")
async def health():
    return {"status": "ok", "timezone": settings.timezone}


# ---- API 路由 ----
from app.api.admin import router as admin_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402
from app.api.dashboard import router as dashboard_router  # noqa: E402
from app.api.favorites import router as favorites_router  # noqa: E402
from app.api.llm_config import router as llm_config_router  # noqa: E402
from app.api.skills import router as skills_router  # noqa: E402
from app.api.tasks import router as tasks_router  # noqa: E402
from app.api.users import router as users_router  # noqa: E402

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(llm_config_router)
app.include_router(skills_router)
app.include_router(dashboard_router)
app.include_router(favorites_router)
app.include_router(chat_router)
app.include_router(tasks_router)
app.include_router(admin_router)


# MCP Server：系统能力暴露给 AI 客户端
from app.mcp_server import mcp_asgi  # noqa: E402

app.mount("/mcp", mcp_asgi, name="mcp")
