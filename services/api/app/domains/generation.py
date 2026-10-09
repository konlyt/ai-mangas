"""
批量生成领域服务。

为分镜创建关键帧（image）、视频（video）、语音（tts）任务，
写入 tasks 表，状态为 queued，由 ARQ Worker 异步执行。
另提供视频片段降级换模重新生成（VID-07）能力。
"""

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import (
    Project,
    QueueName,
    Storyboard,
    Task,
    TaskStatus,
    TaskType,
)
from app.schemas.generate import (
    GenerateRequest,
    GenerateResponse,
    VideoRegenerateRequest,
    VideoRegenerateResponse,
)

logger = get_logger()

# 任务类型 → ARQ 任务函数名映射（与 tasks/worker.py WorkerSettings.functions 注册一致）
_TASK_ARQ_FUNC_NAMES: dict = {
    TaskType.IMAGE: "generate_image",
    TaskType.VIDEO: "generate_video",
    TaskType.TTS: "generate_tts",
}


async def _enqueue_generation_tasks(task_type: TaskType, task_ids: List[int]) -> None:
    """批量投递生成任务到对应 ARQ 队列。

    按 task_type 映射到 worker 注册的任务函数（generate_image /
    generate_video / generate_tts），逐个投递任务 ID。
    Redis / arq 不可用时仅记录告警、不中断主流程（与 regenerate_video
    的降级策略一致），任务保持 queued 状态待重试投递。

    Args:
        task_type: 任务类型（决定投递到的 ARQ 任务函数）。
        task_ids: 待投递的任务 ID 列表。

    Returns:
        None
    """
    if not task_ids:
        return
    func_name = _TASK_ARQ_FUNC_NAMES.get(task_type)
    if not func_name:
        logger.warning(f"[generation] 未知的任务类型，跳过投递: {task_type}")
        return
    try:
        from app.tasks.worker import create_arq_pool

        pool = await create_arq_pool()
        if pool is None:
            logger.warning(
                f"[generation] arq 不可用，任务待处理 func={func_name}, count={len(task_ids)}"
            )
            return
        for task_id in task_ids:
            await pool.enqueue_job(func_name, task_id)
        logger.info(
            f"[generation] 批量任务已投递 ARQ func={func_name}, count={len(task_ids)}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[generation] 投递 ARQ 失败 func={func_name}, count={len(task_ids)}: {exc}"
        )


def _make_idempotency_key(
    project_id: int,
    storyboard_id: int,
    task_type: TaskType,
    voice_id: str | None = None,
) -> str:
    """生成任务幂等键。

    Args:
        project_id: 项目 ID。
        storyboard_id: 分镜 ID。
        task_type: 任务类型。
        voice_id: 音色 ID，仅 tts 任务使用；传入时追加到幂等键尾部，
            使同一分镜更换音色时产生新任务（Task 表无参数字段，
            幂等键是执行侧取回音色的唯一落库通路）。

    Returns:
        str: 幂等键字符串。
    """
    key = f"{project_id}-{storyboard_id}-{task_type.value}"
    if task_type == TaskType.TTS and voice_id:
        key = f"{key}-{voice_id}"
    return key


