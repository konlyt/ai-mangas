"""
视频生成任务（ARQ Worker）。

从 tasks 表取出 video 类型任务，调用视频 Provider 两阶段接口
（submit 提交 + poll 轮询），回写 result_url 与 status。
支持通过任务 error_message 首部的 "provider=<name>;" 标记指定
Provider（VID-07 换模重新生成），重试耗尽后自动 mock 兜底降级。
可重试错误按跨厂商统一基类 VideoRetryableError 识别
（429/5xx/限流/超时等，Agnes/智谱等各厂商 Retryable 异常均继承该基类）。
"""

import asyncio
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.domains.generation import parse_provider_tag
from app.models import AgentEvent, Project, Storyboard, Task, TaskStatus
from app.providers.video.base import VideoRetryableError
from app.providers.video.registry import get_video_registry

logger = get_logger()

# 项目视觉风格 → 视频生成 prompt 前缀映射（让画面风格与所选剧本风格对齐）
STYLE_PROMPT_PREFIX: dict[str, str] = {
    "二次元": "日系二次元动画风格，线条干净利落，赛璐璐上色，色彩明亮通透，人物为动漫造型；",
    "写实": "写实真人电影质感，自然光影，皮肤与服装纹理真实，纪录片级画面；",
    "赛博朋克": "赛博朋克视觉风格，霓虹灯效，高对比冷暖撞色，雨夜都市质感，未来科技感；",
    "水墨": "中国水墨画风格，留白写意，笔墨晕染，淡雅色调，传统东方美学；",
    "油画": "古典油画质感，厚涂笔触，浓郁色彩层次，伦勃朗式明暗光影；",
    "3D": "3D 动画渲染风格，PBR 材质，电影级全局光照，皮克斯/迪士尼质感；",
}


def _get_video_provider(name: str | None = None):
    """获取视频生成 Provider 实例（兼容 registry 接口）。

    Args:
        name: Provider 名称。

    Returns:
        VideoProvider: 视频生成 Provider 实例。
    """
    try:
        from app.providers.video.registry import get_video_provider  # type: ignore

        return get_video_provider(name)
    except Exception:
        return get_video_registry().get_provider(name)


async def _publish_task_status(
    project_id: int,
    task_id: int,
    status: str,
    progress: int = 0,
    extra: dict[str, Any] | None = None,
):
    """广播任务状态变更。

    Args:
        project_id: 项目 ID。
        task_id: 任务 ID。
        status: 状态字符串。
        progress: 进度百分比。
        extra: 附加字段（如 degraded 标记），合并进广播消息。

    Returns:
        None
    """
    try:
        from app.domains.tasks import get_redis, publish_task_status

        if extra:
            # 带附加字段（如 degraded）时直接发布扩展消息，
            # publish_task_status 暂不支持扩展字段
            import json

            message: dict[str, Any] = {
                "task_id": task_id,
                "status": status,
                "progress": progress,
            }
            message.update(extra)
            r = get_redis()
            await r.publish(f"task:{project_id}", json.dumps(message, ensure_ascii=False))
        else:
            await publish_task_status(project_id, task_id, status, progress)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[video-task] 广播状态失败 task_id={task_id}: {exc}")


