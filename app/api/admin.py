"""管理员 API：系统概览 + 用户管理 + 发送日志 + Agent 轨迹查询（仅 ADMIN 角色）"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import business_today
from app.core.deps import get_db, require_admin
from app.models import (
    AgentTrace,
    Article,
    Digest,
    JobRun,
    Role,
    SendLog,
    User,
    UserLLMConfig,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUserItem(BaseModel):
    id: int
    email: str
    role: str
    is_verified: bool
    notify_enabled: bool
    subscribed_categories: list[str]
    created_at: str
    last_login_at: str | None
    last_used_at: str | None


def _fmt(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    date_after: date | None = Query(None, description="只看该日期之后注册的用户"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分页返回用户：注册时间 / 上次使用 / 登录时间。"""
    stmt = select(User).order_by(User.id.desc())
    count_stmt = select(func.count(User.id))
    if date_after:
        stmt = stmt.where(User.created_at >= date_after)
        count_stmt = count_stmt.where(User.created_at >= date_after)

    total = await db.scalar(count_stmt)
    rows = (await db.scalars(stmt.offset((page - 1) * size).limit(size))).all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            AdminUserItem(
                id=u.id,
                email=u.email,
                role=u.role,
                is_verified=u.is_verified,
                notify_enabled=u.notify_enabled,
                subscribed_categories=u.subscribed_categories or [],
                created_at=_fmt(u.created_at) or "",
                last_login_at=_fmt(u.last_login_at),
                last_used_at=_fmt(u.last_used_at),
            )
            for u in rows
        ],
    }


