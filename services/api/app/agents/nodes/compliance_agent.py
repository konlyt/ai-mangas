"""
合规检测 Agent 节点（ComplianceAgent）。

职责：
    对剧本、分镜描述等文本进行合规检测，
    简化版采用关键词过滤（如敏感词列表），
    将检测结果写入 state.compliance。

输入（来自 state）：
    - script: 结构化剧本。
    - storyboards: 分镜列表。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - compliance: 合规检测结果（含 passed、violations 列表）。
    - stage: 下一阶段（保持当前 stage 不变，由调用方决定）。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.logging import get_logger

logger = get_logger()

# 简化版敏感词列表（实际生产环境应接入专业合规服务）
SENSITIVE_KEYWORDS = ["暴力", "色情", "赌博", "毒品", "恐怖主义"]


async def compliance_agent_node(state: ProductionState) -> dict:
    """合规检测节点。

    对剧本与分镜文本进行关键词过滤式合规检测。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 compliance 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    script = state.get("script", {})
    storyboards = state.get("storyboards", []) or []

    logger.info(f"[compliance_agent] 开始合规检测 project_id={project_id}")

    violations = []

    # 检测剧本原始文本
    script_text = script.get("raw", "") if isinstance(script, dict) else ""
    for kw in SENSITIVE_KEYWORDS:
        if kw in script_text:
            violations.append({"source": "script", "keyword": kw})

    # 检测分镜描述与对白
    for sb in storyboards:
        text = f"{sb.get('visual_description', '')} {sb.get('dialogue', '')}"
        for kw in SENSITIVE_KEYWORDS:
            if kw in text:
                violations.append({"source": f"storyboard#{sb.get('sequence')}", "keyword": kw})

    compliance = {
        "passed": len(violations) == 0,
        "violations": violations,
        "checked_count": 1 + len(storyboards),
    }

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="compliance_agent",
        input_digest=f"script+storyboards",
        output_digest=truncate_digest(compliance),
    )

    return {"compliance": compliance}
