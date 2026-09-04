"""地缘类采集：Google News RSS（地缘政治 / 国际局势）"""
from app.services.collectors.base import collect_rss

_SOURCES = [
    ("https://news.google.com/rss/search?q=%E5%9C%B0%E7%BC%98%E6%94%BF%E6%B2%BB&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "Google News · 地缘政治"),
    ("https://news.google.com/rss/search?q=%E5%9B%BD%E9%99%85%E5%B1%80%E5%8A%BF&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "Google News · 国际局势"),
    ("https://news.google.com/rss/search?q=geopolitics&hl=en-US&gl=US&ceid=US:en", "Google News · Geopolitics"),
]


async def collect() -> tuple[list[dict], list[str]]:
    return await collect_rss(_SOURCES)
