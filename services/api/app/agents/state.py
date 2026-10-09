"""
ProductionState（生产状态）定义模块。

本模块定义 LangGraph 状态图（StateGraph）在整个 AI 漫剧生产流水线中流转的状态数据结构。
状态采用 TypedDict 描述，覆盖从剧本、资产、分镜、关键帧、视频、配音、合成到审核的全链路。
"""

from typing import Optional, TypedDict


class ProductionState(TypedDict, total=False):
    """AI 漫剧生产流水线的全局状态。

    该状态在 LangGraph 的各个节点之间传递，每个节点返回一个增量字典，
    由 LangGraph 自动合并到全局状态中。

    Attributes:
        project_id: 关联的项目 ID。
        stage: 当前所处的生产阶段，取值：
            script/assets/storyboard/keyframes/video/voice/compose/review。
        raw_input: 用户的原始输入（如标题、题材、风格、原始文本等）。
        meta: 元数据，存放本次运行的上下文信息（用户 ID、trace_id 等）。
        script: 生成的结构化剧本数据。
        characters: 角色列表，每个元素为角色描述字典。
        scenes: 场景列表，每个元素为场景描述字典。
        storyboards: 分镜列表，每个元素为分镜描述字典。
        consistency: 一致性校验结果汇总。
        compliance: 合规检测结果汇总。
        composition: 最终合成结果数据。
        errors: 各节点产生的错误信息列表。
        revision_id: 关联的版本快照 ID（若有）。
        graph_run_id: 当前 Graph 执行的唯一标识，用于写入 agent_events。
    """

    project_id: int
    stage: str
    raw_input: dict
    meta: dict
    script: dict
    characters: list[dict]
    scenes: list[dict]
    storyboards: list[dict]
    consistency: dict
    compliance: dict
    composition: dict
    errors: list[dict]
    revision_id: Optional[int]
    graph_run_id: str
