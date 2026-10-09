"""
ARQ Worker 配置模块。

基于 Redis 连接配置 ARQ Worker，注册 image / video / tts / compose
四类任务函数，并设置指数退避重试策略（最多 3 次）。

启动方式：
    arq app.tasks.worker.WorkerSettings
"""

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.tasks.compose_tasks import compose_video
from app.tasks.image_tasks import generate_image
from app.tasks.tts_tasks import generate_tts
from app.tasks.video_tasks import generate_video

logger = get_logger()

# 尝试导入 arq；不可用时提供降级配置
try:  # pragma: no cover - 依赖环境
    from arq import create_pool
    from arq.connections import RedisSettings
    from arq.worker import func

    _HAS_ARQ = True
except Exception:  # noqa: BLE001
    create_pool = None  # type: ignore
    RedisSettings = None  # type: ignore
    func = None  # type: ignore
    _HAS_ARQ = False


# 指数退避：第 n 次重试等待 2^n 秒，上限 60 秒
def _backoff(n: int) -> float:
    """计算第 n 次重试的等待时间（指数退避）。

    Args:
        n: 重试次数（从 1 开始）。

    Returns:
        float: 等待秒数。
    """
    return min(2 ** n, 60)


async def _on_job_result(ctx: dict[str, Any], job: Any, result: Any) -> None:
    """ARQ 任务完成回调：重试耗尽后将数据库任务状态更新为 DEAD。

    ARQ 自身的重试机制耗尽后会触发本回调，此时若任务在数据库中仍为
    FAILED 状态（说明业务代码的 retry_count 检查未走到 DEAD 分支），
    则统一更新为 DEAD，保证死信队列状态语义正确。

    Args:
        ctx: Worker 上下文。
        job: ARQ Job 对象。
        result: 任务执行结果。

    Returns:
        None
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.models import Task, TaskStatus
        from sqlalchemy import select

        task_id = None
        # 从 job 箭头参数中提取 task_id（各任务函数签名均为 ctx, task_id）
        if hasattr(job, "args") and len(job.args) >= 2:
            task_id = job.args[1]
        elif hasattr(job, "kwargs") and "task_id" in job.kwargs:
            task_id = job.kwargs["task_id"]

        if task_id is None:
            return

        async with AsyncSessionLocal() as session:
            task = await session.get(Task, int(task_id))
            if task and task.status == TaskStatus.FAILED:
                # ARQ 重试耗尽，任务最终失败 → 标记为 DEAD
                task.status = TaskStatus.DEAD
                if not task.error_message:
                    task.error_message = "ARQ 重试耗尽，任务进入死信队列"
                await session.commit()
                logger.warning(
                    f"[arq-worker] 任务 {task_id} ARQ 重试耗尽，状态更新为 DEAD"
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[arq-worker] on_job_result 回调处理失败: {exc}")


class WorkerSettings:
    """ARQ Worker 配置类。

    Attributes:
        redis_settings: Redis 连接配置。
        functions: 注册的任务函数列表。
        max_tries: 最大尝试次数（含首次）。
        retry_backoff: 重试退避函数。
        queue_name: 队列名称。
        on_job_result: 任务完成回调。
    """

    if _HAS_ARQ and RedisSettings is not None:
        redis_settings = RedisSettings(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            database=settings.REDIS_DB,
        )

    functions = [
        generate_image,
        generate_video,
        generate_tts,
        compose_video,
    ]

    # 最多尝试 4 次（1 次首次 + 3 次重试），与业务代码 max_retry=3 对齐
    max_tries = 4
    retry_backoff = _backoff
    queue_name = "arq:queue"
    on_job_result = _on_job_result

    @staticmethod
    async def startup(ctx: dict[str, Any]) -> None:
        """Worker 启动回调。

        Args:
            ctx: Worker 上下文。

        Returns:
            None
        """
        logger.info("[arq-worker] Worker 启动")

    @staticmethod
    async def shutdown(ctx: dict[str, Any]) -> None:
        """Worker 关闭回调。

        Args:
            ctx: Worker 上下文。

        Returns:
            None
        """
        logger.info("[arq-worker] Worker 关闭")


async def create_arq_pool():
    """创建 ARQ Redis 连接池（供应用端投递任务使用）。

    Returns:
        Any: ARQ Redis 连接池；若 arq 未安装则返回 None。
    """
    if not _HAS_ARQ or create_pool is None or RedisSettings is None:
        logger.warning("[arq-worker] arq 未安装，无法创建连接池。")
        return None

    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        database=settings.REDIS_DB,
    )
    return await create_pool(redis_settings)
