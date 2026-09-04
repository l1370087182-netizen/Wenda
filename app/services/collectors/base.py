"""采集公共工具：异步抓取 / RSS 解析 / HTML 清洗"""
import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 20
MAX_CONTENT = 2000  # 正文截断长度（字符）


async def fetch_text(url: str, *, headers: dict | None = None) -> str | None:
    """抓取 URL 文本，失败返回 None（由上层 Agent 决策换源）。"""
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA, **(headers or {})}, timeout=TIMEOUT, follow_redirects=True) as c:
            resp = await c.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.warning("fetch 失败 %s: %s", url, e)
        return None


def clean_html(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(" ", strip=True)[:MAX_CONTENT]


def parse_rss(xml_text: str, *, source: str, max_items: int = 15) -> list[dict]:
    """解析 RSS/Atom，输出统一结构 raw item。"""
    feed = feedparser.parse(xml_text)
    items: list[dict] = []
    for e in feed.entries[:max_items]:
        published = None
        for key in ("published_parsed", "updated_parsed"):
            if getattr(e, key, None):
                published = datetime(*e[key][:6], tzinfo=timezone.utc)
                break
        content = clean_html(getattr(e, "summary", "") or getattr(e, "description", ""))
        items.append({
            "title": (getattr(e, "title", "") or "").strip(),
            "url": getattr(e, "link", "") or "",
            "content": content,
            "source": source,
            "published_at": published.isoformat() if published else None,
        })
    return [it for it in items if it["title"] and it["url"]]


def make_url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()


async def collect_rss(sources: list[tuple[str, str]], *, max_items: int = 15) -> tuple[list[dict], list[str]]:
    """并行抓取多个 RSS 源。返回 (items, failed_sources)——失败源清单供采集 Agent/健康报告使用。"""
    import asyncio

    async def one(url: str, source: str) -> tuple[list[dict], str | None]:
        text = await fetch_text(url)
        if not text:
            return [], source
        try:
            return parse_rss(text, source=source, max_items=max_items), None
        except Exception as e:
            logger.warning("RSS 解析失败 %s: %s", url, e)
            return [], source

    results = await asyncio.gather(*(one(u, s) for u, s in sources))
    items, failed = [], []
    for its, fail in results:
        items.extend(its)
        if fail:
            failed.append(fail)
    return items, failed
