"""问答 API：多轮研究问答（Agent 编排在 services/graph.py，此处负责会话持久化）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, touch_activity
from app.models import Chat, ChatMessage, User

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    chat_id: int | None = Field(default=None, description="不传=新建会话")
    question: str = Field(min_length=1, max_length=2000)


async def _load_history(db: AsyncSession, chat_id: int, user_id: int) -> list[dict]:
    """取最近 10 条消息作为多轮上下文。"""
    rows = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.chat_id == chat_id, ChatMessage.user_id == user_id)
            .order_by(ChatMessage.id.desc())
            .limit(10)
        )
    ).all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


@router.post("/chat")
async def chat(
    body: ChatIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await touch_activity(user, db)

    # 会话：续聊校验归属，新聊建会话（标题取问题前 30 字）
    if body.chat_id is not None:
        chat_row = await db.get(Chat, body.chat_id)
        if not chat_row or chat_row.user_id != user.id:
            raise HTTPException(404, "会话不存在")
    else:
        chat_row = Chat(user_id=user.id, title=body.question[:30])
        db.add(chat_row)
        await db.commit()

    history = await _load_history(db, chat_row.id, user.id)
    db.add(ChatMessage(chat_id=chat_row.id, user_id=user.id, role="user", content=body.question))
    await db.commit()

    # 多步研究 Agent（用户自带 LLM 配置优先，无则走系统配置）
    from app.models import UserLLMConfig
    from app.services.graph import run_chat
    from app.api.llm_config import _to_service_cfg

    cfg = None
    llm_row = await db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user.id))
    if llm_row:
        cfg = _to_service_cfg(llm_row)

    try:
        result = await run_chat(db, question=body.question, history=history, cfg=cfg)
    except Exception as e:  # 编排失败也要给用户反馈
        answer = f"抱歉，问答服务暂时不可用（{type(e).__name__}），请稍后重试。"
        result = {"answer": answer, "sources": []}

    db.add(ChatMessage(
        chat_id=chat_row.id,
        user_id=user.id,
        role="assistant",
        content=result["answer"],
        sources=result.get("sources", []),
    ))
    await db.commit()

    return {"chat_id": chat_row.id, "answer": result["answer"], "sources": result.get("sources", []), "skill": result.get("skill")}


@router.get("/chats")
async def list_chats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.scalars(
            select(Chat).where(Chat.user_id == user.id).order_by(Chat.updated_at.desc()).limit(50)
        )
    ).all()
    return [
        {"chat_id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in rows
    ]


@router.get("/chats/{chat_id}")
async def chat_detail(
    chat_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    chat_row = await db.get(Chat, chat_id)
    if not chat_row or chat_row.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    await db.refresh(chat_row)
    rows = (await db.scalars(
        select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.id)
    )).all()
    return {
        "chat_id": chat_row.id,
        "title": chat_row.title,
        "messages": [
            {"role": m.role, "content": m.content, "sources": m.sources, "created_at": m.created_at.isoformat()}
            for m in rows
        ],
    }
