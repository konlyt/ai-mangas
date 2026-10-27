"""
合成领域服务。

提供全片合成、局部重合成、查询最终输出、审核导出等业务逻辑。
合成通过创建 compose 类型任务并投递 ARQ 队列由 Worker 执行真实 FFmpeg 合成；
导出在请求内异步执行 FFmpeg 裁剪转码并写入操作日志。
"""

import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import (
    OperationLog,
    Project,
    QueueName,
    Storyboard,
    Task,
    TaskStatus,
    TaskType,
)
from app.providers.storage import STATIC_ROOT
from app.schemas.compose import ComposePartialRequest, ComposeRequest, ExportRequest, OutputOut
from app.utils.ffmpeg import FFmpegNotFoundError, probe_media, run_ffmpeg

logger = get_logger()

# 支持的导出比例
SUPPORTED_EXPORT_RATIOS = {"9:16": 9 / 16, "16:9": 16 / 9}
# 成片输出目录模板（相对 STATIC_ROOT）
OUTPUT_DIR_TEMPLATE = "outputs/{project_id}"


def _make_compose_idempotency_key(project_id: int, partial_ids: Optional[list] = None) -> str:
    """生成合成任务的幂等键。

    Args:
        project_id: 项目 ID。
        partial_ids: 局部分镜 ID 列表，全片合成为 None。

    Returns:
        str: 幂等键字符串。
    """
    suffix = "-" + ",".join(str(i) for i in sorted(partial_ids)) if partial_ids else "-full"
    return f"{project_id}-compose{suffix}"


async def _enqueue_compose_task(task_id: int, storyboard_ids: Optional[list[int]]) -> None:
    """将合成任务投递到 ARQ 队列；不可用时在 API 进程内异步兜底执行。

    Args:
        task_id: 任务 ID。
        storyboard_ids: 局部合成分镜 ID 列表（全片为 None）。

    Returns:
        None
    """
    try:
        from app.tasks.worker import create_arq_pool

        pool = await create_arq_pool()
        if pool is None:
            raise RuntimeError("arq 未安装")
        await pool.enqueue_job(
            "compose_video", task_id=task_id, storyboard_ids=storyboard_ids
        )
        logger.info(f"[compose] 任务已入队 ARQ task_id={task_id}")
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[compose] ARQ 入队失败（{exc}），降级为进程内异步执行 task_id={task_id}")

    # 降级：无 Redis / ARQ 环境时直接在 API 进程内异步执行，保证合成功能可用
    async def _run_local() -> None:
        """进程内兜底执行合成任务，异常仅记录日志。

        Returns:
            None
        """
        try:
            from app.tasks.compose_tasks import compose_video

            await compose_video({}, task_id, storyboard_ids)
        except Exception as run_exc:  # noqa: BLE001
            logger.error(f"[compose] 进程内兜底执行失败 task_id={task_id}: {run_exc}")

    asyncio.create_task(_run_local())


def _get_latest_done_task_stmt(project_id: int):
    """构造查询项目最新完成合成任务的 select 语句。

    Args:
        project_id: 项目 ID。

    Returns:
        Select: 按 updated_at 倒序的 compose 完成任务查询。
    """
    return (
        select(Task)
        .where(
            Task.project_id == project_id,
            Task.type == TaskType.COMPOSE,
            Task.status == TaskStatus.DONE,
        )
        .order_by(desc(Task.updated_at))
        .limit(1)
    )


