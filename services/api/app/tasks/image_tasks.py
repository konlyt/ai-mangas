"""
图像生成任务（ARQ Worker）。

从 tasks 表取出 image 类型任务，调用图像 Provider 生成图片，
回写 result_url 与 status，并通过 Redis Pub/Sub 广播状态变更。
失败时指数退避重试，超过最大重试次数后置为 dead。

多角色注入协议（08 §7.1 缺陷 4，与 graph 路径 keyframe_agent 对齐）：
    关键帧任务执行时按分镜关联角色（storyboard.character_ids）组装多角色
    一致性提示词：复用 graph 路径的 resolve_storyboard_characters（三级关联）
    与 build_multiref_prompt（{{ref N}} 参考板协议 + 特征卡回退 +
    Immutable locks 尾注），参考图经 ref_images 参数传给图像 Provider
    （i2i 优先，失败自动降级纯 t2i）。参考图被 Provider 丢弃时在
    task.error_message 写入 ref_dropped 降级标记（与 graph 路径
    sb["ref_dropped"] 同款降级语义）。
    分镜解析不出关联角色（角色表为空 / 显式关联失配）时保持既有行为：
    原提示词直接生成，不注入任何角色约束。
    注意：characters 表无 feature_tags 列，特征卡数据从 character_locks
    列取；locks 无有效字段时退化为"角色名 + description"（description
    作为外貌特征注入特征卡段）。
"""

import time
from typing import Any

from sqlalchemy import select

from app.agents.nodes.consistency_agent import resolve_storyboard_characters
from app.agents.nodes.keyframe_agent import build_multiref_prompt
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import AgentEvent, Character, Storyboard, StoryboardStatus, Task, TaskStatus
from app.providers.image.registry import get_image_registry

logger = get_logger()

# 参考图被 Provider 丢弃时的降级标记前缀（写入 task.error_message，
# 与 graph 路径 sb["ref_dropped"]=True 同款降级语义）
REF_DROPPED_TAG = "ref_dropped"

# REST 侧 description 退化为外貌特征时的最大截断长度
# （graph 侧 feature_tags 为 LLM 提取的短标签，此处截断对齐其量级）
_DESCRIPTION_MAX_LEN = 200


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


def _character_to_state_dict(char: Character) -> dict:
    """将 Character ORM 对象转换为 graph 侧 state.characters 的字典形态。

    转换字段：id / name / description / ref_board_url / character_locks。
    characters 表无 feature_tags 列，特征卡数据退化规则（任务执行侧兜底）：
    character_locks 四个锚点字段（服饰/发型/外貌/体型）均无有效值且
    description 非空时，将 description 截断后作为外貌特征注入 feature_tags，
    使特征卡段至少携带"角色名 + description"约束（与 graph 路径的
    LLM 特征标签同款数据形态）。

    Args:
        char: characters 表 ORM 对象。

    Returns:
        dict: 与 graph 路径 state.characters 元素同构的角色字典。
    """
    locks = char.character_locks if isinstance(char.character_locks, dict) else {}
    feature_tags: dict = {}
    has_lock_fields = any(
        str(locks.get(key) or "").strip()
        for key in ("costume", "hairstyle", "appearance", "body_type")
    )
    description = (char.description or "").strip()
    if not has_lock_fields and description:
        # 关键降级：无锁字段时以 description 充当外貌特征（特征卡不空转）
        feature_tags["appearance"] = description[:_DESCRIPTION_MAX_LEN]
    return {
        "id": char.id,
        "name": char.name,
        "description": description,
        "ref_board_url": char.ref_board_url,
        "character_locks": locks,
        "feature_tags": feature_tags,
    }


