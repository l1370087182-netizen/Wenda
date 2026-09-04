"""MCP Server：把日报系统能力暴露给任意 MCP 客户端（Claude Desktop / Claude Code 等）

- 只读工具：看板 Top5 / 跨类洞察 / 知识库检索 / 研究问答 / 流水线状态
- 管理工具：重跑流水线 / 补发日报（需 MCP_ADMIN_TOKEN）
- 挂载于 FastAPI /mcp，与 REST API、前端同进程
"""
import logging
from datetime import date as date_cls, timedelta

from mcp.server.mcpserver import MCPServer

from app.config import settings
from app.models import Article, Digest, INSIGHT_SLUG, JobRun
from app.services import digest as digest_svc
from app.services.db import SessionFactory
from app.services.graph import run_chat, run_daily

logger = logging.getLogger(__name__)

mcp = MCPServer("news-daily")

# 挂载用 Starlette 子应用（stateless 模式；内部路径设为 /，挂载到 FastAPI 的 /mcp 下）
mcp_app = mcp.streamable_http_app(stateless_http=True, streamable_http_path="/")


class _RootPathFix:
    """Starlette Mount 对精确前缀（/mcp）会传空串路径给子应用，而子应用路由注册在 / 上；
    此包装器把空路径规整为 /，保证两种写法都能命中。"""

    def __init__(self, asgi) -> None:
        self._asgi = asgi

    async def __call__(self, scope, receive, send):
        if scope.get("path") == "":
            scope = {**scope, "path": "/"}
        await self._asgi(scope, receive, send)


mcp_asgi = _RootPathFix(mcp_app)

CATEGORY_NAMES = digest_svc.CATEGORY_NAMES


def _check_token(token: str) -> str | None:
    """管理工具鉴权；返回错误信息或 None。"""
    if not settings.mcp_admin_token:
        return "服务器未配置 MCP_ADMIN_TOKEN，管理工具不可用"
    if token != settings.mcp_admin_token:
        return "403：token 无效"
    return None


# ============================== 只读工具 ==============================

@mcp.tool()
async def get_top_news(category: str, day_str: str | None = None) -> str:
    """获取某分类某日的重要度 Top5 资讯。

    Args:
        category: 分类 slug（tech/geo/finance/ai_tech/ai_news/github）
        date: 日期 YYYY-MM-DD，默认昨天
    """
    from sqlalchemy import select

    day = date_cls.fromisoformat(day_str) if day_str else date_cls.today() - timedelta(days=1)
    async with SessionFactory() as db:
        rows = (await db.scalars(
            select(Article)
            .where(Article.category == category, Article.batch_date == day)
            .order_by(Article.importance_score.desc().nulls_last(), Article.hot_score.desc().nulls_last())
            .limit(5)
        )).all()
    if not rows:
        return f"{category} 在 {day} 无数据（可能采集失败）"
    return "\n\n".join(
        f"{i + 1}. [{a.source}] {a.title}（重要度 {a.importance_score}，热度 {a.hot_score}）\n"
        f"   {a.summary or ''}\n   {a.url}"
        for i, a in enumerate(rows)
    )


@mcp.tool()
async def get_cross_insight(day_str: str | None = None) -> str:
    """获取某日的跨分类关联洞察（如：地缘事件→油价→航运/芯片）。

    Args:
        date: 日期 YYYY-MM-DD，默认昨天
    """
    from sqlalchemy import select

    day = date_cls.fromisoformat(day_str) if day_str else date_cls.today() - timedelta(days=1)
    async with SessionFactory() as db:
        row = (await db.scalars(
            select(Digest).where(Digest.category == INSIGHT_SLUG, Digest.date == day)
        )).first()
    return row.body_html if row else f"{day} 无洞察数据"


@mcp.tool()
async def search_knowledge(query: str, top_k: int = 6) -> str:
    """在资讯知识库中做语义检索，返回最相关的历史文章。

    Args:
        query: 检索词
        top_k: 返回条数（1-10）
    """
    from app.services.vector import search as vector_search

    async with SessionFactory() as db:
        articles = await vector_search(db, query, top_k=max(1, min(10, top_k)))
    if not articles:
        return "未检索到相关文章"
    return "\n\n".join(f"[{a.id}] {a.title}（{a.source}）\n{(a.summary or '')[:150]}\n{a.url}" for a in articles)


@mcp.tool()
async def ask(question: str) -> str:
    """深度问答：多步研究 Agent（拆解子问题→检索→自检→综合），附来源。

    Args:
        question: 问题
    """
    result = await run_chat(None, question=question, history=[])
    src = "\n".join(f"[{i + 1}] {s['title']}: {s['url']}" for i, s in enumerate(result["sources"]))
    skill = f"（使用技能：{result['skill']}）" if result.get("skill") else ""
    return f"{result['answer']}{skill}\n\n来源：\n{src or '无'}"


@mcp.tool()
async def get_pipeline_status(days: int = 3) -> str:
    """查询最近 N 天采集/发送任务的运行状态。

    Args:
        days: 查询天数（1-30）
    """
    from sqlalchemy import select

    since = date_cls.today() - timedelta(days=max(1, min(30, days)))
    async with SessionFactory() as db:
        rows = (await db.scalars(
            select(JobRun).where(JobRun.date >= since).order_by(JobRun.id.desc()).limit(30)
        )).all()
    if not rows:
        return "最近无任务运行记录"
    return "\n".join(
        f"{r.date} {r.job}: {r.status}" + (f"（{r.error[:100]}）" if r.error else "")
        for r in rows
    )


# ============================== 管理工具（token 鉴权）==============================

@mcp.tool()
async def rerun_pipeline(token: str, day_str: str | None = None) -> str:
    """管理员：重跑指定日期的采集流水线（采集→分析→digest→洞察→审查）。

    Args:
        token: 管理员 token（MCP_ADMIN_TOKEN）
        date: 日期 YYYY-MM-DD，默认今天
    """
    err = _check_token(token)
    if err:
        return err
    day = date_cls.fromisoformat(day_str) if day_str else date_cls.today()
    job = await run_daily(day)
    return f"重跑完成：{job.status}；详情：{job.error or '无'}"


@mcp.tool()
async def resend_digest(token: str, day_str: str | None = None) -> str:
    """管理员：向当日活跃订阅用户补发日报邮件。

    Args:
        token: 管理员 token（MCP_ADMIN_TOKEN）
        date: 日期 YYYY-MM-DD，默认今天
    """
    err = _check_token(token)
    if err:
        return err
    from app.services.scheduler import job_send_daily

    day = date_cls.fromisoformat(day_str) if day_str else date_cls.today()
    await job_send_daily(day)
    return f"{day} 日报补发已执行"
