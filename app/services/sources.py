"""信息源注册表 + 抓取分派（境内可达优先）。

设计动机：原采集器把 Google News 当主源/兜底，境内服务器全部连不上，导致 geo / ai_news
每天整类失败。这里集中管理六类**实测境内可达**的源，并支持采集 Agent 按 id 取源、
主源不足时自主换源（见 services/agent.py + graph.py 采集节点）。

约定：
- 每类 sources 按优先级排序，靠前 = 主源；快路径只抓前 PRIMARY_FAST_COUNT 个（零 LLM）。
- kind="rss"：标准 RSS/Atom，走 base.fetch_text + base.parse_rss。
- kind="github"：GitHub Search API 专用解析（collectors.github.fetch_trending）。
- 同一个源 URL 不在多个分类间复用，避免全局 url_hash 去重把某类"饿死"。
"""
import logging
from dataclasses import dataclass

from app.services.collectors.base import fetch_text, parse_rss

logger = logging.getLogger(__name__)

PRIMARY_FAST_COUNT = 2   # 快路径并行抓取的主源数量（够用即零 LLM 直通）


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    kind: str = "rss"      # rss | github


# 六类源注册表（均为本机境内网络实测可达；36氪服务器侧验证过，保留为主源）
REGISTRY: dict[str, list[Source]] = {
    "tech": [
        Source("tech_36kr", "36氪", "https://36kr.com/feed"),
        Source("tech_sspai", "少数派", "https://sspai.com/feed"),
        Source("tech_ifanr", "爱范儿", "https://www.ifanr.com/feed"),
    ],
    "geo": [
        Source("geo_ft", "FT中文网", "https://www.ftchinese.com/rss/news"),
        Source("geo_chinanews", "中新网国际", "https://www.chinanews.com.cn/rss/importnews.xml"),
    ],
    "finance": [
        Source("fin_wscn", "华尔街见闻", "https://dedicated.wallstreetcn.com/rss.xml"),
        Source("fin_chinanews", "中新网财经", "https://www.chinanews.com.cn/rss/finance.xml"),
        Source("fin_xueqiu", "雪球", "https://xueqiu.com/hots/topic/rss"),
    ],
    "ai_tech": [
        Source("ait_arxiv_ai", "arXiv cs.AI", "http://export.arxiv.org/rss/cs.AI"),
        Source("ait_arxiv_cl", "arXiv cs.CL", "http://export.arxiv.org/rss/cs.CL"),
    ],
    "ai_news": [
        Source("ain_qbitai", "量子位", "https://www.qbitai.com/feed"),
        Source("ain_leiphone", "雷锋网", "https://www.leiphone.com/feed"),
    ],
    "github": [
        Source("gh_trending", "GitHub 近7日新星", "", kind="github"),
    ],
}


def get_sources(category: str) -> list[Source]:
    return REGISTRY.get(category, [])


def get_source(source_id: str) -> Source | None:
    for sources in REGISTRY.values():
        for s in sources:
            if s.id == source_id:
                return s
    return None


async def fetch_source(src: Source, *, max_items: int = 15) -> tuple[list[dict], str | None]:
    """抓取单个源，返回 (items, error)。error=None 表示成功。

    永不抛异常——所有失败都转成 error 字符串，交给上层 Agent 决策。
    """
    if src.kind == "github":
        from app.services.collectors import github

        return await github.fetch_trending()

    text = await fetch_text(src.url)
    if not text:
        return [], f"{src.name} 抓取失败"
    try:
        items = parse_rss(text, source=src.name, max_items=max_items)
    except Exception as e:
        return [], f"{src.name} 解析失败：{type(e).__name__}"
    if not items:
        return [], f"{src.name} 无有效条目"
    return items, None
