"""SMTP 发信 + 验证码（PG 存储 + 频率限流）"""
import asyncio
import random
import smtplib
import ssl
from datetime import timedelta
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import EmailCode, utcnow

# aiosmtplib 在部分事件循环 + Windows 组合下不稳，SMTP 为短连接低频操作，用线程池跑标准库实现
_sem = asyncio.Semaphore(2)


def _render_email(subject: str, html: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(settings.email_from_name, "utf-8")), settings.smtp_user))
    msg["To"] = ""
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def _smtp_send_sync(to: str, subject: str, html: str) -> None:
    msg = _render_email(subject, html)
    msg["To"] = to
    ctx = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=20) as s:
            s.login(settings.smtp_user, settings.smtp_pass)
            s.sendmail(settings.smtp_user, [to], msg.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(settings.smtp_user, settings.smtp_pass)
            s.sendmail(settings.smtp_user, [to], msg.as_string())


async def send_email(to: str, subject: str, html: str) -> None:
    async with _sem:
        await asyncio.to_thread(_smtp_send_sync, to, subject, html)


# ---- 验证码 ----

def generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


async def send_code_email(db: AsyncSession, email: str, purpose: str) -> None:
    """生成验证码入库并发送。触发频率限流时抛 ValueError。"""
    # 限流：同邮箱+用途在间隔内已发过 → 拒绝
    since = utcnow() - timedelta(seconds=settings.code_send_interval_seconds)
    recent = await db.scalar(
        select(EmailCode.id)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.created_at > since)
        .limit(1)
    )
    if recent:
        raise ValueError("发送过于频繁，请稍后再试")

    code = generate_code()
    db.add(EmailCode(
        email=email,
        code=code,
        purpose=purpose,
        expires_at=utcnow() + timedelta(minutes=settings.code_expire_minutes),
    ))
    await db.commit()

    purpose_name = "注册" if purpose == "register" else "重置密码"
    html = f"""
    <div style="max-width:480px;margin:0 auto;font-family:sans-serif">
      <h2>六类资讯日报 · 邮箱验证码</h2>
      <p>您正在进行<strong>{purpose_name}</strong>操作，验证码为：</p>
      <p style="font-size:32px;letter-spacing:8px;font-weight:bold;color:#1a73e8">{code}</p>
      <p style="color:#888">{settings.code_expire_minutes} 分钟内有效。若非本人操作，请忽略此邮件。</p>
    </div>"""
    await send_email(email, f"【六类资讯日报】{purpose_name}验证码", html)


async def verify_code(db: AsyncSession, email: str, purpose: str, code: str) -> bool:
    """校验验证码，通过则标记已用。"""
    row = (
        await db.scalars(
            select(EmailCode)
            .where(
                EmailCode.email == email,
                EmailCode.purpose == purpose,
                EmailCode.used_at.is_(None),
                EmailCode.expires_at > utcnow(),
            )
            .order_by(EmailCode.id.desc())
            .limit(1)
        )
    ).first()
    if not row or row.code != code:
        return False
    row.used_at = utcnow()
    await db.commit()
    return True
