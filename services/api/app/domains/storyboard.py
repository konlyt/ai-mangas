"""
分镜领域服务。

提供分镜生成、查询、单条更新、批量操作（增删改排序）、
拖拽重排（SB-04）、连续性检查（SB-06）、确认等业务逻辑。
"""

import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import (
    Project,
    ProjectStatus,
    Revision,
    Script,
    Storyboard,
    StoryboardStatus,
)
from app.providers.llm.litellm_client import get_llm
from app.schemas.storyboard import (
    ContinuityCheckOut,
    ContinuityIssue,
    StoryboardBatchRequest,
    StoryboardGenerateRequest,
    StoryboardOut,
    StoryboardReorderRequest,
    StoryboardUpdateRequest,
)

logger = get_logger()


async def generate_storyboard(
    db: AsyncSession, project_id: int, req: Optional[StoryboardGenerateRequest] = None
) -> List[StoryboardOut]:
    """将剧本拆解为分镜并存储。

    从剧本的 scenes 字段提取场景，为每个场景生成一条分镜，
    包含景别、运镜、提示词等信息。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 分镜生成请求体（可空）。

    Returns:
        List[StoryboardOut]: 生成的分镜列表。

    Raises:
        BizException: 项目或剧本不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 查询剧本
    script_query = select(Script).where(Script.project_id == project_id)
    if req and req.script_id:
        script_query = script_query.where(Script.id == req.script_id)
    script_query = script_query.order_by(desc(Script.version), desc(Script.id))
    result = await db.execute(script_query)
    script = result.scalars().first()
    if script is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="剧本不存在，请先生成剧本")

    # 从剧本 scenes 拆分为分镜
    scenes = script.content.get("scenes", []) if isinstance(script.content, dict) else []
    if not scenes:
        scenes = [{"description": "默认分镜"}]

    shot_types = ["特写", "近景", "中景", "全景", "远景"]
    camera_movements = ["固定", "推镜", "拉镜", "摇镜", "移镜"]

    output: List[StoryboardOut] = []
    storyboards: List[Storyboard] = []
    for idx, sc in enumerate(scenes, start=1):
        description = sc.get("description", "") if isinstance(sc, dict) else str(sc)
        dialogue = sc.get("dialogue", "") if isinstance(sc, dict) else ""
        if not dialogue and isinstance(sc, dict):
            # 字段名兼容：mock/部分 LLM 返回 dialogues 列表
            # （[{"character": ..., "text": ...}]）而非 dialogue 字符串，
            # dialogue 为空时逐项提取文本并以换行拼接，保证台词不丢失
            dialogue_lines: List[str] = []
            for d in sc.get("dialogues") or []:
                if isinstance(d, dict):
                    text = str(d.get("text") or d.get("dialogue") or "").strip()
                else:
                    text = str(d or "").strip()
                if text:
                    dialogue_lines.append(text)
            dialogue = "\n".join(dialogue_lines)
        prompt = (
            f"动漫分镜，{description}；"
            f"景别：{shot_types[idx % len(shot_types)]}；"
            f"运镜：{camera_movements[idx % len(camera_movements)]}。"
        )

        storyboard = Storyboard(
            project_id=project_id,
            script_id=script.id,
            episode_id=req.episode_id if req else None,
            sequence=idx,
            shot_type=shot_types[idx % len(shot_types)],
            camera_movement=camera_movements[idx % len(camera_movements)],
            duration=5,
            visual_description=description,
            dialogue=dialogue,
            prompt=prompt,
            status=StoryboardStatus.PENDING,
        )
        db.add(storyboard)
        storyboards.append(storyboard)

    # 更新项目状态到 storyboard
    project.status = ProjectStatus.STORYBOARD
    await db.commit()
    # commit 后刷新对象以获取自增 id 和时间戳
    for sb in storyboards:
        await db.refresh(sb)
        output.append(StoryboardOut.model_validate(sb))
    return output


async def get_storyboard(db: AsyncSession, project_id: int) -> List[StoryboardOut]:
    """查询项目下的全部分镜（按 sequence 排序）。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        List[StoryboardOut]: 分镜列表。
    """
    result = await db.execute(
        select(Storyboard)
        .where(Storyboard.project_id == project_id)
        .order_by(Storyboard.sequence)
    )
    items = result.scalars().all()
    return [StoryboardOut.model_validate(s) for s in items]


async def reorder_storyboard(
    db: AsyncSession, project_id: int, req: StoryboardReorderRequest
) -> List[StoryboardOut]:
    """按传入的分镜 ID 顺序重写镜头序号（拖拽重排 SB-04）。

    校验项目存在、ordered_ids 与项目下全部分镜一一对应，
    在同一事务内先写入负数临时序号规避 uk_project_seq 唯一索引冲突，
    再按新顺序重写 sequence（1..n）。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 重排请求体，ordered_ids 为按新顺序排列的分镜 ID 列表。

    Returns:
        List[StoryboardOut]: 重排后的分镜列表（按新 sequence 升序）。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND；
            ordered_ids 缺失 / 多余 / 重复或与项目分镜不匹配时抛出 PARAM_ERROR。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    result = await db.execute(
        select(Storyboard).where(Storyboard.project_id == project_id)
    )
    items: Dict[int, Storyboard] = {s.id: s for s in result.scalars().all()}

    # 关键校验：ordered_ids 必须与项目现有分镜 ID 集合完全一致（缺失/多余/重复均拒绝）
    if sorted(req.ordered_ids) != sorted(items.keys()):
        raise BizException(
            code=ErrorCode.PARAM_ERROR,
            message="分镜 ID 列表与项目现有分镜不一致，无法重排",
        )

    # 先统一写入互不冲突的负数临时序号，避免 UPDATE 顺序触发唯一索引冲突
    for offset, sb in enumerate(items.values(), start=1):
        sb.sequence = -offset
    await db.flush()

    # 按新顺序重写 sequence（1..n）
    for new_seq, storyboard_id in enumerate(req.ordered_ids, start=1):
        items[storyboard_id].sequence = new_seq

    await db.commit()
    return await get_storyboard(db, project_id)


