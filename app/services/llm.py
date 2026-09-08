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
import time
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
    """按头部规则拼接端点。

    - `#` 结尾 → 完整端点原样使用
    - 已含完整默认路径 → 不重复拼接
    - 已含版本前缀（如 /v1、/v3，cc-switch 类代理常见写法）→ 只补剩余段：
      https://x.com/v1 + /v1/messages → https://x.com/v1/messages
    - 否则 → base + 默认路径
    """
    base = (base_url or "").strip()
    if base.endswith("#"):
        return base[:-1]
    base = base.rstrip("/")
    if base.endswith(default_path):
        return base
    first_seg = "/" + default_path.strip("/").split("/")[0]
    if base.endswith(first_seg):
        return base + default_path[len(first_seg):]
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


def _anthropic_headers(cfg: LLMConfig) -> dict:
    # 双头兼容：官方走 x-api-key，火山方舟/Claude Code 生态网关（cc-switch 等）走 Authorization Bearer
    return {
        "x-api-key": cfg.api_key,
        "Authorization": f"Bearer {cfg.api_key}",
        "anthropic-version": ANTHROPIC_VERSION,
    }


async def _anthropic_post(url: str, headers: dict, payload: dict, *, retries: int = 2) -> dict:
    """POST /v1/messages，带指数退避重试。

    429 / 5xx / 网络错误重试；其余 4xx（鉴权、参数错）直接抛，不浪费重试。
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with _sem:
                async with httpx.AsyncClient(timeout=90) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 400 <= status < 500 and status != 429:
                raise
            last = e
        except httpx.TransportError as e:
            last = e
        if attempt < retries:
            await asyncio.sleep(1.5 ** attempt)
    raise last  # type: ignore[misc]


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
    data = await _anthropic_post(url, _anthropic_headers(cfg), payload)
    # 响应格式：{"content": [{"type": "text", "text": "..."}, ...]}
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


# ============================== Tool calling（双协议归一化）==============================
#
# 归一化消息格式（OpenAI 风格，作为内部统一表示）：
#   assistant 带工具调用：{"role":"assistant","content":text,"tool_calls":[{"id","name","arguments":dict}]}
#   工具结果：           {"role":"tool","tool_call_id":id,"name":name,"content":str}
# 发送前按 provider 翻译成各自线上格式（OpenAI function calling / Anthropic tool_use）。


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResponse:
    """chat_with_tools 的归一化返回。"""
    text: str                    # 助手文本（无工具调用时即终答）
    tool_calls: list[ToolCall]   # 本轮请求执行的工具（空 = 终答）
    message: dict                # 归一化 assistant 消息，可直接 append 回 messages


def _tools_to_openai(tools: list[dict]) -> list[dict]:
    """tools 支持两种写法：完整 {"type":"function","function":{...}} 或裸 {"name","description","parameters"}。"""
    out = []
    for t in tools:
        fn = t["function"] if "function" in t else t
        out.append({
            "type": "function",
            "function": {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return out


def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        fn = t["function"] if "function" in t else t
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """归一化消息 → OpenAI 线上格式（tool_calls.arguments dict → JSON 字符串）。"""
    out = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for tc in m["tool_calls"]
                ],
            })
        elif role == "tool":
            content = m.get("content", "")
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            })
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """归一化消息 → Anthropic 线上格式。

    - 抽离 system 为独立参数
    - assistant.tool_calls → content 里的 tool_use blocks
    - 连续的 role=tool → 合并进一个 user turn 的 tool_result blocks（Anthropic 要求）
    """
    system_parts = [
        m["content"] for m in messages
        if m.get("role") == "system" and isinstance(m.get("content"), str)
    ]
    out: list[dict] = []
    pending: list[dict] = []

    def flush() -> None:
        nonlocal pending
        if pending:
            out.append({"role": "user", "content": pending})
            pending = []

    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        if role == "tool":
            content = m.get("content", "")
            pending.append({
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            })
            continue
        flush()
        if role == "assistant":
            blocks: list[dict] = []
            text = m.get("content")
            if isinstance(text, str) and text:
                blocks.append({"type": "text", "text": text})
            for tc in m.get("tool_calls") or []:
                args = tc.get("arguments", {})
                if not isinstance(args, dict):
                    try:
                        args = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": args,
                })
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        else:  # user
            out.append({"role": "user", "content": m.get("content", "")})
    flush()
    return "\n\n".join(system_parts), out


async def _chat_openai_tools(cfg: LLMConfig, messages: list[dict], model: str, tools: list[dict]) -> ToolResponse:
    kwargs = {}
    if tools:
        kwargs = {"tools": _tools_to_openai(tools), "tool_choice": "auto"}
    async with _sem:
        resp = await _openai_client(cfg).chat.completions.create(
            model=model, messages=_to_openai_messages(messages), **kwargs
        )
    msg = resp.choices[0].message
    calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return ToolResponse(
        text=msg.content or "",
        tool_calls=calls,
        message={
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in calls],
        },
    )


async def _chat_anthropic_tools(cfg: LLMConfig, messages: list[dict], model: str, tools: list[dict]) -> ToolResponse:
    system, anth = _to_anthropic_messages(messages)
    payload: dict = {"model": model, "max_tokens": 4000, "messages": anth}
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = _tools_to_anthropic(tools)
    url = _endpoint(cfg.base_url, "/v1/messages")
    data = await _anthropic_post(url, _anthropic_headers(cfg), payload)

    text_parts, calls = [], []
    for b in data.get("content", []):
        if b.get("type") == "text":
            text_parts.append(b.get("text", ""))
        elif b.get("type") == "tool_use":
            calls.append(ToolCall(id=b.get("id", ""), name=b.get("name", ""), arguments=b.get("input", {}) or {}))
    text = "".join(text_parts)
    return ToolResponse(
        text=text,
        tool_calls=calls,
        message={
            "role": "assistant",
            "content": text,
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in calls],
        },
    )


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


async def chat_with_tools(
    messages: list[dict], tools: list[dict], *, strong: bool = False, cfg: LLMConfig | None = None
) -> ToolResponse:
    """带工具的单轮对话：返回归一化 ToolResponse（含 text / tool_calls / 可回填的 assistant message）。

    tools 用 OpenAI function 格式（或裸 {name,description,parameters}）；Anthropic 协议自动翻译。
    这是所有"真 agent 工具循环"的底座，由 services/agent.py 的 run_agent 驱动多轮。
    """
    c = cfg or system_llm_config()
    if not c.api_key or not (c.model_fast or c.model_strong):
        raise RuntimeError("LLM 未配置（api_key / model 为空）")
    model = c.model(strong) or c.model_fast
    if c.provider == "anthropic":
        return await _chat_anthropic_tools(c, messages, model, tools)
    return await _chat_openai_tools(c, messages, model, tools)


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