async def _get_storyboards(
    db: AsyncSession, project_id: int, req: GenerateRequest
) -> List[Storyboard]:
    """根据请求获取需要处理的分镜列表。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 生成请求体。

    Returns:
        List[Storyboard]: 分镜列表。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    query = select(Storyboard).where(Storyboard.project_id == project_id)
    if req.storyboard_ids:
        query = query.where(Storyboard.id.in_(req.storyboard_ids))
    query = query.order_by(Storyboard.sequence)

    result = await db.execute(query)
    return list(result.scalars().all())


async def generate_keyframes(
    db: AsyncSession, project_id: int, req: GenerateRequest
) -> GenerateResponse:
    """为分镜创建关键帧（image）生成任务。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 生成请求体。

    Returns:
        GenerateResponse: 包含创建的任务 ID 列表。
    """
    storyboards = await _get_storyboards(db, project_id, req)
    task_ids: List[int] = []

    for sb in storyboards:
        if req.mode == "only_pending" and sb.keyframe_url:
            continue

        idem_key = _make_idempotency_key(project_id, sb.id, TaskType.IMAGE)
        # 幂等：若已存在相同 key 的任务则跳过
        existing = await db.execute(
            select(Task).where(Task.idempotency_key == idem_key)
        )
        if existing.scalar_one_or_none():
            continue

        task = Task(
            project_id=project_id,
            storyboard_id=sb.id,
            type=TaskType.IMAGE,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=idem_key,
        )
        db.add(task)
        await db.flush()
        task_ids.append(task.id)

    await db.commit()
    # 任务落库后投递 ARQ 执行（不可用时仅告警，任务保持 queued）
    await _enqueue_generation_tasks(TaskType.IMAGE, task_ids)
    return GenerateResponse(task_ids=task_ids, total=len(task_ids))


async def generate_videos(
    db: AsyncSession, project_id: int, req: GenerateRequest
) -> GenerateResponse:
    """为分镜创建视频（video）生成任务。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 生成请求体。

    Returns:
        GenerateResponse: 包含创建的任务 ID 列表。
    """
    storyboards = await _get_storyboards(db, project_id, req)
    task_ids: List[int] = []

    for sb in storyboards:
        if req.mode == "only_pending" and sb.video_url:
            continue
        # 视频生成依赖关键帧
        if not sb.keyframe_url:
            continue

        idem_key = _make_idempotency_key(project_id, sb.id, TaskType.VIDEO)
        existing = await db.execute(
            select(Task).where(Task.idempotency_key == idem_key)
        )
        if existing.scalar_one_or_none():
            continue

        task = Task(
            project_id=project_id,
            storyboard_id=sb.id,
            type=TaskType.VIDEO,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=idem_key,
        )
        db.add(task)
        await db.flush()
        task_ids.append(task.id)

    await db.commit()
    # 任务落库后投递 ARQ 执行（不可用时仅告警，任务保持 queued）
    await _enqueue_generation_tasks(TaskType.VIDEO, task_ids)
    return GenerateResponse(task_ids=task_ids, total=len(task_ids))


async def generate_voices(
    db: AsyncSession, project_id: int, req: GenerateRequest
) -> GenerateResponse:
    """为分镜创建语音（tts）合成任务。

    请求指定的 voice_id 编码进幂等键透传给执行侧（tts_tasks），
    未指定时由执行侧按「角色绑定音色 → 默认音色」回退。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 生成请求体（voice_id 可选）。

    Returns:
        GenerateResponse: 包含创建的任务 ID 列表。
    """
    storyboards = await _get_storyboards(db, project_id, req)
    task_ids: List[int] = []

    for sb in storyboards:
        if req.mode == "only_pending" and sb.audio_url:
            continue
        if not sb.dialogue:
            continue

        idem_key = _make_idempotency_key(project_id, sb.id, TaskType.TTS, req.voice_id)
        existing = await db.execute(
            select(Task).where(Task.idempotency_key == idem_key)
        )
        if existing.scalar_one_or_none():
            continue

        task = Task(
            project_id=project_id,
            storyboard_id=sb.id,
            type=TaskType.TTS,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=idem_key,
        )
        db.add(task)
        await db.flush()
        task_ids.append(task.id)

    await db.commit()
    # 任务落库后投递 ARQ 执行（不可用时仅告警，任务保持 queued）
    await _enqueue_generation_tasks(TaskType.TTS, task_ids)
    return GenerateResponse(task_ids=task_ids, total=len(task_ids))


# ============================================================
# 视频片段降级换模重新生成（VID-07）
# ============================================================

# 新任务 error_message 中记录 provider 选择的标记前缀，
# 同时作为 Worker 端（tasks/video_tasks.py）读取指定 Provider 的载体：
# 格式为 "provider=<name>;"，置于 error_message 首部
PROVIDER_TAG_PREFIX = "provider="


def format_provider_tag(provider: Optional[str]) -> str:
    """格式化 provider 标记字符串。

    Args:
        provider: Provider 名称（如 "agnes" / "mock"），为空返回空串。

    Returns:
        str: 形如 "provider=mock;" 的标记；provider 为空时返回空字符串。
    """
    if not provider:
        return ""
    return f"{PROVIDER_TAG_PREFIX}{provider};"


def parse_provider_tag(error_message: Optional[str]) -> Optional[str]:
    """从任务 error_message 前缀解析指定的 provider 名称。

    Args:
        error_message: 任务 error_message 内容。

    Returns:
        Optional[str]: Provider 名称；无标记时返回 None（表示使用系统默认）。
    """
    if not error_message:
        return None
    msg = error_message.strip()
    if not msg.startswith(PROVIDER_TAG_PREFIX):
        return None
    name = msg[len(PROVIDER_TAG_PREFIX):].split(";", 1)[0].strip()
    return name or None


async def regenerate_video(
    db: AsyncSession,
    project_id: int,
    task_id: int,
    req: VideoRegenerateRequest,
    user_id: int,
) -> VideoRegenerateResponse:
    """视频片段换模重新生成：标记原任务废弃并创建新任务（VID-07）。

    校验项目归属与任务类型后，将原视频任务标记为已换模重生成
    （TaskStatus 无 superseded 状态，最小方案复用 FAILED 并在
    error_message 标注），随后复制 storyboard 关联创建新 video 任务，
    error_message 首部写入 provider 标记供 Worker 读取，最后投递 ARQ
    视频任务并返回新任务 ID。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        task_id: 原视频任务 ID。
        req: 重新生成请求体（可指定 provider）。
        user_id: 当前登录用户 ID（用于项目归属校验）。

    Returns:
        VideoRegenerateResponse: 新任务 ID 与 provider 选择。

    Raises:
        BizException: 项目不存在 / 无权访问时抛出 NOT_FOUND；
            任务不存在或不属于该项目时抛出 NOT_FOUND；
            任务类型非视频时抛出 PARAM_ERROR。
    """
    provider = req.provider if req is not None else None

    # 校验项目存在且归属当前用户
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在或无权访问")

    # 校验任务存在且属于该项目
    task = await db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise BizException(code=ErrorCode.NOT_FOUND, message="任务不存在")

    # 校验任务类型为视频
    if task.type != TaskType.VIDEO:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="仅支持视频任务重新生成")

    # 标记原任务已换模废弃（枚举无 superseded，复用 FAILED 并标注原因）
    task.status = TaskStatus.FAILED
    task.error_message = "已换模重生成（superseded）：原任务已由新任务替代"

    # 创建新视频任务：复用同一分镜（prompt/keyframe 随分镜继承），
    # provider 选择写入 error_message 首部标记，供 Worker 端解析
    new_task = Task(
        project_id=project_id,
        storyboard_id=task.storyboard_id,
        graph_run_id=task.graph_run_id,
        type=TaskType.VIDEO,
        status=TaskStatus.QUEUED,
        queue_name=QueueName.NORMAL,
        priority=5,
        idempotency_key=(
            f"{project_id}-{task.storyboard_id}-video-regen-{uuid.uuid4().hex[:12]}"
        ),
        error_message=format_provider_tag(provider) or None,
    )
    db.add(new_task)
    await db.flush()

    await db.commit()
    await db.refresh(new_task)

    # 广播新任务排队状态（失败不影响主流程）
    try:
        from app.domains.tasks import publish_task_status

        await publish_task_status(project_id, new_task.id, TaskStatus.QUEUED.value)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[generation] 广播重生成任务状态失败 task_id={new_task.id}: {exc}")

    # 投递 ARQ 视频任务（arq 不可用时仅告警，任务保持 queued）
    try:
        from app.tasks.worker import create_arq_pool

        pool = await create_arq_pool()
        if pool is not None:
            await pool.enqueue_job("generate_video", new_task.id)
            logger.info(f"[generation] 重生成任务已投递 ARQ task_id={new_task.id}")
        else:
            logger.warning(f"[generation] arq 不可用，任务待处理 task_id={new_task.id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[generation] 投递 ARQ 失败 task_id={new_task.id}: {exc}")

    return VideoRegenerateResponse(new_task_id=new_task.id, provider=provider)
