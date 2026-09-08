"""GitHub 热点采集：GitHub Search API（近 7 天新建仓库按 star 排序）"""
import json
from datetime import timedelta

from app.config import business_today
from app.services.collectors.base import fetch_text, MAX_CONTENT

API = "https://api.github.com/search/repositories"


async def fetch_trending(*, days: int = 7, per_page: int = 15) -> tuple[list[dict], str | None]:
    """抓取近 N 天新建、按 star 排序的仓库。返回 (items, error)。error=None 表示成功。"""
    since = (business_today() - timedelta(days=days)).isoformat()
    url = f"{API}?q=created:>{since}&sort=stars&order=desc&per_page={per_page}"
    text = await fetch_text(url, headers={"Accept": "application/vnd.github+json"})
    if not text:
        return [], "GitHub Search API 抓取失败"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [], "GitHub Search API 解析失败"

    items = []
    for repo in data.get("items", []):
        stars = repo.get("stargazers_count", 0)
        desc = (repo.get("description") or "").strip()
        items.append({
            "title": f"{repo.get('full_name', '')} ★{stars}",
            "url": repo.get("html_url", ""),
            "content": f"{desc}（语言：{repo.get('language') or '未知'}，{stars} stars）"[:MAX_CONTENT],
            "source": "GitHub Trending",
            "published_at": repo.get("created_at"),
        })
    items = [it for it in items if it["url"]]
    if not items:
        return [], "GitHub Search API 无结果"
    return items, None


async def collect() -> tuple[list[dict], list[str]]:
    """向后兼容旧接口（registry 化之前的采集器约定）。"""
    items, error = await fetch_trending()
    return items, ([error] if error else [])
