"""用户自带模型配置（BYOK）：问答走用户自己的 LLM（openai/anthropic 双协议）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user
from app.models import User, UserLLMConfig
from app.services.llm import LLMConfig, system_llm_config, test_config

router = APIRouter(prefix="/api/users/me/llm-config", tags=["llm-config"])


class LLMConfigIn(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic)$")
    base_url: str = Field(default="", max_length=1024)
    api_key: str = Field(default="", max_length=512)
    model_fast: str = Field(default="", max_length=128)
    model_strong: str = Field(default="", max_length=128)


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "****" + key[-4:] if len(key) > 10 else "****"


def _cfg_out(row: UserLLMConfig | None) -> dict:
    if row is None:
        s = system_llm_config()
        return {
            "using_system": True,
            "provider": s.provider,
            "base_url": s.base_url,
            "api_key_masked": _mask(s.api_key),
            "model_fast": s.model_fast,
            "model_strong": s.model_strong,
        }
    return {
        "using_system": False,
        "provider": row.provider,
        "base_url": row.base_url,
        "api_key_masked": _mask(row.api_key),
        "model_fast": row.model_fast,
        "model_strong": row.model_strong,
    }


async def _get_row(db: AsyncSession, user_id: int) -> UserLLMConfig | None:
    return (await db.scalars(
        select(UserLLMConfig).where(UserLLMConfig.user_id == user_id)
    )).first()


def _to_service_cfg(row: UserLLMConfig) -> LLMConfig:
    return LLMConfig(
        provider=row.provider, base_url=row.base_url, api_key=row.api_key,
        model_fast=row.model_fast, model_strong=row.model_strong, label="user",
    )


@router.get("")
async def get_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """当前生效配置（api_key 只回掩码；未配置时返回系统默认）。"""
    return _cfg_out(await _get_row(db, user.id))


@router.put("")
async def save_config(body: LLMConfigIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not body.model_fast and not body.model_strong:
        raise HTTPException(400, "至少填写一个模型名（model_fast 或 model_strong）")
    row = await _get_row(db, user.id)
    if row is None:
        row = UserLLMConfig(user_id=user.id)
        db.add(row)
    row.provider = body.provider
    row.base_url = body.base_url.strip()
    # api_key 留空 = 保留旧值（前端只回显掩码）
    if body.api_key and "****" not in body.api_key:
        row.api_key = body.api_key.strip()
    row.model_fast = body.model_fast.strip()
    row.model_strong = body.model_strong.strip()
    await db.commit()
    return _cfg_out(row)


@router.delete("")
async def clear_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """清除自带配置，回退系统默认。"""
    row = await _get_row(db, user.id)
    if row:
        await db.delete(row)
        await db.commit()
    return {"cleared": True}


class TestIn(LLMConfigIn):
    """允许测试未保存的配置（api_key 传 '****…' 掩码时自动用已保存的值）。"""


@router.post("/test")
async def test(body: TestIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    saved = await _get_row(db, user.id)
    api_key = body.api_key
    if not api_key or "****" in api_key:
        if saved is None:
            raise HTTPException(400, "api_key 为空且无已保存配置")
        api_key = saved.api_key
    cfg = LLMConfig(
        provider=body.provider, base_url=body.base_url.strip(), api_key=api_key,
        model_fast=body.model_fast.strip(), model_strong=body.model_strong.strip(),
    )
    if not (cfg.model_fast or cfg.model_strong):
        raise HTTPException(400, "至少填写一个模型名")
    return await test_config(cfg)
