"""AgentRunner：通用工具调用循环（ReAct 风格）。

把 llm.chat_with_tools 驱动成一个有预算的自主循环：
    LLM 决策 → 若请求工具则执行并回填 → 再决策 …… 直到给出终答 / 耗尽步数 / 超过时间预算。

设计要点：
- 步数预算（max_steps）+ 时间预算（deadline）双重护栏，避免在 2C2G 上失控刷调用。
- on_step 轨迹回调（P5 可视化用）：任何异常都吞掉，绝不因埋点拖垮 agent 主流程。
- 工具执行异常被捕获并以文本回填给模型，让 agent 自己看到错误、自主换招（而不是整轮崩掉）。
- 协议无关：消息用 llm 层的归一化格式，OpenAI / Anthropic 都能跑。
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.services import llm

logger = logging.getLogger(__name__)

# 工具执行器签名：async (tool_name, arguments) -> str | dict
ToolExec = Callable[[str, dict], Awaitable[Any]]
# 轨迹回调签名：async (AgentStep) -> None
OnStep = Callable[["AgentStep"], Awaitable[None]]


@dataclass
class AgentStep:
    """一轮 LLM 决策 + 其触发的工具执行结果。"""
    index: int
    text: str                       # 本轮助手文本（思考/终答）
    tool_calls: list[dict] = field(default_factory=list)    # [{name, arguments}]
    tool_results: list[dict] = field(default_factory=list)  # [{name, ok, result}]
    latency_ms: int = 0


@dataclass
class AgentResult:
    text: str                       # 终答文本（finished=False 时可能为空）
    steps: list[AgentStep] = field(default_factory=list)
    finished: bool = False          # True=模型主动给出终答；False=耗尽步数/超时/LLM 失败
    tool_calls_total: int = 0
    stop_reason: str = ""           # finished / max_steps / deadline / llm_error


async def _safe_on_step(on_step: OnStep | None, step: AgentStep) -> None:
    if not on_step:
        return
    try:
        await on_step(step)
    except Exception as e:  # 埋点失败不影响主流程
        logger.warning("agent 轨迹回调失败（已忽略）：%s", e)


async def run_agent(
    *,
    system: str,
    user: str,
    tools: list[dict],
    tool_exec: ToolExec,
    strong: bool = False,
    cfg: "llm.LLMConfig | None" = None,
    max_steps: int = 5,
    deadline: datetime | None = None,
    on_step: OnStep | None = None,
) -> AgentResult:
    """运行一个工具调用 agent。

    参数：
        system / user : 初始系统提示词与用户消息
        tools         : OpenAI function 格式工具清单（空列表 = 退化为单次补全）
        tool_exec     : async (name, arguments) -> str|dict，执行单个工具
        max_steps     : 最多决策轮数（每轮可触发多个工具）
        deadline      : aware datetime，超过则提前停（时间预算）
        on_step       : 每轮结束的轨迹回调（P5 落库）

    返回 AgentResult。tool_exec 的副作用（如累积抓取到的条目）由调用方闭包持有，
    因此即便 finished=False（耗尽预算），调用方仍能用已收集到的中间结果。
    """
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    steps: list[AgentStep] = []
    total_calls = 0
    final_text = ""
    stop_reason = "max_steps"

    for i in range(max_steps):
        if deadline is not None and datetime.now(timezone.utc) >= deadline:
            stop_reason = "deadline"
            logger.warning("run_agent 超过时间预算，提前停止（已 %d 轮）", i)
            break

        t0 = time.monotonic()
        try:
            resp = await llm.chat_with_tools(messages, tools, strong=strong, cfg=cfg)
        except Exception as e:
            stop_reason = "llm_error"
            logger.warning("run_agent LLM 调用失败，提前结束：%s", e)
            break
        latency = int((time.monotonic() - t0) * 1000)
        messages.append(resp.message)

        # 无工具调用 = 模型给出终答
        if not resp.tool_calls:
            final_text = resp.text
            step = AgentStep(index=i, text=resp.text, latency_ms=latency)
            steps.append(step)
            await _safe_on_step(on_step, step)
            stop_reason = "finished"
            break

        # 执行本轮请求的所有工具，结果回填
        tool_results: list[dict] = []
        for tc in resp.tool_calls:
            total_calls += 1
            try:
                out = await tool_exec(tc.name, tc.arguments)
                ok = True
            except Exception as e:
                out = f"工具执行失败：{type(e).__name__}: {e}"
                ok = False
            content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
            tool_results.append({"name": tc.name, "ok": ok, "result": content[:2000]})
            messages.append({
                "role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": content,
            })

        step = AgentStep(
            index=i,
            text=resp.text,
            tool_calls=[{"name": t.name, "arguments": t.arguments} for t in resp.tool_calls],
            tool_results=tool_results,
            latency_ms=latency,
        )
        steps.append(step)
        await _safe_on_step(on_step, step)

    return AgentResult(
        text=final_text,
        steps=steps,
        finished=stop_reason == "finished",
        tool_calls_total=total_calls,
        stop_reason=stop_reason,
    )
