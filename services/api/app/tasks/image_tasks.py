"""
图像生成任务（ARQ Worker）。

从 tasks 表取出 image 类型任务，调用图像 Provider 生成图片，
回写 result_url 与 status，并通过 Redis Pub/Sub 广播状态变更。
失败时指数退避重试，超过最大重试次数后置为 dead。
"""

import time
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import AgentEvent, Storyboard, StoryboardStatus, Task, TaskStatus
from app.providers.image.registry import get_image_registry

logger = get_logger()


def _get_image_provider(name: str | None = None):
    """获取图像生成 Provider 实例（兼容 registry 接口）。

    Args:
        name: Provider 名称。

    Returns:
        ImageProvider: 图像生成 Provider 实例。
    """
    try:
        from app.providers.image.registry import get_image_provider  # type: ignore

        return get_image_provider(name)
    except Exception:
        return get_image_registry().get_provider(name)


async def _publish_task_status(project_id: int, task_id: int, status: str, progress: int = 0):
    """广播任务状态变更。

    Args:
        project_id: 项目 ID。
        task_id: 任务 ID。
        status: 状态字符串。
        progress: 进度百分比。

    Returns:
        None
    """
    try:
        from app.domains.tasks import publish_task_status

        await publish_task_status(project_id, task_id, status, progress)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[image-task] 广播状态失败 task_id={task_id}: {exc}")


async def generate_image(ctx: dict[str, Any], task_id: int) -> dict[str, Any]:
    """执行图像生成任务。

    从 tasks 表取出任务，调用 image provider 生成图片，
    回写 result_url 到 storyboard.keyframe_url 与 task.result_url。

    Args:
        ctx: ARQ 任务上下文。
        task_id: 任务 ID。

    Returns:
        dict: 包含 task_id 与 status 的结果字典。

    Raises:
        Exception: 当重试次数未耗尽时抛出，触发 ARQ 重试。
    """
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if task is None:
            logger.error(f"[image-task] 任务不存在 task_id={task_id}")
            return {"task_id": task_id, "status": "not_found"}

        # 已完成的任务直接返回
        if task.status == TaskStatus.DONE:
            return {"task_id": task_id, "status": "done"}

        # 查询关联分镜获取提示词
        storyboard = None
        if task.storyboard_id:
            storyboard = await session.get(Storyboard, task.storyboard_id)
        prompt = storyboard.prompt if storyboard and storyboard.prompt else "动漫风格图片"

        # 标记为 running
        task.status = TaskStatus.RUNNING
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 10)

        start_time = time.time()
        try:
            provider = _get_image_provider()
            image_url = await provider.generate(prompt)

            # 回写结果
            task.result_url = image_url
            task.status = TaskStatus.DONE
            task.cost_points = 1  # mock 消耗点数
            if storyboard:
                storyboard.keyframe_url = image_url
                # 关键帧生成完成，更新分镜状态为 done
                storyboard.status = StoryboardStatus.DONE

            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.DONE.value, 100)

            latency_ms = int((time.time() - start_time) * 1000)
            # 记录 agent_events（provider 调用耗时与点数）
            event = AgentEvent(
                graph_run_id=task.graph_run_id or "",
                project_id=task.project_id,
                node_name="image_provider",
                latency_ms=latency_ms,
                cost_points=task.cost_points,
                input_digest=prompt[:200],
                output_digest=image_url,
            )
            session.add(event)
            await session.commit()

            logger.info(
                f"[image-task] 生成成功 task_id={task_id}, "
                f"latency={latency_ms}ms, url={image_url}"
            )
            return {"task_id": task_id, "status": "done", "url": image_url}

        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start_time) * 1000)
            task.retry_count = (task.retry_count or 0) + 1
            task.error_message = str(exc)[:500]

            if task.retry_count >= (task.max_retry or 3):
                # 超过最大重试次数，标记为 dead
                task.status = TaskStatus.DEAD
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                logger.error(
                    f"[image-task] 任务耗尽重试 task_id={task_id}, "
                    f"latency={latency_ms}ms, error={exc}"
                )
                return {"task_id": task_id, "status": "dead", "error": str(exc)}

            # 否则标记为 failed，由 ARQ 重试（指数退避）
            task.status = TaskStatus.FAILED
            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.FAILED.value)
            logger.warning(
                f"[image-task] 生成失败，将重试 task_id={task_id}, "
                f"retry={task.retry_count}, error={exc}"
            )
            raise
