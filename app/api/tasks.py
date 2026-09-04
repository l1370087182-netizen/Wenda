"""任务 API：运行状态查询（登录用户）+ 手动重跑/补发（管理员）"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, require_admin
from app.models import JobRun, User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/status")
async def task_status(
    days: int = Query(3, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """最近 N 天各任务运行状态。"""
    since = date.today() - timedelta(days=days)
    rows = (await db.scalars(
        select(JobRun).where(JobRun.date >= since).order_by(JobRun.id.desc()).limit(100)
    )).all()
    return [
        {
            "job": r.job,
            "date": r.date.isoformat(),
            "status": r.status,
            "error": r.error[:500],
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


class RerunIn(BaseModel):
    date: str | None = None  # YYYY-MM-DD，默认今天


@router.post("/run")
async def rerun(
    body: RerunIn | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员手动重跑当日采集流水线（成功后可手动触发补发）。"""
    from datetime import date as _date

    from app.services.graph import run_daily

    target = _date.fromisoformat(body.date) if body and body.date else _date.today()
    try:
        job_run = await run_daily(target)
    except Exception as e:
        raise HTTPException(500, f"重跑失败：{type(e).__name__}: {e}")
    return {
        "job_run_id": job_run.id,
        "date": job_run.date.isoformat(),
        "status": job_run.status,
        "error": job_run.error,
    }


@router.post("/send")
async def resend(
    body: RerunIn | None = None,
    admin: User = Depends(require_admin),
):
    """管理员手动补发当日日报（重跑采集成功后调用）。"""
    from app.services.scheduler import job_send_daily

    target = date.fromisoformat(body.date) if body and body.date else date.today()
    try:
        await job_send_daily(target)
    except Exception as e:
        raise HTTPException(500, f"补发失败：{type(e).__name__}: {e}")
    return {"message": f"{target.isoformat()} 日报补发已执行"}
