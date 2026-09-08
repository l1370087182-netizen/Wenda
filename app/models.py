"""SQLAlchemy 模型：12 张表（users / email_codes / sessions / articles / digests / send_logs / job_runs / agent_traces / chats / chat_messages / favorites / user_llm_configs）"""
import hashlib
import uuid
from datetime import date, datetime, timezone
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import business_today, settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_token() -> str:
    """生成会话明文 token（仅出现在 Cookie 中，库里只存 hash）。"""
    return uuid.uuid4().hex + uuid.uuid4().hex


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Role(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


# 分类 slug（六类 + 交叉洞察）
CATEGORY_SLUGS = ("tech", "geo", "finance", "ai_tech", "ai_news", "github")
INSIGHT_SLUG = "insight"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.USER.value)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subscribed_categories: Mapped[list] = mapped_column(JSONB, default=lambda: list(CATEGORY_SLUGS))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class EmailCode(Base):
    __tablename__ = "email_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(6))
    purpose: Mapped[str] = mapped_column(String(16))  # register / reset
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256(cookie token)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(255), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    batch_date: Mapped[date] = mapped_column(Date, index=True, default=business_today)  # 所属日报日期
    hot_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256(url)
    embedding: Mapped[list | None] = mapped_column(Vector(settings.embedding_dim), nullable=True)

    __table_args__ = (Index("ix_articles_category_date", "category", "batch_date"),)


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32))  # 六类 slug 或 insight
    date: Mapped[date] = mapped_column(Date, index=True)
    subject: Mapped[str] = mapped_column(String(512), default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / sent / failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("category", "date", name="uq_digests_category_date"),)


class SendLog(Base):
    __tablename__ = "send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    digest_date: Mapped[date] = mapped_column(Date, index=True)
    email: Mapped[str] = mapped_column(String(255))
    categories: Mapped[list] = mapped_column(JSONB, default=list)  # 本次邮件包含的分类
    status: Mapped[str] = mapped_column(String(16), default="sent")  # sent / failed
    error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(32))  # collect_daily / send_daily
    date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/success/partial/failed
    error: Mapped[str] = mapped_column(Text, default="")  # 失败原因（支撑邮件友好提示）
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentTrace(Base):
    """多 Agent 运行轨迹：一条 = 某 agent 的一步（一次 LLM 决策 / 一个工具调用 / 一条编排决策）。

    run_id 把同一次运行的所有轨迹串起来（如 collect-2026-09-08），供管理后台"Agent 轨迹"可视化。
    由 services/graph.py 在运行中写入内存 buffer、流水线收尾时批量落库（避免并发共用 AsyncSession）。
    """

    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)          # collect-<date> / chat-<uuid>
    run_kind: Mapped[str] = mapped_column(String(16), default="daily")   # daily / chat
    agent_name: Mapped[str] = mapped_column(String(64), index=True)      # supervisor / collect:geo / research …
    step: Mapped[int] = mapped_column(Integer, default=0)                # agent 内步序
    kind: Mapped[str] = mapped_column(String(16), default="tool")        # tool / decision / answer
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input: Mapped[str] = mapped_column(Text, default="")                 # 工具入参 / 决策依据（截断）
    output: Mapped[str] = mapped_column(Text, default="")                # 工具结果 / 终答（截断）
    model_tier: Mapped[str] = mapped_column(String(8), default="")       # fast / strong / ""（无 LLM）
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_agent_traces_run_agent", "run_id", "agent_name", "step"),)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)  # [{article_id, title, url}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chat: Mapped[Chat] = relationship(back_populates="messages")


class Favorite(Base):
    """用户收藏：每个用户对文章的收藏状态（登录用户即可用，无角色限制）。"""

    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "article_id", name="uq_favorites_user_article"),)


class UserLLMConfig(Base):
    """用户自带模型配置（BYOK）：问答走用户自己的 LLM；Embedding/检索始终走系统配置。"""

    __tablename__ = "user_llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(16), default="openai")  # openai / anthropic
    base_url: Mapped[str] = mapped_column(String(1024), default="")
    api_key: Mapped[str] = mapped_column(String(512), default="")  # 只写不读（API 永不回传明文）
    model_fast: Mapped[str] = mapped_column(String(128), default="")
    model_strong: Mapped[str] = mapped_column(String(128), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
