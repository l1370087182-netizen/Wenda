"""LangGraph 多 Agent 编排：
- 日报流水线（daily/rerun）：Supervisor 中枢 → 采集 Agent×6（主源直通/异常换源）→ 去重入库 →
  分析 Agent → digest 生成 → 交叉洞察 → 主编审查（反思循环 ≤2 轮）→ 汇聚。
  Supervisor 是确定性编排中枢（零 LLM）：每个 worker 跑完都回到它，由它按 state 与
  时间预算用 Command(goto=…) 决定下一个 worker——坏天跳过昂贵阶段、临近截止跳过反思、
  失败分类有界重采。"智能"在 worker（采集/分析/审查 Agent），"调度"在 Supervisor。
- 研究问答（chat）：独立 LangGraph 子图——路由 →（factual 直通检索 / analysis 规划→并行检索
  ⇄证据自检循环）→ 综合作答；带 ChatState，命中技能则按技能流程规划与作答。

设计约束：
- state 只存可序列化 JSON（Redis checkpointer 序列化需要）；db 会话经 config["configurable"] 传入
- LLM 未配置时优雅降级（评分默认值、摘要取正文截断），保证流水线在无 key 环境也能走通
"""
import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import Command

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import business_today, settings
from app.models import AgentTrace, Article, Digest, JobRun, CATEGORY_SLUGS, INSIGHT_SLUG, utcnow
from app.services import digest as digest_svc
from app.services import llm
from app.services import sources as source_registry
from app.services.agent import AgentStep, run_agent
from app.services.collectors.base import make_url_hash
from app.services.db import SessionFactory
from app.services.skills import skill_registry
from app.services.vector import find_duplicates, search as vector_search

logger = logging.getLogger(__name__)

CONTENT_SNIPPET = 2000          # state 中正文截断（防检查点膨胀）
MIN_ITEMS_HEALTHY = 5           # 低于此条数视为采集异常，触发换源决策
REVIEW_MAX_ROUNDS = 2           # 主编审查最多修订轮数
FALLBACK_HINT = "LLM API 不可用"  # 降级标记（邮件失败提示时给出原因）
TRACE_INPUT_MAX = 1000          # 轨迹入参截断
TRACE_OUTPUT_MAX = 1500         # 轨迹结果截断


# ============================== 轨迹记录（Agent 可观测性）==============================
#
# 轨迹不进 state（避免 Redis 检查点膨胀），而是挂在 config["configurable"]["traces"] 的
# 内存 list 上：运行中各 agent 追加，流水线收尾（node_finalize）一次性批量落库。
# list.append 无 await，6 个分类采集 agent 并发追加也安全；traces=None 时全程静默跳过。

def _append_trace(traces: list | None, **row) -> None:
    if traces is None:
        return
    traces.append(row)


def _make_collect_on_step(traces: list | None, run_id: str, run_kind: str, cat: str):
    """为某分类采集 Agent 造 on_step 回调：把每步工具调用 / 终答写进 buffer。"""
    if traces is None:
        return None

    async def on_step(step: AgentStep) -> None:
        base = {
            "run_id": run_id, "run_kind": run_kind, "agent_name": f"collect:{cat}",
            "step": step.index, "model_tier": "fast", "latency_ms": step.latency_ms,
        }
        if step.tool_calls:
            for tc, tr in zip(step.tool_calls, step.tool_results):
                out = tr.get("result", "")
                if not isinstance(out, str):
                    out = json.dumps(out, ensure_ascii=False)
                _append_trace(
                    traces, **base, kind="tool", tool_name=tc.get("name"),
                    input=json.dumps(tc.get("arguments", {}), ensure_ascii=False)[:TRACE_INPUT_MAX],
                    output=out[:TRACE_OUTPUT_MAX],
                )
        else:
            _append_trace(traces, **base, kind="answer", tool_name=None, input="",
                          output=(step.text or "")[:TRACE_OUTPUT_MAX])

    return on_step


