"""
视频换模重新生成（VID-07）冒烟测试 —— 直接调用域函数 regenerate_video。

覆盖点：
    1. 任务不存在 → BizException NOT_FOUND(40401)；
    2. 任务类型非视频 → BizException PARAM_ERROR(40001)；
    3. mock 换模成功：原任务置为 failed（error_message 标注 superseded）、
       新任务 queued 且 error_message 首部带 provider=mock 标记，
       parse_provider_tag 可解析出 mock；
    4. provider 标记的格式化 / 解析往返（format_provider_tag ↔ parse_provider_tag）。
"""

import pytest

from app.core.response import BizException, ErrorCode
from app.domains.generation import (
    format_provider_tag,
    parse_provider_tag,
    regenerate_video,
)
from app.models import Task, TaskStatus, TaskType
from app.schemas.generate import VideoRegenerateRequest


def _patch_arq_pool(monkeypatch) -> None:
    """将 create_arq_pool 替换为直接返回 None，避免测试连接真实 Redis。

    Args:
        monkeypatch: pytest 夹具。

    Returns:
        None
    """

    async def _fake_create_arq_pool():
        """替代 create_arq_pool：测试环境无 Redis，直接返回 None。"""
        return None

    monkeypatch.setattr("app.tasks.worker.create_arq_pool", _fake_create_arq_pool)


async def test_regenerate_task_not_found(make_project, make_task, db_session, monkeypatch):
    """任务 ID 不存在 → NOT_FOUND(40401)。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具（作为域函数入参）。
        monkeypatch: 用于屏蔽 ARQ 真实连接。

    Returns:
        None
    """
    _patch_arq_pool(monkeypatch)
    project_id = await make_project(title="重生成测试项目")

    with pytest.raises(BizException) as exc_info:
        await regenerate_video(
            db_session,
            project_id,
            999999,  # 不存在的任务 ID
            VideoRegenerateRequest(provider="mock"),
            user_id=1,
        )
    assert exc_info.value.code == ErrorCode.NOT_FOUND


async def test_regenerate_wrong_user_not_found(make_project, make_task, db_session, monkeypatch):
    """任务存在但不属于当前用户（项目归属校验失败）→ NOT_FOUND(40401)。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        monkeypatch: 用于屏蔽 ARQ 真实连接。

    Returns:
        None
    """
    _patch_arq_pool(monkeypatch)
    project_id = await make_project(title="归属校验项目", user_id=1)
    task_id = await make_task(project_id, task_type=TaskType.VIDEO)

    with pytest.raises(BizException) as exc_info:
        await regenerate_video(
            db_session,
            project_id,
            task_id,
            VideoRegenerateRequest(provider="mock"),
            user_id=2,  # 与项目归属用户不一致
        )
    assert exc_info.value.code == ErrorCode.NOT_FOUND


async def test_regenerate_rejects_non_video_task(make_project, make_task, db_session, monkeypatch):
    """非视频任务（image）→ PARAM_ERROR(40001)。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        monkeypatch: 用于屏蔽 ARQ 真实连接。

    Returns:
        None
    """
    _patch_arq_pool(monkeypatch)
    project_id = await make_project(title="非视频任务项目")
    task_id = await make_task(project_id, task_type=TaskType.IMAGE)

    with pytest.raises(BizException) as exc_info:
        await regenerate_video(
            db_session,
            project_id,
            task_id,
            VideoRegenerateRequest(provider="mock"),
            user_id=1,
        )
    assert exc_info.value.code == ErrorCode.PARAM_ERROR


async def test_regenerate_with_mock_provider(make_project, make_task, db_session, monkeypatch):
    """mock 换模成功：原任务 failed + 新任务 queued + provider=mock 标记。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        monkeypatch: 用于屏蔽 ARQ 真实连接。

    Returns:
        None
    """
    _patch_arq_pool(monkeypatch)
    project_id = await make_project(title="换模成功项目")
    original_task_id = await make_task(project_id, task_type=TaskType.VIDEO, status=TaskStatus.DONE)

    result = await regenerate_video(
        db_session,
        project_id,
        original_task_id,
        VideoRegenerateRequest(provider="mock"),
        user_id=1,
    )

    # 返回体：新任务 ID 有效且 provider 透传
    assert result.provider == "mock"
    assert result.new_task_id > 0
    assert result.new_task_id != original_task_id

    # 原任务：置为 failed 且 error_message 标注已换模废弃
    original_task = await db_session.get(Task, original_task_id)
    assert original_task.status == TaskStatus.FAILED
    assert "superseded" in original_task.error_message

    # 新任务：queued 的 video 任务，error_message 首部带 provider=mock 标记
    new_task = await db_session.get(Task, result.new_task_id)
    assert new_task.status == TaskStatus.QUEUED
    assert new_task.type == TaskType.VIDEO
    assert new_task.project_id == project_id
    assert new_task.error_message.startswith("provider=mock;")
    assert parse_provider_tag(new_task.error_message) == "mock"


def test_provider_tag_format_and_parse_roundtrip():
    """provider 标记的格式化与解析往返、边界取值。

    Returns:
        None
    """
    assert format_provider_tag("mock") == "provider=mock;"
    assert format_provider_tag("agnes") == "provider=agnes;"
    assert format_provider_tag(None) == ""
    assert format_provider_tag("") == ""

    assert parse_provider_tag("provider=mock;") == "mock"
    assert parse_provider_tag("provider=agnes;附加错误信息") == "agnes"
    assert parse_provider_tag(None) is None
    assert parse_provider_tag("") is None
    assert parse_provider_tag("普通错误信息，无标记") is None
    assert parse_provider_tag("provider=;") is None
