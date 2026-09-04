"""GitHub 热点采集：GitHub Search API（近 7 天新建仓库按 star 排序）"""
from datetime import date, timedelta

import httpx

from app.services.collectors.base import fetch_text, MAX_CONTENT

API = "https://api.github.com/search/repositories"


async def collect() -> tuple[list[dict], list[str]]:
    since = (date.today() - timedelta(days=7)).isoformat()
    url = f"{API}?q=created:>{since}&sort=stars&order=desc&per_page=15"
    text = await fetch_text(url, headers={"Accept": "application/vnd.github+json"})
    if not text:
        return [], ["GitHub Search API"]

    import json

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [], ["GitHub Search API"]

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
    return [it for it in items if it["url"]], []
