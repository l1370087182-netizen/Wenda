"""FastAPI 依赖：数据库会话 / 鉴权 / 管理员 / 活跃度更新"""
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import COOKIE_NAME, hash_token
from app.models import Role, Session, User, utcnow
from app.services.db import SessionFactory


async def get_db():
    async with SessionFactory() as db:
        yield db


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    row = (
        await db.scalars(
            select(Session).where(Session.token_hash == hash_token(token))
        )
    ).first()
    if not row or row.expires_at < utcnow():
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    user = await db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def touch_activity(user: User, db: AsyncSession) -> None:
    """更新 last_used_at（节流：距上次超过 1 分钟才写库，避免每请求一次写）。"""
    now = utcnow()
    if user.last_used_at is None or now - user.last_used_at > timedelta(minutes=1):
        user.last_used_at = now
        await db.commit()
