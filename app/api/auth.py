"""认证 API：验证码 / 注册 / 登录 / 登出 / 找回密码 / 当前用户"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import email as email_svc
from app.core.deps import get_db, get_current_user, touch_activity
from app.core.security import (
    clear_session_cookie,
    create_session,
    destroy_session,
    hash_password,
    set_session_cookie,
    verify_password,
    COOKIE_NAME,
)
from app.models import Role, User, utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---- 请求/响应模型 ----

class SendCodeIn(BaseModel):
    email: EmailStr
    purpose: str = Field(pattern="^(register|reset)$")


class RegisterIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=8, max_length=64)


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=255)  # 管理员用户名非邮箱格式，登录不做 EmailStr 校验
    password: str = Field(min_length=1, max_length=64)


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=64)


class MeOut(BaseModel):
    id: int
    email: str
    role: str
    notify_enabled: bool
    subscribed_categories: list[str]
    created_at: str | None = None


def _me_out(u: User) -> MeOut:
    return MeOut(
        id=u.id,
        email=u.email,
        role=u.role,
        notify_enabled=u.notify_enabled,
        subscribed_categories=u.subscribed_categories or [],
        created_at=u.created_at.isoformat() if u.created_at else None,
    )


# ---- 接口 ----

@router.post("/send-code")
async def send_code(body: SendCodeIn, db: AsyncSession = Depends(get_db)):
    if not EMAIL_RE.match(body.email):
        raise HTTPException(400, "邮箱格式不正确")
    try:
        await email_svc.send_code_email(db, body.email.lower(), body.purpose)
    except ValueError as e:
        raise HTTPException(429, str(e))
    return {"message": "验证码已发送，请查收邮箱"}


@router.post("/register")
async def register(body: RegisterIn, response: Response, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()
    if not await email_svc.verify_code(db, email, "register", body.code):
        raise HTTPException(400, "验证码错误或已过期")
    exists = await db.scalar(select(User.id).where(User.email == email))
    if exists:
        raise HTTPException(409, "该邮箱已注册，请直接登录")
    user = User(email=email, password_hash=hash_password(body.password), is_verified=True)
    db.add(user)
    await db.commit()
    token = await create_session(db, user)
    set_session_cookie(response, token)
    return _me_out(user)


@router.post("/login")
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    user = (await db.scalars(select(User).where(User.email == body.email.lower()))).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    token = await create_session(db, user)
    user.last_login_at = utcnow()
    await db.commit()
    set_session_cookie(response, token)
    return _me_out(user)


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await destroy_session(db, token)
    clear_session_cookie(response)
    return {"message": "已退出登录"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordIn, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()
    if not await email_svc.verify_code(db, email, "reset", body.code):
        raise HTTPException(400, "验证码错误或已过期")
    user = (await db.scalars(select(User).where(User.email == email))).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"message": "密码已重置，请使用新密码登录"}


@router.get("/me")
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await touch_activity(user, db)
    return _me_out(user)


# ---- 管理员引导（.env 唯一修改途径）----

async def ensure_admin(db: AsyncSession) -> None:
    """应用启动时按 .env 同步管理员账号：不存在则创建，存在则同步密码，不走注册/找回。"""
    if not settings.admin_username or not settings.admin_password:
        return
    user = (await db.scalars(select(User).where(User.email == settings.admin_username))).first()
    if user is None:
        db.add(User(
            email=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role=Role.ADMIN.value,
            is_verified=True,
        ))
        await db.commit()
        print(f"[init] 已创建管理员 {settings.admin_username}")
    elif not verify_password(settings.admin_password, user.password_hash):
        user.password_hash = hash_password(settings.admin_password)
        await db.commit()
        print("[init] 已按 .env 同步管理员密码")
