"""LLM 层：OpenAI / Anthropic 双协议适配 + 用户自带配置（BYOK）

URL 拼接规则（兼容火山方舟等非标准前缀）：
- 以 `#` 结尾 → 去掉 # 后作为**完整端点**原样使用（万能逃生门）
- 已以默认路径结尾 → 原样使用
- 否则 → base_url + 默认路径（openai: /chat/completions，anthropic: /v1/messages）

例（火山方舟 OpenAI 兼容前缀）：
  base_url = https://ark.cn-beijing.volces.com/api/v3
  → https://ark.cn-beijing.volces.com/api/v3/chat/completions

例（任意特殊端点，如 /api/plan 系路径）：
  base_url = https://ark.cn-beijing.volces.com/api/plan/chat/completions#
  → 原样使用

注意：Embedding 走系统配置（pgvector 中的向量必须与索引时同一模型，
用户的对话模型配置不影响检索向量）。
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_sem = asyncio.Semaphore(settings.llm_concurrency)  # 全局并发闸门

ANTHROPIC_VERSION = "2023-06-01"
JSON_HINT = "\n\n只输出 JSON，不要输出任何其他内容。"


@dataclass
class LLMConfig:
    provider: str = "openai"        # openai / anthropic
    base_url: str = ""
    api_key: str = ""
    model_fast: str = ""
    model_strong: str = ""
    label: str = "system"           # 来源标识（system / user）

    def model(self, strong: bool) -> str:
        m = self.model_strong if strong else self.model_fast
        return m or self.model_strong or self.model_fast


def system_llm_config() -> LLMConfig:
    return LLMConfig(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model_fast=settings.llm_model_fast,
        model_strong=settings.llm_model_strong,
        label="system",
    )


def _endpoint(base_url: str, default_path: str) -> str:
    """按头部规则拼接端点。"""
    base = (base_url or "").strip()
    if base.endswith("#"):
        return base[:-1]
    base = base.rstrip("/")
    if base.endswith(default_path):
        return base
    return base + default_path


# ============================== OpenAI 协议 ==============================

_openai_clients: dict[tuple, AsyncOpenAI] = {}


def _openai_client(cfg: LLMConfig) -> AsyncOpenAI:
    key = (cfg.base_url, cfg.api_key)
    if key not in _openai_clients:
        _openai_clients[key] = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url or None)
    return _openai_clients[key]


async def _chat_openai(cfg: LLMConfig, messages: list[dict], model: str, json_mode: bool) -> str:
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    async with _sem:
        resp = await _openai_client(cfg).chat.completions.create(
            model=model, messages=messages, **kwargs
        )
    return resp.choices[0].message.content or ""


# ============================== Anthropic 协议 ==============================

def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """anthropic 的 system 是独立参数。"""
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    return "\n\n".join(system_parts), rest


async def _chat_anthropic(cfg: LLMConfig, messages: list[dict], model: str, json_mode: bool) -> str:
    system, rest = _split_system(messages)
    if json_mode:
        system += JSON_HINT
    payload = {
        "model": model,
        "max_tokens": 4000,
        "messages": rest,
    }
    if system:
        payload["system"] = system
    url = _endpoint(cfg.base_url, "/v1/messages")
    headers = {"x-api-key": cfg.api_key, "anthropic-version": ANTHROPIC_VERSION}
    async with _sem:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
    data = resp.json()
    # 响应格式：{"content": [{"type": "text", "text": "..."}, ...]}
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


# ============================== 对外接口 ==============================

async def chat(messages: list[dict], *, strong: bool = False, json_mode: bool = False, cfg: LLMConfig | None = None) -> str:
    """单次对话补全。cfg=None 时用系统配置。"""
    c = cfg or system_llm_config()
    if not c.api_key or not (c.model_fast or c.model_strong):
        raise RuntimeError("LLM 未配置（api_key / model 为空）")
    model = c.model(strong) or c.model_fast
    if c.provider == "anthropic":
        return await _chat_anthropic(c, messages, model, json_mode)
    return await _chat_openai(c, messages, model, json_mode)


async def chat_json(messages: list[dict], *, strong: bool = False, cfg: LLMConfig | None = None) -> dict:
    """强制 JSON 输出，解析失败重试一次。"""
    for attempt in range(2):
        raw = await chat(messages, strong=strong, json_mode=True, cfg=cfg)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 1:
                raise ValueError(f"LLM 返回非 JSON：{raw[:200]}")
            messages = [*messages, {"role": "user", "content": "你刚才的输出不是合法 JSON，请重新只输出 JSON。"}]
    raise ValueError("unreachable")


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化——始终走系统 Embedding 配置（向量须与索引同模型）。"""
    if not texts:
        return []
    ec = settings.embedding_api_key or settings.llm_api_key
    base = settings.embedding_base_url or settings.llm_base_url or None
    key = (base, ec)
    if key not in _openai_clients:
        _openai_clients[key] = AsyncOpenAI(api_key=ec, base_url=base)
    async with _sem:
        resp = await _openai_clients[key].embeddings.create(
            model=settings.embedding_model, input=[t[:4000] for t in texts]
        )
    return [d.embedding for d in resp.data]


async def test_config(cfg: LLMConfig) -> dict:
    """连通性测试：ping 一次 fast 模型。返回 {ok, detail, latency_ms}。"""
    import time

    start = time.monotonic()
    try:
        reply = await chat(
            [{"role": "user", "content": "回复一个字：好"}],
            strong=False, cfg=cfg,
        )
        return {"ok": True, "detail": f"模型响应：{reply[:50]}", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}", "latency_ms": int((time.monotonic() - start) * 1000)}


async def detect_provider(base_url: str, api_key: str, model_fast: str, model_strong: str) -> dict:
    """自动识别协议类型：依次用 openai / anthropic 协议 ping，返回第一个通的。

    启发式排序：URL 含 anthropic 或模型名含 claude → 先试 anthropic。
    返回 {provider: "openai"|"anthropic"|None, detail, latency_ms, attempts}。
    """
    text = (base_url + " " + model_fast + " " + model_strong).lower()
    order = ["anthropic", "openai"] if ("anthropic" in text or "claude" in text) else ["openai", "anthropic"]

    attempts: list[str] = []
    for provider in order:
        cfg = LLMConfig(provider=provider, base_url=base_url, api_key=api_key,
                        model_fast=model_fast, model_strong=model_strong)
        r = await test_config(cfg)
        if r["ok"]:
            return {"provider": provider, "detail": r["detail"], "latency_ms": r["latency_ms"], "attempts": attempts}
        attempts.append(f"{provider}: {r['detail'][:150]}")

    return {"provider": None, "detail": "两种协议均失败；" + "；".join(attempts), "latency_ms": 0, "attempts": attempts}
