"""看板 API：六类 Top5（热度/重要度）+ 文章详情 + 交叉洞察"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, touch_activity
from app.models import Article, Digest, INSIGHT_SLUG, User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class ArticleItem(BaseModel):
    id: int
    category: str
    title: str
    url: str
    source: str
    published_at: str | None
    hot_score: float | None
    importance_score: float | None
    summary: str


def _item(a: Article) -> ArticleItem:
    return ArticleItem(
        id=a.id,
        category=a.category,
        title=a.title,
        url=a.url,
        source=a.source,
        published_at=a.published_at.isoformat() if a.published_at else None,
        hot_score=a.hot_score,
        importance_score=a.importance_score,
        summary=a.summary or "",
    )


@router.get("/top")
async def top_articles(
    date_str: str | None = Query(None, alias="date", description="YYYY-MM-DD，默认昨天"),
    category: str | None = Query(None, description="不传=全部六类"),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await touch_activity(user, db)
    day = date.fromisoformat(date_str) if date_str else date.today() - timedelta(days=1)

    stmt = select(Article).where(Article.batch_date == day)
    if category:
        stmt = stmt.where(Article.category == category)
    stmt = stmt.order_by(
        Article.importance_score.desc().nulls_last(), Article.hot_score.desc().nulls_last()
    )

    result: dict = {"date": day.isoformat(), "categories": {}}
    if category:
        rows = (await db.scalars(stmt.limit(limit))).all()
        result["categories"][category] = [_item(a) for a in rows]
        return result

    # 全部六类：一次查询按分类取 TopN（窗口函数）
    from sqlalchemy import func
    from sqlalchemy.orm import aliased

    rk = (
        func.row_number()
        .over(
            partition_by=Article.category,
            order_by=(Article.importance_score.desc().nulls_last(), Article.hot_score.desc().nulls_last()),
        )
        .label("rk")
    )
    subq = select(Article, rk).where(Article.batch_date == day).subquery()
    a_alias = aliased(Article, subq)
    rows = (
        await db.scalars(
            select(a_alias).where(subq.c.rk <= limit).order_by(a_alias.category, subq.c.rk)
        )
    ).all()
    for a in rows:
        result["categories"].setdefault(a.category, []).append(_item(a))
    return result


@router.get("/insight")
async def today_insight(
    date_str: str | None = Query(None, alias="date", description="YYYY-MM-DD，默认昨天"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当日跨类关联洞察（digests 中 category=insight 的行）。"""
    await touch_activity(user, db)
    day = date.fromisoformat(date_str) if date_str else date.today() - timedelta(days=1)
    row = (
        await db.scalars(
            select(Digest).where(Digest.category == INSIGHT_SLUG, Digest.date == day)
        )
    ).first()
    if not row:
        return {"date": day.isoformat(), "insight": None}
    return {"date": day.isoformat(), "insight": row.body_html}


@router.get("/articles/{article_id}")
async def article_detail(
    article_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await touch_activity(user, db)
    a = await db.get(Article, article_id)
    if not a:
        raise HTTPException(404, "文章不存在")
    return {
        **_item(a).model_dump(),
        "content": a.content,
        "impact": a.impact,
        "collected_at": a.collected_at.isoformat(),
        "batch_date": a.batch_date.isoformat(),
    }