async def _compose_multiref_prompt(
    session, storyboard: Storyboard, base_prompt: str
) -> tuple[str, list[dict]]:
    """REST 关键帧任务执行侧的多角色提示词组装（对齐 graph 路径协议）。

    复用 graph 路径的 resolve_storyboard_characters（character_ids /
    character_names / 全角色回退三级关联）与 build_multiref_prompt
    （{{ref N}} 协议 + 特征卡回退 + Immutable locks 尾注），参考板
    下载由 build_multiref_prompt 内部完成（单张失败仅该角色回退特征卡）。

    Args:
        session: 当前任务执行持有的异步数据库会话。
        storyboard: 待生成关键帧的分镜 ORM 对象。
        base_prompt: 分镜原始绘图提示词。

    Returns:
        tuple[str, list[dict]]: (组装后的提示词, 参考图列表)。
            分镜解析不出关联角色（项目无角色 / 显式关联失配）时返回
            (base_prompt, [])，调用方据此保持既有行为。

    Raises:
        无：角色查询与提示词组装的异常由调用方捕获降级为原提示词。
    """
    result = await session.execute(
        select(Character).where(Character.project_id == storyboard.project_id)
    )
    characters = list(result.scalars().all())
    if not characters:
        return base_prompt, []

    char_dicts = [_character_to_state_dict(char) for char in characters]
    sb_dict = {
        "id": storyboard.id,
        "sequence": storyboard.sequence,
        "character_ids": storyboard.character_ids,
    }
    # 关键逻辑：三级关联解析（显式 ID 匹配失败/显式为空 → 空列表 → 回退旧行为；
    # 无显式关联字段（NULL）→ 全角色分镜，与 graph 路径语义一致）
    linked_chars = resolve_storyboard_characters(sb_dict, char_dicts)
    if not linked_chars:
        return base_prompt, []
    return await build_multiref_prompt(base_prompt, linked_chars)


async def generate_image(ctx: dict[str, Any], task_id: int) -> dict[str, Any]:
    """执行图像生成任务。

    从 tasks 表取出任务，调用 image provider 生成图片，
    回写 result_url 到 storyboard.keyframe_url 与 task.result_url。
    有分镜关联时按 multiref 协议组装多角色提示词（{{ref N}} 参考板 +
    特征卡回退 + Immutable locks 尾注）并携带参考图生成；解析不出
    关联角色时保持既有行为（原提示词直接生成）。参考图被 Provider
    丢弃（i2i 失败降级纯 t2i）时在 task.error_message 写入
    ref_dropped 降级标记，任务仍正常完成。

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

        # 关键逻辑（08 §7.1 缺陷 4 对齐）：REST 执行侧按 multiref 协议
        # 组装多角色提示词与参考图；解析不出关联角色时返回原提示词与
        # 空参考图（保持既有行为）。组装失败降级为原提示词，不阻塞生成。
        ref_images: list[dict] = []
        if storyboard:
            try:
                prompt, ref_images = await _compose_multiref_prompt(session, storyboard, prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"[image-task] 多角色提示词组装失败，回退原提示词 task_id={task_id}: {exc}"
                )
                ref_images = []

        # 标记为 running
        task.status = TaskStatus.RUNNING
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 10)

        start_time = time.time()
        try:
            provider = _get_image_provider()
            if ref_images:
                # 携带参考板参考图生成（Provider 内部优先 i2i，
                # 失败自动降级纯 t2i 并置 last_ref_dropped=True）
                image_url = await provider.generate(prompt, ref_images=ref_images)
            else:
                image_url = await provider.generate(prompt)

            # 与 graph 路径同款降级语义：参考图未被 Provider 消费时记录告警，
            # 并在 task.error_message 写入标记（特征卡约束仍在提示词中）
            if ref_images and bool(getattr(provider, "last_ref_dropped", False)):
                task.error_message = (
                    f"{REF_DROPPED_TAG}: 参考图未被 Provider 消费"
                    "（已降级纯 t2i，特征卡约束仍在提示词中）"
                )
                logger.warning(
                    f"[image-task] 参考图未被 Provider 消费（已降级纯 t2i）task_id={task_id}"
                )

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
