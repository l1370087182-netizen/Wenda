"""LangGraph 多 Agent 编排：
- 日报流水线（daily/rerun）：Supervisor → 采集 Agent×6（主源直通/异常换源）→ 去重入库 →
  分析 Agent（单次结构化调用）→ digest 生成 → 交叉洞察 → 主编审查（反思循环 ≤2 轮）
- 研究问答（chat）：问题路由 → 单轮快速通道 / 研究 Agent（拆解→并行检索→自检→综合）

设计约束：
- state 只存可序列化 JSON（Redis checkpointer 序列化需要）；db 会话经 config["configurable"] 传入
- LLM 未配置时优雅降级（评分默认值、摘要取正文截断），保证流水线在无 key 环境也能走通
"""
import asyncio
import importlib
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.models import Article, Digest, JobRun, CATEGORY_SLUGS, INSIGHT_SLUG, utcnow
from app.services import digest as digest_svc
from app.services import llm
from app.services.collectors.base import collect_rss, make_url_hash
from app.services.db import SessionFactory
from app.services.skills import skill_registry
from app.services.vector import find_duplicates, search as vector_search

logger = logging.getLogger(__name__)

CONTENT_SNIPPET = 2000          # state 中正文截断（防检查点膨胀）
MIN_ITEMS_HEALTHY = 5           # 低于此条数视为采集异常，触发换源决策
REVIEW_MAX_ROUNDS = 2           # 主编审查最多修订轮数
FALLBACK_HINT = "LLM API 不可用"  # 降级标记（邮件失败提示时给出原因）


# ============================== State ==============================

class NewsState(TypedDict, total=False):
    batch_id: str
    target_date: str
    raw_items: dict[str, list[dict]]            # cat -> raw items（content 已截断）
    category_reports: dict[str, dict]            # cat -> {status, items, failed_sources, error}
    review_round: int
    review_issues: list[dict]                    # [{category, comment}]
    errors: list[str]


# ============================== 采集 Agent ==============================

async def _web_search_fallback(query: str) -> tuple[list[dict], list[str]]:
    """兜底搜索工具：Google News RSS。"""
    from urllib.parse import quote_plus

    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    return await collect_rss([(url, f"Google News · {query}")])


async def node_collect_with_items(state: NewsState, config: RunnableConfig) -> dict:
    """Supervisor 分派 6 个采集 Agent 并行执行，产出 raw_items + 健康报告。"""
    deadline = datetime.fromisoformat(config["configurable"]["deadline"])
    results = await asyncio.gather(
        *(_collect_category_with_items(c, deadline) for c in CATEGORY_SLUGS)
    )
    raw_items, reports = {}, {}
    for cat, items, report in results:
        raw_items[cat] = [{**it, "content": (it.get("content") or "")[:CONTENT_SNIPPET]} for it in items]
        reports[cat] = report
    return {"raw_items": raw_items, "category_reports": reports}


async def _collect_category_with_items(cat: str, deadline: datetime):
    mod = importlib.import_module(f"app.services.collectors.{cat}")
    try:
        items, failed = await mod.collect()
    except Exception as e:
        items, failed = [], [f"{cat} 采集器异常: {type(e).__name__}"]

    report: dict[str, Any] = {"status": "success", "items": len(items), "failed_sources": failed, "error": ""}

    if (not items or len(items) < MIN_ITEMS_HEALTHY or failed) and datetime.now(timezone.utc) < deadline:
        try:
            decision = await llm.chat_json([
                {"role": "system", "content":
                    '你是采集换源决策器。给出一个中文搜索词（5-15字）。只输出 JSON：{"query": "..."}'},
                {"role": "user", "content": f"分类：{cat}；失败源：{failed}；已抓取：{len(items)} 条"},
            ])
            query = decision.get("query") or cat
        except Exception:
            query = cat
        fb_items, fb_failed = await _web_search_fallback(query)
        seen = {it["url"] for it in items}
        items += [it for it in fb_items if it["url"] not in seen]
        report["items"] = len(items)
        report["failed_sources"] = failed + [f"(搜索补源) {s}" for s in fb_failed]

    if not items:
        report["status"] = "failed"
        report["error"] = "主源与搜索补源均无数据；" + ("；".join(failed) if failed else "")
    elif failed:
        report["status"] = "partial"
        report["error"] = "部分源失败：" + "；".join(failed)
    return cat, items, report


