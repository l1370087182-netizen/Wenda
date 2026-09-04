"""管理员 API：用户管理（仅 ADMIN 角色）"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_admin
from app.models import User

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
