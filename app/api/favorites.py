"""收藏 API：登录用户即可收藏/取消收藏文章（无角色限制），按用户独立记录"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user
from app.models import Article, Favorite, User

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


async def _fav_article_ids(db: AsyncSession, user_id: int, article_ids: list[int] | None = None) -> set[int]:
    stmt = select(Favorite.article_id).where(Favorite.user_id == user_id)
    if article_ids is not None:
        if not article_ids:
            return set()
        stmt = stmt.where(Favorite.article_id.in_(article_ids))
    return set((await db.scalars(stmt)).all())


@router.post("/{article_id}/toggle")
async def toggle_favorite(
    article_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """切换收藏状态，返回切换后的状态。"""
    if not await db.get(Article, article_id):
        raise HTTPException(404, "文章不存在")
    row = (
        await db.scalars(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.article_id == article_id)
        )
    ).first()
    if row:
        await db.delete(row)
        await db.commit()
        return {"favorited": False}
    db.add(Favorite(user_id=user.id, article_id=article_id))
    await db.commit()
    return {"favorited": True}


@router.get("")
async def list_favorites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我的收藏列表（新→旧）。"""
    rows = (
        await db.execute(
            select(Article, Favorite.created_at)
            .join(Favorite, Favorite.article_id == Article.id)
            .where(Favorite.user_id == user.id)
            .order_by(Favorite.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": a.id,
            "category": a.category,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "hot_score": a.hot_score,
            "importance_score": a.importance_score,
            "summary": a.summary or "",
            "favorited": True,
            "favorited_at": fav.isoformat() if fav else None,
        }
        for a, fav in rows
    ]
