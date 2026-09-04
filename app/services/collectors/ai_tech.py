"""AI 技术类采集：arXiv cs.AI / cs.CL 最新论文"""
from app.services.collectors.base import collect_rss

SOURCES = [
    ("http://export.arxiv.org/rss/cs.AI", "arXiv cs.AI"),
    ("http://export.arxiv.org/rss/cs.CL", "arXiv cs.CL"),
]


async def collect() -> tuple[list[dict], list[str]]:
    return await collect_rss(SOURCES)
