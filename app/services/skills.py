"""项目内置 Skill 系统：Agent 技能包扫描与渐进式披露

规范：遵循 Anthropic Agent Skills 格式——每个技能一个文件夹，SKILL.md 含
YAML frontmatter（name / description），正文为流程指令。

设计要点：
- 渐进式披露：路由阶段只注入 name+description（几十 token），
  命中后才加载正文——技能多时成本恒定
- 技能包随 app/ 打包进 Docker 镜像，加技能不需要改代码、不需要重建数据库
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    body: str          # SKILL.md 去掉 frontmatter 后的正文
    path: Path


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 `---\\nkey: value\\n---\\n` 头部，返回 (meta, body)。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, m.group(2).strip()


class SkillRegistry:
    def __init__(self, skills_dir: Path = SKILLS_DIR) -> None:
        self._dir = skills_dir
        self._cache: dict[str, Skill] | None = None

    def _scan(self) -> dict[str, Skill]:
        """扫描技能目录（带缓存；新技能需重启进程生效）。"""
        if self._cache is not None:
            return self._cache
        skills: dict[str, Skill] = {}
        if self._dir.exists():
            for md in sorted(self._dir.glob("*/SKILL.md")):
                try:
                    meta, body = _parse_frontmatter(md.read_text(encoding="utf-8"))
                    name = meta.get("name") or md.parent.name
                    skills[name] = Skill(
                        name=name,
                        description=meta.get("description", ""),
                        body=body,
                        path=md,
                    )
                except Exception as e:
                    logger.warning("技能包解析失败 %s: %s", md, e)
        self._cache = skills
        logger.info("Skill 注册完成：%s", list(skills) or "无技能")
        return skills

    # ---- 对外 API ----

    def list_skills(self) -> list[dict[str, str]]:
        """技能目录（注入路由提示词 / 展示用），只含 name + description。"""
        return [
            {"name": s.name, "description": s.description}
            for s in self._scan().values()
        ]

    def get_skill(self, name: str) -> Skill | None:
        """按名取技能正文（渐进式披露第二级：命中后才加载）。"""
        return self._scan().get(name)

    def list_skills_prompt(self) -> str:
        """渲染为提示词片段：一行一个技能。"""
        items = self.list_skills()
        if not items:
            return "（无）"
        return "\n".join(f"- {s['name']}：{s['description']}" for s in items)


skill_registry = SkillRegistry()
