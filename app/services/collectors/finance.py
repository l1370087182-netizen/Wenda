"""财经类采集：华尔街见闻 / CNBC"""
from app.services.collectors.base import collect_rss

SOURCES = [
    ("https://dedicated.wallstreetcn.com/rss.xml", "华尔街见闻"),
    ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC Top News"),
]


async def collect() -> tuple[list[dict], list[str]]:
    return await collect_rss(SOURCES)
