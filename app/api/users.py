"""用户 API：通知与订阅设置"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, touch_activity
from app.models import CATEGORY_SLUGS, User

router = APIRouter(prefix="/api/users", tags=["users"])


class SettingsIn(BaseModel):
    notify_enabled: bool | None = None
    subscribed_categories: list[str] | None = Field(
        default=None, description=f"订阅分类，取值：{CATEGORY_SLUGS}"
    )


@router.put("/me/settings")
async def update_settings(
    body: SettingsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await touch_activity(user, db)
    if body.notify_enabled is not None:
        user.notify_enabled = body.notify_enabled
    if body.subscribed_categories is not None:
        invalid = set(body.subscribed_categories) - set(CATEGORY_SLUGS)
        if invalid:
            raise HTTPException(400, f"非法分类：{sorted(invalid)}")
        user.subscribed_categories = body.subscribed_categories
    await db.commit()
    return {
        "notify_enabled": user.notify_enabled,
        "subscribed_categories": user.subscribed_categories,
    }
