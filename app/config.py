"""应用配置：pydantic-settings 读取 .env"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 管理员（唯一修改途径：.env）----
    admin_username: str = "adminljj"
    admin_password: str = ""

    # ---- 会话 ----
    cookie_days: int = 7          # Cookie 有效期（天）
    active_days: int = 7          # N 天内登录过 = 活跃用户

    # ---- 定时任务 ----
    timezone: str = "Asia/Shanghai"
    collect_hour: int = 7         # 采集 Job
    send_hour: int = 8            # 发送 Job
    llm_concurrency: int = 8      # LLM 调用并发闸门

    # ---- SMTP（发件邮箱）----
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    email_from_name: str = "六类资讯日报"

    # ---- 验证码 ----
    code_expire_minutes: int = 10
    code_send_interval_seconds: int = 60   # 同邮箱两次发码最小间隔（限流）

    # ---- LLM / Embedding（OpenAI 兼容 API；provider 可选 anthropic）----
    llm_provider: str = "openai"   # openai / anthropic
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_fast: str = ""
    llm_model_strong: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024

    # ---- 存储 ----
    database_url: str = "postgresql+asyncpg://news:news@localhost:5432/news"
    redis_url: str = "redis://localhost:6379/0"

    # ---- 前端（开发期 Vite 独立服务器）----
    cors_origins: str = "http://localhost:5173"

    # ---- MCP ----
    mcp_admin_token: str = ""   # 管理类 MCP 工具（重跑/补发）的鉴权 token；留空=管理工具禁用

    # ---- RAG ----
    rag_top_k: int = 6                    # 每个子问题检索条数
    rag_max_subquestions: int = 4         # 研究 Agent 最多拆解子问题数
    dedup_similarity_threshold: float = 0.95  # 语义去重相似度阈值


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
