"""密码哈希与会话管理"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Session, User, new_token, hash_token, utcnow

COOKIE_NAME = "session_token"


# ---- 密码 ----

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# ---- 会话（库里只存 token 的 sha256，泄露库也无法冒用）----

async def create_session(db: AsyncSession, user: User) -> str:
    token = new_token()
    expires = utcnow() + timedelta(days=settings.cookie_days)
    db.add(Session(user_id=user.id, token_hash=hash_token(token), expires_at=expires))
    await db.commit()
    return token


async def destroy_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == hash_token(token)))
    await db.commit()


async def cleanup_expired_sessions(db: AsyncSession) -> None:
    await db.execute(delete(Session).where(Session.expires_at < utcnow()))
    await db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.cookie_days * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # 生产环境走 HTTPS 后改为 True
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


# ---- 常量时间比较（验证码等场景）----

def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