# ============================== State ==============================

class NewsState(TypedDict, total=False):
    batch_id: str
    target_date: str
    phase: str                                   # Supervisor 状态机：最近一次派发的 worker 名
    raw_items: dict[str, list[dict]]            # cat -> raw items（content 已截断）
    category_reports: dict[str, dict]            # cat -> {status, items, failed_sources, error, agent}
    recollect_tries: int                         # Supervisor 已触发的整批重采次数（有界）
    total_ingested: int                          # 去重入库后新增文章数
    review_round: int
    review_issues: list[dict]                    # [{category, comment}]
    errors: list[str]


# ============================== 采集 Agent ==============================

def _dedupe_items(items: list[dict]) -> list[dict]:
    """按 url 去重、保序（跨主源/换源合并时用）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        u = it.get("url")
        if u and u not in seen:
            seen.add(u)
            out.append(it)
    return out


# 采集 Agent 的工具清单（OpenAI function 格式，双协议由 llm 层翻译）
_COLLECT_TOOLS = [
    {
        "name": "list_sources",
        "description": "列出当前分类的所有可用信息源及其抓取状态（id / name / 是否已尝试）。无参数。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "fetch_source",
        "description": "按 id 抓取指定信息源，把新条目并入已收集集合并返回最新计数；可对疑似临时失败的源重试。",
        "parameters": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "信息源 id，取自 list_sources 结果"},
            },
            "required": ["source_id"],
        },
    },
]


async def _run_collect_agent(
    cat: str, all_sources: list, seed_items: list[dict], seed_failed: list[str], deadline: datetime,
    *, traces: list | None = None, run_id: str = "", run_kind: str = "daily",
):
    """主源不足时启动：采集 Agent 用工具自主换源 / 重试，尽力补足到 MIN_ITEMS_HEALTHY。

    返回 (collected_items, failed_list, info)。collected 已含 seed。
    LLM 未配置时安静降级——run_agent 直接返回 seed，不额外补源，流水线继续。
    """
    collected = list(seed_items)
    seen_urls = {it["url"] for it in collected if it.get("url")}
    tried = {s.id for s in all_sources[: source_registry.PRIMARY_FAST_COUNT]}
    failed: list[str] = list(seed_failed)
    cat_name = digest_svc.CATEGORY_NAMES.get(cat, cat)

    async def tool_exec(name: str, args: dict):
        if name == "list_sources":
            return {
                "category": cat,
                "target_items": MIN_ITEMS_HEALTHY,
                "collected": len(collected),
                "sources": [
                    {"id": s.id, "name": s.name, "tried": s.id in tried} for s in all_sources
                ],
            }
        if name == "fetch_source":
            sid = args.get("source_id") or args.get("id") or ""
            src = source_registry.get_source(sid)
            if src is None or src not in all_sources:
                return {"ok": False, "error": f"未知或不属于本分类的源：{sid}"}
            tried.add(src.id)
            its, err = await source_registry.fetch_source(src)
            added = 0
            for it in its:
                u = it.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    collected.append(it)
                    added += 1
            if err:
                failed.append(err)
            return {
                "ok": err is None,
                "source": src.name,
                "new_items": added,
                "total_collected": len(collected),
                "target_items": MIN_ITEMS_HEALTHY,
                "error": err,
                "sample_titles": [it["title"][:40] for it in its[:3]],
            }
        return {"ok": False, "error": f"未知工具：{name}"}

    system = (
        f"你是“{cat_name}”分类的采集 Agent，目标：收集至少 {MIN_ITEMS_HEALTHY} 条互不重复的资讯。"
        f"当前已收集 {len(collected)} 条。策略：先 list_sources 看清有哪些源，再 fetch_source 逐个抓取；"
        "某个源失败或条数太少就自主换下一个源，也可对疑似临时失败的源重试一次。"
        "达到目标条数、或所有源都试过仍不足时，停止调用工具并用一句话说明结果。"
    )
    user = (
        f"分类：{cat_name}（{cat}）。快路径已抓取 {len(seed_items)} 条；"
        f"失败源：{seed_failed or '无'}。请补足到至少 {MIN_ITEMS_HEALTHY} 条。"
    )

    result = await run_agent(
        system=system, user=user, tools=_COLLECT_TOOLS, tool_exec=tool_exec,
        strong=False, max_steps=4, deadline=deadline,
        on_step=_make_collect_on_step(traces, run_id, run_kind, cat),
    )
    info = {
        "steps": len(result.steps),
        "stop_reason": result.stop_reason,
        "tool_calls": result.tool_calls_total,
        "finished": result.finished,
    }
    logger.info("采集 Agent[%s] 结束：收集 %d 条，%d 步，stop=%s", cat, len(collected), info["steps"], info["stop_reason"])
    return collected, failed, info


async def node_collect_with_items(state: NewsState, config: RunnableConfig) -> dict:
    """分派采集 Agent 并行执行，产出 raw_items + 健康报告。

    每个分类走「快路径直通，异常才升级为 agent」：主源够用则零 LLM，
    否则由 _run_collect_agent 用工具循环自主换源。

    Supervisor 重采（recollect_tries>0）时只重跑上次 status=failed 的分类，
    保留已成功/部分成功的结果——给瞬时网络故障一次二次机会，又不浪费预算重抓好分类。
    """
    deadline = datetime.fromisoformat(config["configurable"]["deadline"])
    conf = config["configurable"]
    traces = conf.get("traces")
    run_id = conf.get("run_id", "")
    run_kind = conf.get("run_kind", "daily")
    prev_reports = state.get("category_reports", {}) or {}
    is_recollect = state.get("recollect_tries", 0) > 0

    if is_recollect:
        cats = [c for c in CATEGORY_SLUGS if prev_reports.get(c, {}).get("status") == "failed"]
    else:
        cats = list(CATEGORY_SLUGS)
    if not cats:
        return {}

    results = await asyncio.gather(*(
        _collect_category_with_items(c, deadline, traces=traces, run_id=run_id, run_kind=run_kind)
        for c in cats
    ))
    raw_items = dict(state.get("raw_items", {}) or {})   # 保留未重采分类
    reports = dict(prev_reports)
    for cat, items, report in results:
        raw_items[cat] = [{**it, "content": (it.get("content") or "")[:CONTENT_SNIPPET]} for it in items]
        reports[cat] = report
    return {"raw_items": raw_items, "category_reports": reports}


async def _collect_category_with_items(
    cat: str, deadline: datetime, *, traces: list | None = None, run_id: str = "", run_kind: str = "daily"
):
    """单分类采集：快路径（并行抓主源，零 LLM）→ 不足且有预算则升级采集 Agent 换源。"""
    all_sources = source_registry.get_sources(cat)
    if not all_sources:
        return cat, [], {
            "status": "failed", "items": 0, "failed_sources": [],
            "error": "该分类未配置信息源", "agent": False,
        }

    # ---- 快路径：并行抓前 PRIMARY_FAST_COUNT 个主源，零 LLM ----
    primary = all_sources[: source_registry.PRIMARY_FAST_COUNT]
    fast = await asyncio.gather(*(source_registry.fetch_source(s) for s in primary))
    items, failed = [], []
    for its, err in fast:
        items.extend(its)
        if err:
            failed.append(err)
    items = _dedupe_items(items)

    report: dict[str, Any] = {
        "status": "success", "items": len(items),
        "failed_sources": list(failed), "error": "", "agent": False,
    }

    # ---- 升级：主源不足且仍有时间预算 → 采集 Agent 自主换源 ----
    if len(items) < MIN_ITEMS_HEALTHY and datetime.now(timezone.utc) < deadline:
        items, agent_failed, info = await _run_collect_agent(
            cat, all_sources, items, failed, deadline,
            traces=traces, run_id=run_id, run_kind=run_kind,
        )
        failed = agent_failed
        report.update({
            "agent": True, "items": len(items), "failed_sources": list(failed),
            "agent_steps": info["steps"], "agent_tool_calls": info["tool_calls"],
            "agent_stop": info["stop_reason"],
        })

    if not items:
        report["status"] = "failed"
        report["error"] = "主源与采集 Agent 补源均无数据；" + ("；".join(failed) if failed else "")
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
        return {"total_ingested": 0}

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
    return {"total_ingested": ingested}


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
                "你是主编审查 Agent。逐板块审查日报：事实矛盾、摘要空泛套话、评分与内容明显不符、缺少关键信息。"
                '只输出 JSON：{"pass": true/false, "issues": [{"category": "板块slug", "comment": "修改指令"}]}。'
                "comment 必须是具体、可执行的修改指令（指出哪篇/哪里有什么问题 + 应如何改写），不要泛泛而谈。"
                "category 取值：tech/geo/finance/ai_tech/ai_news/github/insight。最多 3 条 issue；无实质问题则 pass=true。"},
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
    """按主编意见真修订：分类板块批量改写摘要/影响/校正评分；洞察重新生成。"""
    db: AsyncSession = config["configurable"]["db"]
    target = date.fromisoformat(state["target_date"])
    for issue in state.get("review_issues", []):
        cat = issue.get("category")
        comment = issue.get("comment", "")
        if cat == INSIGHT_SLUG:
            await _re_insight(db, target, comment)
        elif cat in CATEGORY_SLUGS:
            await _revise_category(db, target, cat, comment)
    await db.commit()
    return {"review_issues": []}


async def _revise_category(db: AsyncSession, target: date, cat: str, comment: str) -> None:
    """按主编意见改写整个板块：一次结构化调用修订 Top5 的摘要/影响，并校正与内容不符的评分。

    取代旧的"末位文章 importance_score 减 5"假修订——那只是让排名轮换，并未针对意见改内容。
    LLM 不可用时安静降级（保留原板块），不阻塞发布。
    """
    arts = await _top_articles(db, target, cat, 5)
    if not arts:
        return
    feed = "\n\n".join(
        f"[{i}] 标题：{a.title}\n正文：{(a.content or '')[:800]}\n"
        f"当前摘要：{a.summary or '（无）'}\n当前影响：{a.impact or '（无）'}\n"
        f"当前热度/重要度：{a.hot_score}/{a.importance_score}"
        for i, a in enumerate(arts)
    )
    try:
        r = await llm.chat_json([
            {"role": "system", "content":
                "你是日报修订 Agent。主编对该板块给出了修改指令，请据此改写每篇文章的 summary（80字内、具体不空泛）"
                "与 impact（40字内影响分析），并在 hot_score/importance_score 与内容明显不符时校正（0-100）。"
                "保持与原文事实一致，不要编造。只针对确有问题的文章修改，其余可原样返回。"
                '只输出 JSON：{"items":[{"index":0,"summary":"...","impact":"...","hot_score":n,"importance_score":n}]}，'
                "index 对应上面的编号。"},
            {"role": "user", "content": f"主编修改指令：{comment}\n\n板块文章：\n{feed}"},
        ], strong=True)
    except Exception as e:
        logger.warning("板块修订降级[%s]：%s", cat, e)
        return

    changed = False
    for it in r.get("items", []):
        idx = it.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(arts)):
            continue
        a = arts[idx]
        if it.get("summary"):
            a.summary = str(it["summary"])[:300]; changed = True
        if it.get("impact"):
            a.impact = str(it["impact"])[:200]; changed = True
        for field, key in (("hot_score", "hot_score"), ("importance_score", "importance_score")):
            v = it.get(key)
            if v is not None:
                try:
                    setattr(a, field, max(0, min(100, float(v)))); changed = True
                except (TypeError, ValueError):
                    pass
    if not changed:
        return
    await db.commit()
    arts = await _top_articles(db, target, cat, 5)   # 评分可能变化 → 重新取序
    subject, body = digest_svc.render_category_digest(cat, arts)
    await _upsert_digest(db, cat, target, subject, body)


async def _re_insight(db: AsyncSession, target: date, comment: str) -> None:
    """按主编意见重新生成洞察（复用 insight 的前置数据组装 + 附注意见）。"""
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

    # 轨迹批量落库（一次运行的所有 agent 步骤）；失败只记日志，绝不影响 job_run 收尾
    traces = config["configurable"].get("traces") or []
    if traces:
        try:
            db.add_all([AgentTrace(**t) for t in traces])
            await db.flush()
        except Exception as e:
            logger.warning("Agent 轨迹落库失败（已忽略）：%s", e)

    reports = state.get("category_reports", {})
    statuses = [r.get("status") for r in reports.values()]
    if statuses and all(s == "failed" for s in statuses):
        job_run.status = "failed"
    elif "failed" in statuses or "partial" in statuses:
        job_run.status = "partial"
    else:
        job_run.status = "success"
    # 采集错误 + Supervisor 编排决策（跳过阶段/未消化意见等）一并落库，便于排障
    parts = [f"{cat}: {r.get('error')}" for cat, r in reports.items() if r.get("error")]
    parts += [f"[编排] {e}" for e in state.get("errors", [])]
    job_run.error = "；".join(parts)[:2000]
    job_run.finished_at = utcnow()
    await db.commit()
    return {}


# ============================== Supervisor 编排中枢 ==============================

async def node_supervisor(state: NewsState, config: RunnableConfig) -> Command:
    """确定性编排中枢（零 LLM）：读 state + 时间预算，用 Command(goto=…) 决定下一个 worker。

    每个 worker 跑完都回到这里。phase 记录"最近派发的 worker"，据此推进状态机：
      ""→collect→(失败分类有界重采?)→ingest→(有可用结果?)→analyse→digest→insight
      →(还有预算?)→review→(有意见&有预算?)→revise→review… →finalize→END
    坏天 / 临近发送截止时主动跳过昂贵 LLM 阶段——把调度决策集中在一处，可观测、可控成本。
    """
    phase = state.get("phase", "")
    reports = state.get("category_reports", {}) or {}
    errors = list(state.get("errors", []) or [])

    conf = config["configurable"]
    deadline = datetime.fromisoformat(conf["deadline"])
    budget_left = datetime.now(timezone.utc) < deadline
    traces = conf.get("traces")
    run_id = conf.get("run_id", "")

    def _step_no() -> int:
        return sum(1 for t in (traces or []) if t.get("agent_name") == "supervisor")

    def go(next_node: str, **update) -> Command:
        _append_trace(traces, run_id=run_id, run_kind="daily", agent_name="supervisor",
                      step=_step_no(), kind="decision", tool_name=None,
                      input=phase or "start", output=next_node, model_tier="", latency_ms=0)
        return Command(goto=next_node, update={"phase": next_node, **update})

    def end(reason: str) -> Command:
        _append_trace(traces, run_id=run_id, run_kind="daily", agent_name="supervisor",
                      step=_step_no(), kind="decision", tool_name=None,
                      input=phase or "start", output=f"END（{reason}）", model_tier="", latency_ms=0)
        return Command(goto=END)

    if phase == "":                                   # 起步
        return go("collect")

    if phase == "collect":                            # 采集后：失败分类有界重采
        failed = [c for c, r in reports.items() if r.get("status") == "failed"]
        tries = state.get("recollect_tries", 0)
        all_failed = bool(reports) and all(r.get("status") == "failed" for r in reports.values())
        if all_failed and tries >= 1:
            return go("finalize", errors=errors + ["重采后仍全部分类失败"])
        if failed and tries < 1 and budget_left:
            logger.info("Supervisor：%d 个分类失败，触发第 %d 次重采", len(failed), tries + 1)
            return go("collect", recollect_tries=tries + 1)
        return go("ingest")

    if phase == "ingest":                             # 入库后：无可用结果则跳过昂贵阶段
        usable = [c for c, r in reports.items() if r.get("status") in ("success", "partial")]
        if not usable:
            return go("finalize", errors=errors + ["无可用采集结果，跳过分析与审查"])
        return go("analyse")

    if phase == "analyse":
        return go("digest")

    if phase == "digest":
        return go("insight")

    if phase == "insight":                            # 洞察后：临近截止则跳过反思循环
        if not budget_left:
            return go("finalize", errors=errors + ["临近发送截止，跳过主编审查"])
        return go("review")

    if phase == "review":                             # 审查后：有意见且还有预算才修订
        if state.get("review_issues") and budget_left:
            return go("revise")
        if state.get("review_issues"):
            return go("finalize", errors=errors + ["临近截止，未消化审查意见即发布"])
        return go("finalize")

    if phase == "revise":
        return go("review")

    if phase == "finalize":
        return end("finalize 完成")

    logger.warning("Supervisor：未知 phase=%r，直接结束（防死循环）", phase)
    return end("未知 phase 兜底")


# ============================== 图构建 ==============================

def build_daily_graph():
    from langgraph.graph import StateGraph

    g = StateGraph(NewsState)
    g.add_node("supervisor", node_supervisor)
    g.add_node("collect", node_collect_with_items)
    g.add_node("ingest", node_ingest)
    g.add_node("analyse", node_analyse)
    g.add_node("digest", node_digest)
    g.add_node("insight", node_insight)
    g.add_node("review", node_review)
    g.add_node("revise", node_revise)
    g.add_node("finalize", node_finalize)

    g.set_entry_point("supervisor")
    # 所有 worker 跑完都回到 Supervisor，由它用 Command 动态决定下一步
    for worker in ("collect", "ingest", "analyse", "digest", "insight", "review", "revise"):
        g.add_edge(worker, "supervisor")
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
    """日报流水线入口（凌晨采集 Job / 管理员重跑共用）。"""
    async with SessionFactory() as db:
        job_run = JobRun(job="collect_daily", date=target, status="running")
        db.add(job_run)
        await db.commit()

        # 时间预算：正常凌晨采集 → 08:00 发送前 15 分钟为硬截止；
        # 手动重跑时该截止可能已过 → 退化为 now+30min 的宽松墙钟预算，
        # 否则 Supervisor 会因 budget_left=False 跳过重采与主编审查反思循环。
        import zoneinfo

        tz = zoneinfo.ZoneInfo(settings.timezone)
        now = datetime.now(timezone.utc)
        send_deadline = (
            datetime.combine(business_today(), time(settings.send_hour, 0), tzinfo=tz)
            .astimezone(timezone.utc) - timedelta(minutes=15)
        )
        deadline = send_deadline if send_deadline > now else now + timedelta(minutes=30)

        graph = build_daily_graph().compile(checkpointer=await get_checkpointer())
        run_id = f"collect-{target}"
        await graph.ainvoke(
            {"batch_id": run_id, "target_date": target.isoformat(),
             "phase": "", "raw_items": {}, "category_reports": {},
             "recollect_tries": 0, "total_ingested": 0,
             "review_round": 0, "review_issues": [], "errors": []},
            config={"configurable": {"db": db, "deadline": deadline.isoformat(), "job_run": job_run,
                                     "run_id": run_id, "run_kind": "daily", "traces": []},
                    "thread_id": run_id},
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


class ChatState(TypedDict, total=False):
    """研究问答子图状态（无 checkpointer，可持有 Article ORM 对象）。"""
    question: str
    history: list[dict]
    qtype: str                       # factual | analysis
    skill_name: str | None
    skill_body: str | None
    pending_queries: list[str]       # 本轮 search 要检索的 query
    subquestions: list[str]
    articles: dict                   # id -> Article（去重累积）
    evidence_round: int              # 已做的自检补检索轮数
    need_more: bool                  # 自检判定是否还需补检索
    answer: str
    sources: list[dict]


def _chat_cfg(config: RunnableConfig):
    return config["configurable"].get("cfg")


async def node_chat_route(state: ChatState, config: RunnableConfig) -> dict:
    """路由：判定 factual/analysis + 技能匹配（渐进式披露第一级）。"""
    cfg = _chat_cfg(config)
    route: dict = {}
    try:
        route = await llm.chat_json(_route_messages(state["question"]), cfg=cfg)
        qtype = route.get("type", "factual")
    except Exception as e:
        logger.warning("问答路由失败，降级 factual：%s", e)
        qtype = "factual"

    skill_name = route.get("skill") if isinstance(route, dict) else None
    if skill_name in (None, "null"):
        skill_name = None
    skill_body = None
    if skill_name:
        skill = skill_registry.get_skill(skill_name)
        if skill:
            skill_body = skill.body          # 渐进式披露第二级：命中才加载正文
        else:
            logger.warning("路由返回未知技能：%s", skill_name)
            skill_name = None

    out: dict = {"qtype": qtype, "skill_name": skill_name, "skill_body": skill_body, "articles": {}}
    if qtype != "analysis":
        out["pending_queries"] = [state["question"]]   # factual 直接检索原问题
    return out


async def node_chat_plan(state: ChatState, config: RunnableConfig) -> dict:
    """研究规划：拆解子问题（命中技能时按技能流程规划）。"""
    cfg = _chat_cfg(config)
    question = state["question"]
    plan_system = (
        f"你是研究规划 Agent。把问题拆解为 2-{settings.rag_max_subquestions} 个可独立检索的子问题。"
        '只输出 JSON：{"subquestions": ["...", "..."]}'
    )
    if state.get("skill_body"):
        plan_system += f"\n\n用户问题命中了技能，请结合技能要求规划检索：\n{state['skill_body']}"
    try:
        plan = await llm.chat_json([
            {"role": "system", "content": plan_system},
            {"role": "user", "content": question},
        ], strong=True, cfg=cfg)
        subqs = plan.get("subquestions", [])[: settings.rag_max_subquestions] or [question]
    except Exception:
        subqs = [question]
    return {"subquestions": subqs, "pending_queries": subqs}


async def node_chat_search(state: ChatState, config: RunnableConfig) -> dict:
    """并行检索 pending_queries，结果按 article id 去重累积进 state。"""
    queries = state.get("pending_queries") or [state["question"]]
    groups = await asyncio.gather(*(_search_articles(q) for q in queries))
    articles = dict(state.get("articles") or {})
    for grp in groups:
        for a in grp:
            articles[a.id] = a
    return {"articles": articles, "pending_queries": []}


async def node_chat_selfcheck(state: ChatState, config: RunnableConfig) -> dict:
    """证据自检：不足则产出补充检索词、回 search（轮数受 settings 限制）。"""
    cfg = _chat_cfg(config)
    max_rounds = max(0, min(3, settings.rag_selfcheck_rounds))
    rnd = state.get("evidence_round", 0)
    if rnd >= max_rounds:
        return {"need_more": False}

    articles = state.get("articles") or {}
    evidence = "\n".join(
        f"[{i}] {a.title}：{(a.summary or a.content)[:150]}" for i, a in enumerate(articles.values())
    )
    try:
        check = await llm.chat_json([
            {"role": "system", "content":
                '你是证据审查器。判断已有检索证据是否足以回答问题。'
                '只输出 JSON：{"enough": true/false, "followup_queries": ["补充检索词", ...]}'},
            {"role": "user", "content": f"问题：{state['question']}\n\n证据：\n{evidence or '（无）'}"},
        ], cfg=cfg)   # FIX：此前漏传 cfg → BYOK 用户自检静默失败被 except 吞掉
    except Exception:
        return {"need_more": False}

    followups = check.get("followup_queries") or []
    if check.get("enough") or not followups:
        return {"need_more": False}
    return {"need_more": True, "pending_queries": followups[:2], "evidence_round": rnd + 1}


async def node_chat_synthesize(state: ChatState, config: RunnableConfig) -> dict:
    """综合作答：analysis 用 strong 模型，factual 用 fast。"""
    cfg = _chat_cfg(config)
    result = await _synthesize(
        state["question"], state.get("history", []), list((state.get("articles") or {}).values()),
        strong=state.get("qtype") == "analysis", skill_body=state.get("skill_body"), cfg=cfg,
    )
    return {"answer": result["answer"], "sources": result["sources"]}


def _route_after_route(state: ChatState) -> str:
    return "plan" if state.get("qtype") == "analysis" else "search"


def _route_after_search(state: ChatState) -> str:
    return "selfcheck" if state.get("qtype") == "analysis" else "synthesize"


def _route_after_selfcheck(state: ChatState) -> str:
    return "search" if state.get("need_more") else "synthesize"


def build_chat_graph():
    """研究问答子图：route →(factual)search→synthesize /(analysis)plan→search⇄selfcheck→synthesize。"""
    from langgraph.graph import StateGraph

    g = StateGraph(ChatState)
    g.add_node("route", node_chat_route)
    g.add_node("plan", node_chat_plan)
    g.add_node("search", node_chat_search)
    g.add_node("selfcheck", node_chat_selfcheck)
    g.add_node("synthesize", node_chat_synthesize)

    g.set_entry_point("route")
    g.add_conditional_edges("route", _route_after_route, {"plan": "plan", "search": "search"})
    g.add_edge("plan", "search")
    g.add_conditional_edges("search", _route_after_search, {"selfcheck": "selfcheck", "synthesize": "synthesize"})
    g.add_conditional_edges("selfcheck", _route_after_selfcheck, {"search": "search", "synthesize": "synthesize"})
    g.add_edge("synthesize", END)
    return g


_chat_graph = None


async def run_chat(*, question: str, history: list[dict], cfg=None) -> dict:
    """研究问答入口（LangGraph 子图）。返回 {answer, sources, skill}。

    cfg：用户自带 LLM 配置（BYOK），None 时用系统配置。
    无 checkpointer——问答是无状态请求/响应，多轮上下文由调用方经 history 传入。
    """
    global _chat_graph
    if _chat_graph is None:
        _chat_graph = build_chat_graph().compile()
    final = await _chat_graph.ainvoke(
        {"question": question, "history": history, "evidence_round": 0, "articles": {}},
        config={"configurable": {"cfg": cfg}},
    )
    return {
        "answer": final.get("answer", ""),
        "sources": final.get("sources", []),
        "skill": final.get("skill_name"),
    }


async def _search_articles(query: str) -> list[Article]:
    async with SessionFactory() as db:
        try:
            return await vector_search(db, query, top_k=settings.rag_top_k)
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            return []


async def _synthesize(
    question: str, history: list[dict], articles: list[Article], *, strong: bool, skill_body: str | None = None, cfg=None
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
        answer = await llm.chat(msgs, strong=strong, cfg=cfg)
    except Exception as e:
        answer = f"抱歉，问答服务暂时不可用（{type(e).__name__}）。若持续出现，请联系管理员检查 LLM API 配置。"
    sources = [{"article_id": a.id, "title": a.title, "url": a.url} for a in articles]
    return {"answer": answer, "sources": sources}
