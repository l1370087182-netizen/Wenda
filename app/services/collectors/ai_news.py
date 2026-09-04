"""最新 AI 资讯采集：机器之心 / Google News 人工智能"""
from app.services.collectors.base import collect_rss

SOURCES = [
    ("https://www.jiqizhixin.com/rss", "机器之心"),
    ("https://news.google.com/rss/search?q=AI+OR+%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "Google News · AI"),
]


async def collect() -> tuple[list[dict], list[str]]:
    return await collect_rss(SOURCES)
