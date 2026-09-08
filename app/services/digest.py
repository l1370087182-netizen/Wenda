"""邮件/digest 渲染：单分类 digest、跨类洞察合并、失败友好提示"""
import html

from app.config import business_today
from app.models import Article, CATEGORY_SLUGS

CATEGORY_NAMES = {
    "tech": "科技",
    "geo": "地缘",
    "finance": "财经",
    "ai_tech": "AI 技术",
    "ai_news": "最新 AI 资讯",
    "github": "GitHub 热点项目",
    "insight": "今日关联",
}


def esc(s: str) -> str:
    return html.escape(s or "")


# ---- 单分类 digest（凌晨采集时生成草稿）----

def render_category_digest(category: str, articles: list[Article]) -> tuple[str, str]:
    """返回 (subject, body_html)。"""
    name = CATEGORY_NAMES.get(category, category)
    subject = f"六类日报 · {name} · {business_today().isoformat()}"
    rows = []
    for a in articles:
        score = f"{a.importance_score:.0f}" if a.importance_score is not None else "-"
        rows.append(f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #eee">
            <a href="{esc(a.url)}" style="color:#1a73e8;text-decoration:none;font-weight:bold">{esc(a.title)}</a>
            <div style="color:#666;font-size:13px;margin-top:4px">{esc(a.summary or "")}</div>
            <div style="color:#999;font-size:12px;margin-top:4px">
              {esc(a.source)} · 重要度 {score} · 影响分析：{esc((a.impact or "暂无")[:120])}
            </div>
          </td>
        </tr>""")
    body = f"""
    <h2 style="color:#1a73e8">📊 {name} · Top {len(articles)}</h2>
    <table style="border-collapse:collapse;width:100%">{''.join(rows)}</table>
    """
    return subject, body


# ---- 跨类洞察 ----

def render_insight(insights: list[dict]) -> tuple[str, str]:
    """insights: [{title, text, related_categories}] → (subject, body_html)。"""
    subject = f"六类日报 · 今日关联 · {business_today().isoformat()}"
    blocks = []
    for it in insights:
        cats = " × ".join(CATEGORY_NAMES.get(c, c) for c in it.get("related_categories", []))
        blocks.append(f"""
        <div style="border-left:3px solid #f4b400;padding:8px 12px;margin:10px 0;background:#fffbea">
          <strong>{esc(it.get("title", ""))}</strong>
          <div style="color:#444;font-size:14px;margin-top:4px">{esc(it.get("text", ""))}</div>
          <div style="color:#b06000;font-size:12px;margin-top:4px">关联分类：{esc(cats)}</div>
        </div>""")
    return subject, f"<h2 style='color:#f4b400'>🔗 今日关联</h2>{''.join(blocks)}"


# ---- 08:00 合并邮件（每天一封）----

def failure_notice_html(missing: list[str], error_summary: str) -> str:
    """某分类当日无数据时的友好提示：失败原因 + 建议操作。"""
    names = "、".join(CATEGORY_NAMES.get(c, c) for c in missing)
    return f"""
    <div style="border:1px solid #f0c020;background:#fff8e1;padding:12px;margin:12px 0;border-radius:6px">
      <strong>⚠️ 以下板块今日暂时缺席：{esc(names)}</strong>
      <div style="color:#555;font-size:13px;margin-top:6px">原因：{esc(error_summary or "信息源暂时不可用")}</div>
      <div style="color:#555;font-size:13px">建议：管理员可稍后手动重跑补发（POST /api/tasks/run）；
      若未补发，明日 08:00 会自动恢复。</div>
    </div>"""


def render_daily_email(
    sections: dict[str, str],
    *,
    insight_html: str | None = None,
    missing: list[str] | None = None,
    error_summary: str = "",
) -> str:
    """合并一封日报：订阅分类各一节 + 今日关联 + 失败提示。"""
    parts = [
        "<div style='max-width:680px;margin:0 auto;font-family:sans-serif'>",
        "<div style='background:#1a73e8;color:#fff;padding:14px 18px;border-radius:6px 6px 0 0'>"
        "<h1 style='margin:0;font-size:20px'>📰 六类资讯日报</h1></div>",
        "<div style='padding:16px;border:1px solid #eee;border-top:none;border-radius:0 0 6px 6px'>",
    ]
    if missing:
        parts.append(failure_notice_html(missing, error_summary))
    if insight_html:
        parts.append(insight_html)
    for cat in CATEGORY_SLUGS:
        if cat in sections:
            parts.append(sections[cat])
    parts.append(
        "<hr style='border:none;border-top:1px solid #eee;margin-top:16px'>"
        "<p style='color:#aaa;font-size:12px'>本邮件由六类资讯日报系统自动生成 · "
        "可在「我的设置」调整订阅分类或关闭通知</p></div></div>"
    )
    return "".join(parts)
