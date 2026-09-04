"""定时任务：07:00 采集 / 08:00 发送 + 失败兜底 + 管理员重跑"""
import asyncio
import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import settings
from app.core.security import cleanup_expired_sessions
from app.models import CATEGORY_SLUGS, Digest, SendLog, User, utcnow
from app.services import digest as digest_svc
from app.services.db import SessionFactory
from app.core.email import send_email

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None

CATEGORY_NAMES = digest_svc.CATEGORY_NAMES


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


async def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    tz = ZoneInfo(settings.timezone)
    sched = AsyncIOScheduler(timezone=tz)
    sched.add_job(job_collect_daily, CronTrigger(hour=settings.collect_hour, minute=0, timezone=tz),
                  id="collect_daily", max_instances=1, coalesce=True)
    sched.add_job(job_send_daily, CronTrigger(hour=settings.send_hour, minute=0, timezone=tz),
                  id="send_daily", max_instances=1, coalesce=True)
    sched.add_job(job_cleanup, CronTrigger(hour=3, minute=30, timezone=tz),
                  id="cleanup", max_instances=1, coalesce=True)
    sched.start()
    _scheduler = sched
    logger.info("调度器已启动：%s（%s）", [j.id for j in sched.get_jobs()], settings.timezone)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ============================== 07:00 采集 ==============================

async def job_collect_daily(target: date | None = None) -> None:
    """日报流水线：多 Agent 编排（graph.run_daily）。"""
    from app.services.graph import run_daily

    target = target or date.today()
    try:
        job_run = await run_daily(target)
        logger.info("collect_daily 完成：%s %s", target, job_run.status)
    except Exception:
        logger.exception("collect_daily 执行失败 %s", target)


# ============================== 08:00 发送 ==============================

async def _send_one(to: str, html: str, subject: str) -> None:
    for attempt in range(3):  # 指数退避重试
        try:
            await send_email(to, subject, html)
            return
        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt * 5)


async def job_send_daily(target: date | None = None) -> None:
    target = target or date.today()
    cutoff = utcnow() - timedelta(days=settings.active_days)

    async with SessionFactory() as db:
        # 当日 digest 与洞察
        digests = (await db.scalars(select(Digest).where(Digest.date == target))).all()
        by_cat = {d.category: d for d in digests}
        insight_html = by_cat["insight"].body_html if "insight" in by_cat else None
        missing = [c for c in CATEGORY_SLUGS if c not in by_cat]

        # 失败原因摘要（来自 job_runs）
        from app.models import JobRun

        jr = (await db.scalars(
            select(JobRun).where(JobRun.job == "collect_daily", JobRun.date == target)
            .order_by(JobRun.id.desc()).limit(1)
        )).first()
        error_summary = (jr.error if jr else "")[:200] or "信息源暂时不可用"

        if not digests:
            logger.warning("send_daily：%s 无任何 digest，跳过发送", target)
            return

        # 活跃 + 开启通知的用户
        users = (await db.scalars(
            select(User).where(
                User.notify_enabled.is_(True),
                User.last_login_at >= cutoff,
                User.role != "ADMIN",
            )
        )).all()

        for u in users:
            subscribed = [c for c in (u.subscribed_categories or []) if c in CATEGORY_SLUGS]
            if not subscribed:
                continue
            cats = [c for c in subscribed if c in by_cat]
            subscribed_missing = [c for c in subscribed if c in missing]
            if not cats and not subscribed_missing:
                continue  # 订阅内容既无 digest 也无需缺席提示
            sections = {c: by_cat[c].body_html for c in cats}
            html = digest_svc.render_daily_email(
                sections,
                insight_html=insight_html,
                missing=subscribed_missing,
                error_summary=error_summary,
            )
            subject = f"📰 六类资讯日报 · {target.isoformat()}"
            status, error = "sent", ""
            try:
                await _send_one(u.email, html, subject)
            except Exception as e:
                status, error = "failed", f"{type(e).__name__}: {e}"
                logger.warning("发信失败 %s: %s", u.email, e)
            db.add(SendLog(
                user_id=u.id, digest_date=target, email=u.email,
                categories=cats + (["insight"] if insight_html else []),
                status=status, error=error,
            ))
            await db.commit()

        # 标记 digest 已发送
        for d in digests:
            d.status, d.sent_at = "sent", utcnow()
        await db.commit()
        logger.info("send_daily 完成：%s，用户 %d 人", target, len(users))


# ============================== 03:30 清理 ==============================

async def job_cleanup() -> None:
    """过期会话 + 30 天前文章正文清理（保留行，正文置空省空间）。"""
    async with SessionFactory() as db:
        await cleanup_expired_sessions(db)
    logger.info("cleanup 完成")