@router.get("/trace-runs")
async def list_trace_runs(
    days: int = Query(7, ge=1, le=30),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """近 N 天有 Agent 轨迹的运行列表（供后台选择查看哪一次运行）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            AgentTrace.run_id,
            func.count(AgentTrace.id).label("steps"),
            func.count(func.distinct(AgentTrace.agent_name)).label("agents"),
            func.min(AgentTrace.created_at).label("started_at"),
        )
        .where(AgentTrace.created_at >= since)
        .group_by(AgentTrace.run_id)
        .order_by(func.min(AgentTrace.created_at).desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "run_id": r.run_id,
            "steps": r.steps,
            "agents": r.agents,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in rows
    ]


@router.get("/traces")
async def get_traces(
    run_id: str = Query(..., description="运行 id，如 collect-2026-09-08"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """某次运行的全部 Agent 轨迹（按写入序 = 真实时间序），供后台可视化每步决策/工具调用。"""
    rows = (await db.scalars(
        select(AgentTrace).where(AgentTrace.run_id == run_id).order_by(AgentTrace.id)
    )).all()
    return {
        "run_id": run_id,
        "count": len(rows),
        "traces": [
            {
                "agent_name": t.agent_name,
                "step": t.step,
                "kind": t.kind,
                "tool_name": t.tool_name,
                "input": t.input,
                "output": t.output,
                "model_tier": t.model_tier,
                "latency_ms": t.latency_ms,
                "created_at": _fmt(t.created_at),
            }
            for t in rows
        ],
    }


# ============================ 系统概览 ============================

@router.get("/stats")
async def system_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """系统概览：用户 / 文章 / 日报 / 发送 / 轨迹 的关键计数 + 最近任务运行状态。"""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    today = business_today()

    async def count(model, *conds) -> int:
        stmt = select(func.count(model.id))
        if conds:
            stmt = stmt.where(*conds)
        return await db.scalar(stmt) or 0

    # 今日各分类文章数
    cat_rows = (await db.execute(
        select(Article.category, func.count(Article.id))
        .where(Article.batch_date == today)
        .group_by(Article.category)
    )).all()

    # 最近任务运行：每个 job 取最新一条
    job_rows = (await db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(40))).all()
    latest_jobs: dict[str, dict] = {}
    for r in job_rows:
        if r.job not in latest_jobs:
            latest_jobs[r.job] = {
                "job": r.job,
                "date": r.date.isoformat(),
                "status": r.status,
                "error": (r.error or "")[:300],
                "started_at": _fmt(r.started_at),
                "finished_at": _fmt(r.finished_at),
            }

    return {
        "today": today.isoformat(),
        "users": {
            "total": await count(User),
            "verified": await count(User, User.is_verified.is_(True)),
            "admins": await count(User, User.role == Role.ADMIN.value),
            "active_7d": await count(User, User.last_used_at >= week_ago),
            "new_7d": await count(User, User.created_at >= week_ago),
            "llm_configured": await count(UserLLMConfig, UserLLMConfig.api_key != ""),
        },
        "articles": {
            "total": await count(Article),
            "today": await count(Article, Article.batch_date == today),
            "by_category": {c: n for c, n in cat_rows},
        },
        "digests": {
            "total": await count(Digest),
            "sent": await count(Digest, Digest.status == "sent"),
        },
        "send_logs": {
            "total": await count(SendLog),
            "failed_7d": await count(SendLog, SendLog.status == "failed", SendLog.sent_at >= week_ago),
        },
        "agent_traces": {
            "runs_7d": await db.scalar(
                select(func.count(func.distinct(AgentTrace.run_id))).where(AgentTrace.created_at >= week_ago)
            ) or 0,
        },
        "latest_jobs": list(latest_jobs.values()),
    }


# ============================ 用户管理（改 / 删）============================

class AdminUserPatch(BaseModel):
    role: str | None = None            # USER / ADMIN
    is_verified: bool | None = None
    notify_enabled: bool | None = None


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: AdminUserPatch,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员改用户角色 / 验证状态 / 通知开关（含防锁死保护）。"""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "用户不存在")

    if body.role is not None:
        if body.role not in (Role.USER.value, Role.ADMIN.value):
            raise HTTPException(400, "非法角色")
        if target.id == admin.id and body.role != Role.ADMIN.value:
            raise HTTPException(400, "不能取消自己的管理员权限")
        # 降级管理员前，确保系统还有其他管理员
        if target.role == Role.ADMIN.value and body.role != Role.ADMIN.value:
            others = await db.scalar(
                select(func.count(User.id)).where(User.role == Role.ADMIN.value, User.id != target.id)
            )
            if not others:
                raise HTTPException(400, "系统需保留至少一名管理员")
        target.role = body.role
    if body.is_verified is not None:
        target.is_verified = body.is_verified
    if body.notify_enabled is not None:
        target.notify_enabled = body.notify_enabled

    await db.commit()
    return {
        "id": target.id,
        "role": target.role,
        "is_verified": target.is_verified,
        "notify_enabled": target.notify_enabled,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除用户（DB 级联清除其会话 / 对话 / 收藏 / 模型配置）。防锁死：不能删自己、不能删最后一名管理员。"""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.id == admin.id:
        raise HTTPException(400, "不能删除自己的账号")
    if target.role == Role.ADMIN.value:
        others = await db.scalar(
            select(func.count(User.id)).where(User.role == Role.ADMIN.value, User.id != target.id)
        )
        if not others:
            raise HTTPException(400, "系统需保留至少一名管理员")
    await db.delete(target)
    await db.commit()
    return {"deleted": user_id}


# ============================ 发送日志 ============================

@router.get("/send-logs")
async def list_send_logs(
    days: int = Query(7, ge=1, le=60),
    status: str | None = Query(None, description="sent / failed，不传=全部"),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """近 N 天发送日志：谁、哪天、哪些分类、成功/失败、错误原因。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(SendLog).where(SendLog.sent_at >= since)
    if status:
        stmt = stmt.where(SendLog.status == status)
    rows = (await db.scalars(stmt.order_by(SendLog.id.desc()).limit(limit))).all()
    return [
        {
            "id": r.id,
            "email": r.email,
            "digest_date": r.digest_date.isoformat(),
            "categories": r.categories or [],
            "status": r.status,
            "error": (r.error or "")[:300],
            "sent_at": _fmt(r.sent_at),
        }
        for r in rows
    ]
