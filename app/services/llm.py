"""LLM / Embedding 封装：OpenAI 兼容 API + 模型分层 + 并发闸门"""
import asyncio
import json

from openai import AsyncOpenAI

from app.config import settings

_sem = asyncio.Semaphore(settings.llm_concurrency)  # 全局并发闸门（2C2G / API 限流友好）

_client: AsyncOpenAI | None = None
_embed_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url or None)
    return _client


def embed_client() -> AsyncOpenAI:
    global _embed_client
    if _embed_client is None:
        _embed_client = AsyncOpenAI(
            api_key=settings.embedding_api_key or settings.llm_api_key,
            base_url=settings.embedding_base_url or settings.llm_base_url or None,
        )
    return _embed_client


async def chat(messages: list[dict], *, strong: bool = False, json_mode: bool = False) -> str:
    """单次对话补全。strong=True 走强模型，否则走轻量模型。"""
    model = settings.llm_model_strong if strong else settings.llm_model_fast
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    async with _sem:
        resp = await client().chat.completions.create(model=model, messages=messages, **kwargs)
    return resp.choices[0].message.content or ""


async def chat_json(messages: list[dict], *, strong: bool = False) -> dict:
    """强制 JSON 输出，解析失败重试一次。"""
    for attempt in range(2):
        raw = await chat(messages, strong=strong, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 1:
                raise ValueError(f"LLM 返回非 JSON：{raw[:200]}")
            messages = [*messages, {"role": "user", "content": "你刚才的输出不是合法 JSON，请重新只输出 JSON。"}]
    raise ValueError("unreachable")


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化（一次 API 调用）。"""
    if not texts:
        return []
    async with _sem:
        resp = await embed_client().embeddings.create(
            model=settings.embedding_model, input=[t[:4000] for t in texts]
        )
    return [d.embedding for d in resp.data]
