"""科技类采集：36氪 / TechCrunch"""
from app.services.collectors.base import collect_rss

SOURCES = [
    ("https://36kr.com/feed", "36氪"),
    ("https://techcrunch.com/feed/", "TechCrunch"),
]


async def collect() -> tuple[list[dict], list[str]]:
    return await collect_rss(SOURCES)