async def update_storyboard(
    db: AsyncSession, project_id: int, sequence: int, req: StoryboardUpdateRequest
) -> StoryboardOut:
    """更新单个分镜的字段。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        sequence: 镜头序号。
        req: 分镜更新请求体。

    Returns:
        StoryboardOut: 更新后的分镜。

    Raises:
        BizException: 分镜不存在时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Storyboard).where(
            Storyboard.project_id == project_id, Storyboard.sequence == sequence
        )
    )
    storyboard = result.scalar_one_or_none()
    if storyboard is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="分镜不存在")

    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(storyboard, field, value)

    await db.commit()
    await db.refresh(storyboard)
    return StoryboardOut.model_validate(storyboard)


async def batch_operations(
    db: AsyncSession, project_id: int, req: StoryboardBatchRequest
) -> List[StoryboardOut]:
    """批量执行分镜操作：新增、删除、重排序、更新。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 批量操作请求体。

    Returns:
        List[StoryboardOut]: 操作后的分镜列表。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    for op in req.operations:
        if op.op == "delete" and op.sequence is not None:
            result = await db.execute(
                select(Storyboard).where(
                    Storyboard.project_id == project_id,
                    Storyboard.sequence == op.sequence,
                )
            )
            sb = result.scalar_one_or_none()
            if sb:
                await db.delete(sb)

        elif op.op == "add":
            data = op.data or {}
            max_seq_result = await db.execute(
                select(Storyboard.sequence)
                .where(Storyboard.project_id == project_id)
                .order_by(desc(Storyboard.sequence))
                .limit(1)
            )
            max_seq = max_seq_result.scalar() or 0
            sb = Storyboard(
                project_id=project_id,
                script_id=data.get("script_id", 0),
                sequence=max_seq + 1,
                shot_type=data.get("shot_type"),
                camera_movement=data.get("camera_movement"),
                duration=data.get("duration", 5),
                visual_description=data.get("visual_description"),
                dialogue=data.get("dialogue"),
                prompt=data.get("prompt"),
                status=StoryboardStatus.PENDING,
            )
            db.add(sb)

        elif op.op == "update" and op.sequence is not None:
            result = await db.execute(
                select(Storyboard).where(
                    Storyboard.project_id == project_id,
                    Storyboard.sequence == op.sequence,
                )
            )
            sb = result.scalar_one_or_none()
            if sb and op.data:
                for field, value in op.data.items():
                    if hasattr(sb, field):
                        setattr(sb, field, value)

        elif op.op == "reorder":
            # data 为 {sequence: new_sequence} 映射
            data = op.data or {}
            for seq_str, new_seq in data.items():
                result = await db.execute(
                    select(Storyboard).where(
                        Storyboard.project_id == project_id,
                        Storyboard.sequence == int(seq_str),
                    )
                )
                sb = result.scalar_one_or_none()
                if sb:
                    sb.sequence = int(new_seq)

    await db.commit()
    return await get_storyboard(db, project_id)