async def compose(
    db: AsyncSession, project_id: int, req: Optional[ComposeRequest] = None
) -> dict:
    """创建全片合成任务并投递 ARQ 队列。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 合成请求体（可空）。

    Returns:
        dict: 包含 task_id 的字典。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 记录本次合成的音频模式到项目配置，供 compose worker 读取
    audio_mode = (req.audio_mode if req else None) or "auto"
    if audio_mode not in ("auto", "keep_original", "tts"):
        audio_mode = "auto"
    config = dict(project.config or {})
    config["audio_mode"] = audio_mode
    project.config = config
    await db.commit()

    idem_key = _make_compose_idempotency_key(project_id)
    existing = await db.execute(
        select(Task).where(Task.idempotency_key == idem_key)
    )
    task = existing.scalar_one_or_none()

    if task is None:
        task = Task(
            project_id=project_id,
            type=TaskType.COMPOSE,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=idem_key,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        await _enqueue_compose_task(task.id, req.storyboard_ids if req else None)
    else:
        # 幂等命中：任务已结束（失败/死亡/完成）则重置为排队状态并重新入队
        if task.status in (TaskStatus.FAILED, TaskStatus.DEAD, TaskStatus.DONE, TaskStatus.SUCCESS):
            task.status = TaskStatus.QUEUED
            task.error_message = None
            task.result_url = None
            await db.commit()
            await _enqueue_compose_task(task.id, req.storyboard_ids if req else None)

    return {"task_id": task.id}


async def partial_compose(
    db: AsyncSession, project_id: int, req: ComposePartialRequest
) -> dict:
    """创建局部重合成任务（仅拼接指定分镜产出预览片）并投递 ARQ 队列。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 局部合成请求体。

    Returns:
        dict: 包含 task_id 的字典。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 校验分镜归属
    rows = await db.execute(
        select(Storyboard.id).where(
            Storyboard.project_id == project_id,
            Storyboard.id.in_(req.storyboard_ids),
        )
    )
    valid_ids = {row[0] for row in rows.all()}
    invalid = set(req.storyboard_ids) - valid_ids
    if invalid:
        raise BizException(
            code=ErrorCode.PARAM_ERROR,
            message=f"分镜不存在或不属于该项目: {sorted(invalid)}",
        )

    idem_key = _make_compose_idempotency_key(project_id, req.storyboard_ids)
    existing = await db.execute(
        select(Task).where(Task.idempotency_key == idem_key)
    )
    task = existing.scalar_one_or_none()

    if task is None:
        task = Task(
            project_id=project_id,
            type=TaskType.COMPOSE,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=idem_key,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

    await _enqueue_compose_task(task.id, req.storyboard_ids)
    return {"task_id": task.id}


async def _stat_output(url: str) -> tuple[float, int]:
    """探测成片 URL 对应本地文件的时长与大小。

    Args:
        url: 成片相对 URL（/static/...）。

    Returns:
        tuple[float, int]: (时长秒, 文件字节数)；不可探测时为 (0, 0)。
    """
    if not url or not url.startswith("/static/"):
        return 0.0, 0
    local = (STATIC_ROOT / url[len("/static/"):]).resolve()
    if not local.is_file():
        return 0.0, 0
    size = local.stat().st_size
    try:
        info = await probe_media(local)
        return info.get("duration") or 0.0, size
    except Exception:  # noqa: BLE001
        return 0.0, size


async def get_output(db: AsyncSession, project_id: int) -> OutputOut:
    """查询项目的最终合成输出。

    从最新完成的 compose 任务中获取结果 URL，并探测真实时长与大小。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        OutputOut: 最终输出信息。
    """
    result = await db.execute(_get_latest_done_task_stmt(project_id))
    task = result.scalar_one_or_none()

    if task is None or not task.result_url:
        # 若暂无完成的合成任务，返回空输出
        return OutputOut()

    duration, size = await _stat_output(task.result_url)
    return OutputOut(
        video_url=task.result_url,
        url=task.result_url,
        duration=int(duration),
        size=size,
        created_at=task.updated_at.isoformat() if task.updated_at else None,
    )


async def export_project(
    db: AsyncSession, project_id: int, req: ExportRequest, user_id: int
) -> dict:
    """导出成片：按比例居中裁剪并轻量转码，写入操作日志后返回下载 URL。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 导出请求体（含可选 ratio）。
        user_id: 当前操作用户 ID（用于操作日志）。

    Returns:
        dict: 包含 url / ratio / size 的导出结果。

    Raises:
        BizException: 项目不存在、无成片、成片文件缺失、比例非法或未检测到 FFmpeg 时抛出。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 比例：请求未指定时回退到项目配置比例，再回退 9:16
    ratio = req.ratio or (project.aspect_ratio if project.aspect_ratio in SUPPORTED_EXPORT_RATIOS else "9:16")
    if ratio not in SUPPORTED_EXPORT_RATIOS:
        raise BizException(code=ErrorCode.PARAM_ERROR, message=f"不支持的导出比例: {ratio}（支持 9:16 / 16:9）")

    # 取最新成片
    result = await db.execute(_get_latest_done_task_stmt(project_id))
    task = result.scalar_one_or_none()
    if task is None or not task.result_url:
        raise BizException(code=ErrorCode.NOT_FOUND, message="暂无成片，请先完成合成")
    if not task.result_url.startswith("/static/"):
        raise BizException(code=ErrorCode.NOT_FOUND, message="成片文件不可用（非本地产物）")

    source_path = (STATIC_ROOT / task.result_url[len("/static/"):]).resolve()
    if not source_path.is_file():
        raise BizException(code=ErrorCode.NOT_FOUND, message="成片文件缺失，请重新合成")

    # FFmpeg 可用性前置检查
    try:
        await run_ffmpeg(["-version"], log_tag="export-check")
    except FFmpegNotFoundError as exc:
        raise BizException(code=ErrorCode.SERVER_ERROR, message=str(exc))

    # 计算居中裁剪参数（宽高取偶，避免编码器报错）
    info = await probe_media(source_path)
    src_w = info.get("width") or 0
    src_h = info.get("height") or 0
    if src_w <= 0 or src_h <= 0:
        raise BizException(code=ErrorCode.SERVER_ERROR, message="成片信息探测失败，无法导出")
    target_ratio = SUPPORTED_EXPORT_RATIOS[ratio]
    if src_w / src_h > target_ratio:
        crop_h = src_h
        crop_w = max(2, int(src_h * target_ratio) // 2 * 2)
    else:
        crop_w = src_w
        crop_h = max(2, int(src_w / target_ratio) // 2 * 2)
    x = (src_w - crop_w) // 2
    y = (src_h - crop_h) // 2

    # 输出到 exports 子目录
    out_dir = STATIC_ROOT / OUTPUT_DIR_TEMPLATE.format(project_id=project_id) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(datetime.now().timestamp())
    out_file = out_dir / f"export_{ts}.mp4"

    # 裁剪 + 轻量转码（视频重编码，音频直拷）
    await run_ffmpeg(
        ["-y", "-i", str(source_path),
         "-vf", f"crop={crop_w}:{crop_h}:{x}:{y}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
         str(out_file)],
        log_tag="export",
    )
    if not out_file.is_file():
        raise BizException(code=ErrorCode.SERVER_ERROR, message="导出失败：未生成产物文件")

    url = f"/static/{OUTPUT_DIR_TEMPLATE.format(project_id=project_id)}/exports/{out_file.name}"
    size = out_file.stat().st_size

    # 写操作日志
    log = OperationLog(
        user_id=user_id,
        project_id=project_id,
        action="export",
        detail={
            "url": url,
            "ratio": ratio,
            "size": size,
            "source": task.result_url,
            "crop": f"{crop_w}x{crop_h}+{x}+{y}",
        },
    )
    db.add(log)
    await db.commit()

    logger.info(f"[compose] 导出成功 project_id={project_id}, ratio={ratio}, url={url}")
    return {"url": url, "ratio": ratio, "size": size}


async def get_latest_export(db: AsyncSession, project_id: int) -> dict:
    """查询项目最近一次导出记录。

    简化实现：从 operation_logs 中取最近一条 export 操作的详情。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        dict: 包含 url / ratio / created_at 的记录；无导出记录时各字段为 None。
    """
    result = await db.execute(
        select(OperationLog)
        .where(OperationLog.project_id == project_id, OperationLog.action == "export")
        .order_by(desc(OperationLog.created_at))
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if log is None:
        return {"url": None, "ratio": None, "created_at": None}

    detail = log.detail or {}
    return {
        "url": detail.get("url"),
        "ratio": detail.get("ratio"),
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
