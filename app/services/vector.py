"""pgvector 向量层：语义去重 + RAG 检索（与文章表同库联合查询）"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import business_today, settings
from app.models import Article
from app.services import llm


async def find_duplicates(
    db: AsyncSession, *, url_hash: str, embedding: list[float], category: str, since: date
) -> bool:
    """去重：url_hash 精确命中 或 同分类近期文章语义相似度超阈值。"""
    exists = await db.scalar(select(Article.id).where(Article.url_hash == url_hash).limit(1))
    if exists:
        return True
    if embedding is None:
        return False
    similar = await db.scalar(
        select(Article.id)
        .where(
            Article.category == category,
            Article.batch_date >= since,
            Article.embedding.is_not(None),
            Article.embedding.cosine_distance(embedding) < (1 - settings.dedup_similarity_threshold),
        )
        .limit(1)
    )
    return similar is not None


async def search(
    db: AsyncSession, query: str, *, top_k: int | None = None, days: int = 14, category: str | None = None
) -> list[Article]:
    """RAG 检索：查询向量化 → 余弦距离最近的文章。"""
    top_k = top_k or settings.rag_top_k
    embeddings = await llm.embed_texts([query])
    if not embeddings:
        return []
    since = business_today() - timedelta(days=days)
    stmt = (
        select(Article)
        .where(
            Article.batch_date >= since,
            Article.embedding.is_not(None),
            Article.summary != "",
        )
        .order_by(Article.embedding.cosine_distance(embeddings[0]))
        .limit(top_k)
    )
    if category:
        stmt = stmt.where(Article.category == category)
    return list((await db.scalars(stmt)).all())