# ============================== 去重入库 ==============================

async def node_ingest(state: NewsState, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    candidates = [it for items in state["raw_items"].values() for it in items]
    if not candidates:
        return {"ingested": 0}

    # 批量向量化（LLM 未配置时返回空 → 只做 url_hash 去重）
    embed_input = [f"{it['title']}\n{it.get('content', '')[:800]}" for it in candidates]
    try:
        vectors = await llm.embed_texts(embed_input)
    except Exception:
        vectors = []

    # 先并发算 url_hash（CPU），DB 操作串行（AsyncSession 不允许并发）
    ingested = 0
    since = target - timedelta(days=3)
    for i, it in enumerate(candidates):
        url_hash = make_url_hash(it["url"])
        emb = vectors[i] if i < len(vectors) else None
        try:
            dup = await find_duplicates(db, url_hash=url_hash, embedding=emb, category=_cat_of(state, it), since=since)
        except Exception:
            dup = False
        if dup:
            continue
        db.add(Article(
            category=_cat_of(state, it),
            title=it["title"][:500],
            url=it["url"],
            content=it.get("content", ""),
            source=it.get("source", ""),
            published_at=_parse_dt(it.get("published_at")),
            batch_date=target,
            url_hash=url_hash,
            embedding=emb,
        ))
        ingested += 1
    await db.commit()
    return {"ingested": ingested}


def _cat_of(state: NewsState, item: dict) -> str:
    for cat, items in state["raw_items"].items():
        if item in items:
            return cat
    return "tech"


def _parse_dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ============================== 分析 Agent ==============================

_ANALYSIS_SYSTEM = (
    "你是资讯分析 Agent。对给定资讯一次性返回结构化结果：\n"
    '- hot_score: 热度 0-100（讨论度/传播度）\n'
    '- importance_score: 重要度 0-100（对行业/社会的影响潜力）\n'
    '- summary: 80 字内中文摘要\n'
    '- impact: 40 字内中文影响分析\n'
    '只输出 JSON：{"hot_score": n, "importance_score": n, "summary": "...", "impact": "..."}'
)


async def node_analyse(state: NewsState, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    rows = (await db.scalars(
        select(Article).where(Article.batch_date == target, Article.hot_score.is_(None))
    )).all()
    if not rows:
        return {}

    # 1) 并发调 LLM（不碰 DB）；2) 串行回写
    async def one(a: Article) -> dict:
        try:
            r = await llm.chat_json([
                {"role": "system", "content": _ANALYSIS_SYSTEM},
                {"role": "user", "content": f"标题：{a.title}\n正文：{a.content[:1500] or a.summary}"},
            ])
            return {
                "hot": max(0, min(100, float(r.get("hot_score", 0)))),
                "imp": max(0, min(100, float(r.get("importance_score", 0)))),
                "summary": str(r.get("summary", ""))[:300],
                "impact": str(r.get("impact", ""))[:200],
            }
        except Exception as e:
            logger.warning("分析降级 %s: %s", a.id, e)
            return {"hot": 0.0, "imp": 0.0, "summary": a.content[:100], "impact": ""}

    results = await asyncio.gather(*(one(a) for a in rows))
    for a, r in zip(rows, results):
        a.hot_score, a.importance_score = r["hot"], r["imp"]
        a.summary, a.impact = r["summary"], r["impact"]
    await db.commit()
    return {}


# ============================== digest / 交叉洞察 ==============================

async def _top_articles(db: AsyncSession, target: date, category: str, n: int) -> list[Article]:
    rows = (await db.scalars(
        select(Article).where(Article.batch_date == target, Article.category == category)
        .order_by(Article.importance_score.desc().nulls_last(), Article.hot_score.desc().nulls_last())
        .limit(n)
    )).all()
    return list(rows)


async def _upsert_digest(db: AsyncSession, category: str, target: date, subject: str, body_html: str) -> None:
    stmt = pg_insert(Digest).values(
        category=category, date=target, subject=subject, body_html=body_html, status="draft"
    ).on_conflict_do_update(
        index_elements=["category", "date"], set_={"subject": subject, "body_html": body_html, "status": "draft"}
    )
    await db.execute(stmt)


async def node_digest(state: NewsState, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    for cat in CATEGORY_SLUGS:
        if state["category_reports"].get(cat, {}).get("status") == "failed":
            continue
        arts = await _top_articles(db, target, cat, 5)
        if not arts:
            continue
        subject, body = digest_svc.render_category_digest(cat, arts)
        await _upsert_digest(db, cat, target, subject, body)
    await db.commit()
    return {}


async def node_insight(state: NewsState, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    top3 = {}
    for cat in CATEGORY_SLUGS:
        arts = await _top_articles(db, target, cat, 3)
        if arts:
            top3[cat] = [f"{a.title}：{(a.summary or a.content)[:150]}" for a in arts]
    if len(top3) < 2:
        return {}

    feed = "\n".join(f"[{cat}] " + "；".join(titles) for cat, titles in top3.items())
    prompt = (
        "你是交叉洞察 Agent。以下是六类资讯各自的 Top3 摘要，请找出 1-3 条跨分类的关联事件链"
        "（如：地缘事件 → 油价 → 航运/芯片）。只输出 JSON：\n"
        '{"insights": [{"title": "...", "text": "80字内关联分析", "related_categories": ["geo","finance"]}]}\n'
        "related_categories 取值：tech/geo/finance/ai_tech/ai_news/github。若无关联，返回空数组。"
    )
    try:
        r = await llm.chat_json(
            [{"role": "system", "content": prompt}, {"role": "user", "content": feed}], strong=True
        )
        insights = r.get("insights", [])[:3]
    except Exception as e:
        logger.warning("交叉洞察降级: %s", e)
        insights = []
    if not insights:
        return {}

    subject, body = digest_svc.render_insight(insights)
    await _upsert_digest(db, INSIGHT_SLUG, target, subject, body)
    await db.commit()
    return {}


# ============================== 主编审查（反思循环）==============================

async def node_review(state: NewsState, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    round_no = state.get("review_round", 0)

    rows = (await db.scalars(select(Digest).where(Digest.date == target, Digest.status == "draft"))).all()
    if not rows:
        return {"review_issues": [], "review_round": round_no + 1}

    feed = "\n\n".join(f"【{digest_svc.CATEGORY_NAMES.get(r.category, r.category)}】\n{r.body_html[:1500]}" for r in rows)
    try:
        r = await llm.chat_json([
            {"role": "system", "content":
                "你是主编审查 Agent。审查日报各板块：事实矛盾、摘要空泛、评分与内容不符。"
                '只输出 JSON：{"pass": true/false, "issues": [{"category": "板块slug", "comment": "修改意见"}]}'
                "。category 取值：tech/geo/finance/ai_tech/ai_news/github/insight。最多 3 条 issue。"},
            {"role": "user", "content": feed},
        ], strong=True)
        issues = [] if r.get("pass") else r.get("issues", [])[:3]
    except Exception:
        issues = []  # 审查 LLM 不可用 → 直接放行，不阻塞发布

    # 达到修订上限 → 放行并记录
    if issues and round_no >= REVIEW_MAX_ROUNDS:
        return {"review_issues": [], "review_round": round_no + 1,
                "errors": state.get("errors", []) + [f"审查意见未完全消化（{len(issues)} 条）"]}
    return {"review_issues": issues, "review_round": round_no + 1}


async def node_revise(state: NewsState, config: RunnableConfig) -> dict:
    """按审查意见修订：对被点名的分类，重排末位文章并重新分析/渲染该板块。"""
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    for issue in state.get("review_issues", []):
        cat = issue.get("category")
        if cat == INSIGHT_SLUG:
            await _re_insight(db, target, issue.get("comment", ""))
        elif cat in CATEGORY_SLUGS:
            arts = await _top_articles(db, target, cat, 5)
            if not arts:
                continue
            tail = arts[-1]
            tail.importance_score = max(0, (tail.importance_score or 0) - 5)  # 轻推排名使板块内容轮换
            try:
                r = await llm.chat_json([
                    {"role": "system", "content": _ANALYSIS_SYSTEM + f"\n主编意见：{issue.get('comment', '')}"},
                    {"role": "user", "content": f"标题：{tail.title}\n正文：{tail.content[:1500]}"},
                ])
                tail.summary, tail.impact = str(r.get("summary", ""))[:300], str(r.get("impact", ""))[:200]
            except Exception:
                pass
            await db.commit()
            arts = await _top_articles(db, target, cat, 5)
            subject, body = digest_svc.render_category_digest(cat, arts)
            await _upsert_digest(db, cat, target, subject, body)
    await db.commit()
    return {"review_issues": []}


async def _re_insight(db: AsyncSession, target: date, comment: str) -> None:
    """按主编意见重新生成洞察（直接调用 insight 逻辑并附注意见）。"""
    state_ctx = {"target_date": target.isoformat()}
    del state_ctx  # 简化：复用 node_insight 前置数据组装
    top3 = {}
    for cat in CATEGORY_SLUGS:
        arts = await _top_articles(db, target, cat, 3)
        if arts:
            top3[cat] = [f"{a.title}：{(a.summary or a.content)[:150]}" for a in arts]
    feed = "\n".join(f"[{cat}] " + "；".join(titles) for cat, titles in top3.items())
    try:
        r = await llm.chat_json([
            {"role": "system", "content":
                "你是交叉洞察 Agent。结合主编意见重新输出跨类关联链。"
                '只输出 JSON：{"insights": [{"title": "...", "text": "...", "related_categories": []}]}'},
            {"role": "user", "content": f"主编意见：{comment}\n\n分类摘要：\n{feed}"},
        ], strong=True)
        insights = r.get("insights", [])[:3]
    except Exception:
        return
    if insights:
        subject, body = digest_svc.render_insight(insights)
        await _upsert_digest(db, INSIGHT_SLUG, target, subject, body)


# ============================== 汇聚 ==============================

async def node_finalize(state: NewsState, config: RunnableConfig) -> dict:
    db: AsyncSession = config["configurable"]["db"]
    job_run: JobRun = config["configurable"]["job_run"]
    reports = state.get("category_reports", {})
    statuses = [r.get("status") for r in reports.values()]
    if statuses and all(s == "failed" for s in statuses):
        job_run.status = "failed"
    elif "failed" in statuses or "partial" in statuses:
        job_run.status = "partial"
    else:
        job_run.status = "success"
    job_run.error = "；".join(
        f"{cat}: {r.get('error')}" for cat, r in reports.items() if r.get("error")
    )[:2000]
    job_run.finished_at = utcnow()
    await db.commit()
    return {}


def _route_review(state: NewsState) -> str:
    return "revise" if state.get("review_issues") else "finalize"


# ============================== 图构建 ==============================

def build_daily_graph():
    from langgraph.graph import END, StateGraph

    g = StateGraph(NewsState)
    g.add_node("collect", node_collect_with_items)
    g.add_node("ingest", node_ingest)
    g.add_node("analyse", node_analyse)
    g.add_node("digest", node_digest)
    g.add_node("insight", node_insight)
    g.add_node("review", node_review)
    g.add_node("revise", node_revise)
    g.add_node("finalize", node_finalize)

    g.set_entry_point("collect")
    g.add_edge("collect", "ingest")
    g.add_edge("ingest", "analyse")
    g.add_edge("analyse", "digest")
    g.add_edge("digest", "insight")
    g.add_edge("insight", "review")
    g.add_conditional_edges("review", _route_review, {"revise": "revise", "finalize": "finalize"})
    g.add_edge("revise", "review")   # 反思循环
    g.add_edge("finalize", END)
    return g


_checkpointer_cm = None


async def get_checkpointer():
    """Redis 检查点（断点续跑）；不可用时退化为内存检查点。"""
    global _checkpointer_cm
    if _checkpointer_cm is not None:
        return _checkpointer_cm
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        cm = AsyncRedisSaver.from_conn_string(settings.redis_url)
        cp = await cm.__aenter__()
        await cp.setup()
        _checkpointer_cm = cp
    except Exception as e:
        from langgraph.checkpoint.memory import MemorySaver

        logger.warning("Redis checkpointer 不可用，退化为内存：%s", e)
        _checkpointer_cm = MemorySaver()
    return _checkpointer_cm


async def run_daily(target: date) -> JobRun:
    """07:00 日报流水线入口（collect_daily / 管理员重跑共用）。"""
    async with SessionFactory() as db:
        job_run = JobRun(job="collect_daily", date=target, status="running")
        db.add(job_run)
        await db.commit()

        # 时间预算：08:00（本地时区）前 15 分钟为缓冲
        import zoneinfo

        tz = zoneinfo.ZoneInfo(settings.timezone)
        deadline = datetime.combine(date.today(), time(settings.send_hour, 0), tzinfo=tz).astimezone(timezone.utc) - timedelta(minutes=15)

        graph = build_daily_graph().compile(checkpointer=await get_checkpointer())
        await graph.ainvoke(
            {"batch_id": f"collect-{target}", "target_date": target.isoformat(),
             "raw_items": {}, "category_reports": {}, "review_round": 0, "review_issues": [], "errors": []},
            config={"configurable": {"db": db, "deadline": deadline.isoformat(), "job_run": job_run},
                    "thread_id": f"collect-{target}"},
        )
        await db.refresh(job_run)
        return job_run


# ============================== 研究问答（chat）==============================

_CHAT_ROUTE_SYSTEM = (
    '你是问答路由器。判断问题类型：简单事实/摘要类→factual；需要分析推理的复杂问题→analysis。'
    '另外判断问题是否匹配某个技能（技能目录见下方），匹配则给出技能名，否则 skill 为 null。'
    '只输出 JSON：{"type": "factual"|"analysis", "skill": "技能名|null"}'
)


def _route_messages(question: str) -> list[dict]:
    """路由提示词附带技能目录（渐进式披露第一级：只有 name+description）。"""
    return [
        {"role": "system", "content":
            f"{_CHAT_ROUTE_SYSTEM}\n\n可用技能：\n{skill_registry.list_skills_prompt()}"},
        {"role": "user", "content": question},
    ]


async def run_chat(db: AsyncSession, *, question: str, history: list[dict]) -> dict:
    """研究问答入口：路由（含技能匹配）→ 单轮快速通道 / 研究 Agent。返回 {answer, sources}。"""
    try:
        route = await llm.chat_json(_route_messages(question))
        qtype = route.get("type", "factual")
    except Exception:
        qtype = "factual"

    # 渐进式披露第二级：命中技能才加载正文
    skill_body = None
    skill_name = route.get("skill") if isinstance(route, dict) else None
    if skill_name and skill_name != "null":
        skill = skill_registry.get_skill(skill_name)
        if skill:
            skill_body = skill.body
        else:
            logger.warning("路由返回未知技能：%s", skill_name)

    if qtype == "factual":
        result = await _quick_answer(question, history, skill_body=skill_body)
    else:
        result = await _research_answer(question, history, skill_body=skill_body)
    result["skill"] = skill_name if (skill_name and skill_name != "null") else None
    return result


async def _quick_answer(question: str, history: list[dict], *, skill_body: str | None = None) -> dict:
    articles = await _search_articles(question)
    return await _synthesize(question, history, articles, strong=False, skill_body=skill_body)


async def _search_articles(query: str) -> list[Article]:
    async with SessionFactory() as db:
        try:
            return await vector_search(db, query, top_k=settings.rag_top_k)
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            return []


async def _research_answer(question: str, history: list[dict], *, skill_body: str | None = None) -> dict:
    """研究 Agent：拆解子问题 → 并行检索 → 证据自检（≤2 轮补充）→ 综合。"""
    # 1) 规划（命中技能时，按技能流程规划检索）
    plan_system = (
        f"你是研究规划 Agent。把问题拆解为 2-{settings.rag_max_subquestions} 个可独立检索的子问题。"
        '只输出 JSON：{"subquestions": ["...", "..."]}'
    )
    if skill_body:
        plan_system += f"\n\n用户问题命中了技能，请结合技能要求规划检索：\n{skill_body}"
    try:
        plan = await llm.chat_json([
            {"role": "system", "content": plan_system},
            {"role": "user", "content": question},
        ], strong=True)
        subqs = plan.get("subquestions", [])[: settings.rag_max_subquestions] or [question]
    except Exception:
        subqs = [question]

    # 2) 并行检索
    rounds_results = await asyncio.gather(*(_search_articles(q) for q in subqs))
    articles: dict[int, Article] = {}
    for group in rounds_results:
        for a in group:
            articles[a.id] = a

    # 3) 自检：证据充分性（最多补 1 轮）
    for _ in range(1):
        evidence = "\n".join(f"[{i}] {a.title}：{(a.summary or a.content)[:150]}" for i, a in enumerate(articles.values()))
        try:
            check = await llm.chat_json([
                {"role": "system", "content":
                    '你是证据审查器。判断已有检索证据是否足以回答问题。'
                    '只输出 JSON：{"enough": true/false, "followup_queries": ["补充检索词", ...]}'},
                {"role": "user", "content": f"问题：{question}\n\n证据：\n{evidence or '（无）'}"},
            ])
            if check.get("enough") or not check.get("followup_queries"):
                break
            extra = await asyncio.gather(
                *(_search_articles(q) for q in check["followup_queries"][:2])
            )
            for group in extra:
                for a in group:
                    articles[a.id] = a
        except Exception:
            break

    return await _synthesize(question, history, list(articles.values()), strong=True, skill_body=skill_body)


async def _synthesize(
    question: str, history: list[dict], articles: list[Article], *, strong: bool, skill_body: str | None = None
) -> dict:
    """综合作答：带编号引用；命中技能时按技能输出规范作答。"""
    context = "\n\n".join(
        f"[{i + 1}] 标题：{a.title}（来源：{a.source}）\n摘要：{a.summary}\n正文片段：{a.content[:600]}"
        for i, a in enumerate(articles)
    )
    sys_content = (
        "你是资讯问答助手。基于给定的资讯片段回答用户问题，用 [编号] 标注引用来源；"
        "证据不足时明确说明。用中文。"
    )
    if skill_body:
        sys_content += f"\n\n请严格按以下技能流程与输出规范作答：\n{skill_body}"
    msgs = [
        {"role": "system", "content": sys_content},
        *history[-6:],
        {"role": "user", "content": f"参考资料：\n{context or '（未检索到相关资讯）'}\n\n问题：{question}"},
    ]
    try:
        answer = await llm.chat(msgs, strong=strong)
    except Exception as e:
        answer = f"抱歉，问答服务暂时不可用（{type(e).__name__}）。若持续出现，请联系管理员检查 LLM API 配置。"
    sources = [{"article_id": a.id, "title": a.title, "url": a.url} for a in articles]
    return {"answer": answer, "sources": sources}
