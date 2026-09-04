"""技能 API：查看系统已装的 Agent 技能包"""
from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.services.skills import skill_registry

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills(user=Depends(get_current_user)):
    """已装技能目录（name + description），技能正文在问答命中时由 Agent 按需加载。"""
    return skill_registry.list_skills()