def _parse_continuity_response(text: str) -> List[ContinuityIssue]:
    """解析 LLM 返回的连续性检查结果文本。

    兼容纯 JSON 与 ```json 围栏两种输出形式，仅提取首个 JSON 对象；
    对 severity 做白名单归一化，非法字段一律取默认值，解析失败返回空列表。

    Args:
        text: LLM 输出的原始文本。

    Returns:
        List[ContinuityIssue]: 解析出的问题列表，解析失败时为空列表。
    """
    cleaned = text.strip()
    # 剥离 Markdown 代码围栏
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    # 截取首个 { 到最后一个 } 之间的内容，容忍模型输出多余说明文字
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return []

    try:
        data = json.loads(cleaned[start : end + 1])
    except (ValueError, TypeError):
        return []

    allowed_severity = {"low", "medium", "high"}
    issues: List[ContinuityIssue] = []
    for raw in data.get("issues", []) or []:
        if not isinstance(raw, dict):
            continue
        between = [int(x) for x in raw.get("between", []) if isinstance(x, (int, float))]
        severity = str(raw.get("severity", "medium")).lower()
        issues.append(
            ContinuityIssue(
                between=between,
                type=str(raw.get("type", "")),
                message=str(raw.get("message", "")),
                severity=severity if severity in allowed_severity else "medium",
            )
        )
    return issues


async def continuity_check(db: AsyncSession, project_id: int) -> dict:
    """检查相邻分镜之间的衔接问题（SB-06）。

    取项目全部分镜（按 sequence 排序），调用 LLM 检查相邻分镜在
    角色 / 场景 / 时间 / 道具上的跳变问题。LLM 调用或解析失败时
    不抛出异常，返回 checked=False 与空问题列表，保证前端可正常渲染。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        dict: {"checked": bool, "issues": [...]} 结构。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND；
            项目下无分镜时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    storyboards = await get_storyboard(db, project_id)
    if not storyboards:
        raise BizException(code=ErrorCode.NOT_FOUND, message="分镜不存在，请先生成分镜")

    # 组装相邻分镜上下文，交由 LLM 审查衔接
    lines = [
        f"#{s.sequence} 景别:{s.shot_type or '未设置'} 运镜:{s.camera_movement or '未设置'} "
        f"时长:{s.duration}s 画面:{s.visual_description or '无'} 对白:{s.dialogue or '无'}"
        for s in storyboards
    ]
    messages = [
        {
            "role": "system",
            "content": "你是动漫分镜连续性审查专家，只输出 JSON，不要输出多余文字。",
        },
        {
            "role": "user",
            "content": (
                "以下是按播放顺序排列的分镜列表：\n"
                + "\n".join(lines)
                + "\n\n请逐一检查相邻两个分镜之间的衔接问题，包括："
                "角色跳变（角色凭空出现/消失、外貌不一致）、场景跳变（地点无过渡切换）、"
                "时间不连续（昼夜/时间线矛盾）、道具跳变（道具凭空出现/消失）。"
                '输出格式：{"issues": [{"between": [seq1, seq2], "type": "角色|场景|时间|道具", '
                '"message": "问题描述", "severity": "low|medium|high"}]}。'
                '若无问题输出 {"issues": []}。'
            ),
        },
    ]

    try:
        content = await get_llm().achat(messages, temperature=0.2)
        issues = _parse_continuity_response(content)
        result = ContinuityCheckOut(checked=True, issues=issues)
    except BizException as exc:
        # LLM 调用失败：降级返回未检查状态，避免打断前端流程
        logger.warning(f"[storyboard] 连续性检查 LLM 调用失败: {exc.message}")
        result = ContinuityCheckOut(checked=False, issues=[])

    return result.model_dump()


async def confirm_storyboard(db: AsyncSession, project_id: int) -> None:
    """确认分镜，推进到关键帧阶段并创建版本快照。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        None

    Raises:
        BizException: 项目或分镜不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    result = await db.execute(
        select(Storyboard).where(Storyboard.project_id == project_id)
    )
    storyboards = result.scalars().all()
    if not storyboards:
        raise BizException(code=ErrorCode.NOT_FOUND, message="分镜不存在，请先生成分镜")

    project.status = ProjectStatus.KEYFRAMES

    # 创建 revision 快照
    snapshot = {
        "storyboards": [
            {
                "sequence": s.sequence,
                "shot_type": s.shot_type,
                "prompt": s.prompt,
            }
            for s in storyboards
        ]
    }
    revision = Revision(
        project_id=project_id,
        stage="storyboard",
        snapshot=snapshot,
        created_by=project.user_id,
    )
    db.add(revision)
    await db.commit()