async def generate_video(ctx: dict[str, Any], task_id: int) -> dict[str, Any]:
    """执行视频生成任务。

    调用 video provider 的 submit 提交任务，再通过 poll 轮询直到完成，
    回写视频 URL 到 storyboard.video_url 与 task.result_url。

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
            logger.error(f"[video-task] 任务不存在 task_id={task_id}")
            return {"task_id": task_id, "status": "not_found"}

        if task.status == TaskStatus.DONE:
            return {"task_id": task_id, "status": "done"}

        # 查询关联分镜与项目风格
        storyboard = None
        if task.storyboard_id:
            storyboard = await session.get(Storyboard, task.storyboard_id)

        project = await session.get(Project, task.project_id)
        project_style = (project.style or "").strip() if project else ""
        style_prefix = STYLE_PROMPT_PREFIX.get(project_style, "")

        base_prompt = storyboard.prompt if storyboard and storyboard.prompt else "动漫视频"
        # 把项目视觉风格拼进 prompt，保证整剧人物画风统一
        prompt = f"{style_prefix}{base_prompt}" if style_prefix else base_prompt
        image_url = (
            storyboard.keyframe_url if storyboard and storyboard.keyframe_url else ""
        )

        task.status = TaskStatus.RUNNING
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 10)

        start_time = time.time()
        try:
            # 解析任务 error_message 首部的 provider 标记（VID-07 换模指定），
            # 无标记时使用系统默认 Provider
            provider_name = parse_provider_tag(task.error_message)
            provider = _get_video_provider(provider_name)

            # 提交任务
            provider_task_id = await provider.submit(prompt, image_url)
            task.provider_task_id = provider_task_id
            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 30)

            # 轮询结果
            video_url = None
            max_poll = 60  # 最多轮询 60 次
            for _ in range(max_poll):
                result = await provider.poll(provider_task_id)
                if result.get("status") == "done":
                    video_url = result.get("url")
                    break
                await asyncio.sleep(2)

            if not video_url:
                raise RuntimeError("视频生成超时")

            # 回写结果（显式指定 mock 生成不消耗点数）
            task.result_url = video_url
            task.status = TaskStatus.DONE
            task.cost_points = 0 if provider_name == "mock" else 5
            if storyboard:
                storyboard.video_url = video_url

            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.DONE.value, 100)

            latency_ms = int((time.time() - start_time) * 1000)
            # 记录 agent_events（provider 调用耗时与点数）
            event = AgentEvent(
                graph_run_id=task.graph_run_id or "",
                project_id=task.project_id,
                node_name="video_provider",
                latency_ms=latency_ms,
                cost_points=task.cost_points,
                input_digest=prompt[:200],
                output_digest=video_url,
            )
            session.add(event)
            await session.commit()

            logger.info(
                f"[video-task] 生成成功 task_id={task_id}, "
                f"latency={latency_ms}ms, url={video_url}"
            )
            return {"task_id": task_id, "status": "done", "url": video_url}

        except VideoRetryableError as exc:
            # 可重试错误（各厂商统一基类：429/5xx/限流/超时/队列满等临时性错误，
            # 含 AgnesVideoRetryableError 与 ZhipuVideoRetryableError）：
            # 先交 ARQ 指数退避重试，耗尽后 mock 兜底
            task.retry_count = (task.retry_count or 0) + 1
            task.error_message = str(exc)[:500]

            if task.retry_count < (task.max_retry or 3):
                task.status = TaskStatus.FAILED
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.FAILED.value)
                logger.warning(
                    f"[video-task] 可重试错误，将退避重试 task_id={task_id}, "
                    f"retry={task.retry_count}, error={exc}"
                )
                raise

            # 重试耗尽：改用 mock 兜底完成本次生成，避免任务直接死亡
            logger.warning(f"[video-task] 可重试错误耗尽，mock 兜底 task_id={task_id}: {exc}")
            try:
                mock_provider = _get_video_provider("mock")
                mock_id = await mock_provider.submit(prompt, image_url)
                video_url = None
                for _ in range(5):
                    r = await mock_provider.poll(mock_id)
                    if r.get("status") == "done":
                        video_url = r.get("url")
                        break
                    await asyncio.sleep(1)
                if not video_url:
                    raise RuntimeError("mock 兜底未产出视频")
            except Exception as mock_exc:  # noqa: BLE001
                task.status = TaskStatus.DEAD
                task.error_message = f"重试耗尽且 mock 兜底失败: {mock_exc}"[:500]
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                return {"task_id": task_id, "status": "dead", "error": str(mock_exc)}

            # 回写兜底结果（降级任务不计点数）；
            # error_message 写入"降级"标记，供前端识别降级结果并弹降级提示
            task.result_url = video_url
            task.status = TaskStatus.DONE
            task.cost_points = 0
            task.error_message = f"降级生成(mock)：{str(exc)[:200]}"
            if storyboard:
                storyboard.video_url = video_url
            await session.commit()
            await _publish_task_status(
                task.project_id,
                task_id,
                TaskStatus.DONE.value,
                100,
                extra={"degraded": True},
            )
            return {"task_id": task_id, "status": "done", "url": video_url, "degraded": True}

        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start_time) * 1000)
            task.retry_count = (task.retry_count or 0) + 1
            task.error_message = str(exc)[:500]

            if task.retry_count >= (task.max_retry or 3):
                task.status = TaskStatus.DEAD
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                logger.error(
                    f"[video-task] 任务耗尽重试 task_id={task_id}, "
                    f"latency={latency_ms}ms, error={exc}"
                )
                return {"task_id": task_id, "status": "dead", "error": str(exc)}

            task.status = TaskStatus.FAILED
            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.FAILED.value)
            logger.warning(
                f"[video-task] 生成失败，将重试 task_id={task_id}, "
                f"retry={task.retry_count}, error={exc}"
            )
            raise
