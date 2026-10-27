"""视频任务 mock 兜底放宽（08 §7.1 缺陷 3）回归测试。

覆盖点：
    1. 智谱类可重试异常（ZhipuVideoRetryableError，如 429 余额不足）重试耗尽
       → 任务 DONE + degraded 降级完成（mock 兜底），而非 DEAD；
    2. 可重试异常未耗尽 → FAILED + 向上抛出（交 ARQ 退避重试）；
    3. 不可恢复错误（如 401 鉴权失败，普通 RuntimeError）重试耗尽 → DEAD；
    4. 显式指定 mock（provider=mock）正常路径不受影响：DONE 且 cost_points=0。

实现说明：generate_video 通过模块级 AsyncSessionLocal 获取会话，测试中
monkeypatch 为内存 SQLite 会话工厂；_get_video_provider 按 provider 名分派
fake 智谱 Provider（可注入异常）与真实 MockVideoProvider。
"""

import pytest
from app.models import Task, TaskStatus, TaskType
from app.providers.video.mock import MockVideoProvider
from app.providers.video.zhipu import ZhipuVideoRetryableError
from app.tasks.video_tasks import generate_video


class _FakeZhipuProvider:
    """模拟智谱视频 Provider：按注入的异常在 submit/poll 抛出。

    Attributes:
        _submit_exc: submit 阶段抛出的异常（None 表示成功返回假任务 ID）。
        _poll_exc: poll 阶段抛出的异常（None 表示成功返回 done 结果）。
    """

    def __init__(self, submit_exc: Exception | None = None, poll_exc: Exception | None = None) -> None:
        """初始化 fake Provider 并记录待抛出的异常。

        Args:
            submit_exc: submit 调用时应抛出的异常。
            poll_exc: poll 调用时应抛出的异常。

        Returns:
            None
        """
        self._submit_exc = submit_exc
        self._poll_exc = poll_exc

    async def submit(self, prompt: str, image_url: str, params: dict | None = None) -> str:
        """提交任务：有注入异常则抛出，否则返回假厂商任务 ID。

        Args:
            prompt: 视频提示词。
            image_url: 首帧图 URL。
            params: 额外参数。

        Returns:
            str: 假的厂商侧任务 ID。

        Raises:
            Exception: 注入的 submit 异常原样抛出。
        """
        if self._submit_exc is not None:
            raise self._submit_exc
        return "fake-zhipu-task-001"

    async def poll(self, task_id: str) -> dict:
        """查询任务：有注入异常则抛出，否则返回 done 结果。

        Args:
            task_id: submit 返回的任务 ID。

        Returns:
            dict: {"status": "done", "url": ...} 形态的假结果。

        Raises:
            Exception: 注入的 poll 异常原样抛出。
        """
        if self._poll_exc is not None:
            raise self._poll_exc
        return {"status": "done", "url": "https://fake.zhipu/video.mp4"}


def _patch_video_task_env(monkeypatch: pytest.MonkeyPatch, session_factory, fake_provider) -> None:
    """将视频任务模块的会话工厂与 Provider 获取函数替换为测试实现。

    Args:
        monkeypatch: pytest 夹具。
        session_factory: 内存 SQLite 会话工厂（替代 AsyncSessionLocal）。
        fake_provider: 非 mock 名称（如 zhipu）时返回的 Provider 实例。

    Returns:
        None
    """

    def _fake_get_video_provider(name: str | None = None):
        """按名称分派 Provider：mock 返回真实 Mock，其余返回 fake 智谱。

        Args:
            name: Provider 名称。

        Returns:
            VideoProvider: 对应的 Provider 实例。
        """
        if name == "mock":
            return MockVideoProvider()
        return fake_provider

    monkeypatch.setattr("app.tasks.video_tasks.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.tasks.video_tasks._get_video_provider", _fake_get_video_provider)


async def _make_queued_video_task(make_project, make_task, db_session, max_retry: int, error_message: str | None = None) -> int:
    """创建一条 queued 状态、指定 max_retry 的视频任务并返回其 ID。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具（用于补写 max_retry/error_message）。
        max_retry: 最大重试次数（写入任务记录）。
        error_message: 任务初始 error_message（可携带 provider 标记）。

    Returns:
        int: 新建任务 ID。
    """
    project_id = await make_project(title="视频兜底测试项目")
    task_id = await make_task(project_id, task_type=TaskType.VIDEO, status=TaskStatus.QUEUED)
    task = await db_session.get(Task, task_id)
    task.max_retry = max_retry
    task.error_message = error_message
    await db_session.commit()
    return task_id


async def test_zhipu_429_falls_back_to_mock_after_retries_exhausted(
    make_project, make_task, db_session, session_factory, monkeypatch
):
    """智谱 429（可重试异常）重试耗尽 → mock 兜底 DONE+degraded，而非 DEAD。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        session_factory: 内存库会话工厂夹具。
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    fake = _FakeZhipuProvider(
        submit_exc=ZhipuVideoRetryableError("智谱视频 API 返回 429: 余额不足")
    )
    _patch_video_task_env(monkeypatch, session_factory, fake)
    task_id = await _make_queued_video_task(make_project, make_task, db_session, max_retry=1)

    result = await generate_video({}, task_id)

    # 兜底完成：degraded 标记 + DONE + mock 占位视频
    assert result["status"] == "done"
    assert result.get("degraded") is True

    # generate_video 使用独立会话写库，先过期本地缓存再读取，避免 identity map 脏读
    db_session.expire_all()
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.DONE
    assert task.cost_points == 0
    assert "降级生成(mock)" in (task.error_message or "")
    assert "429" in (task.error_message or "")
    assert task.result_url == MockVideoProvider.PLACEHOLDER_VIDEO_URL


async def test_retryable_error_retries_then_falls_back(
    make_project, make_task, db_session, session_factory, monkeypatch
):
    """可重试异常未耗尽 → FAILED 并抛出交 ARQ 重试；耗尽后走 mock 兜底。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        session_factory: 内存库会话工厂夹具。
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    fake = _FakeZhipuProvider(submit_exc=ZhipuVideoRetryableError("智谱视频 API 返回 429: 限流"))
    _patch_video_task_env(monkeypatch, session_factory, fake)
    task_id = await _make_queued_video_task(make_project, make_task, db_session, max_retry=3)

    # 第一次失败：未耗尽 → FAILED + 异常向上抛出（ARQ 退避重试）
    with pytest.raises(ZhipuVideoRetryableError):
        await generate_video({}, task_id)
    # generate_video 使用独立会话写库，先过期本地缓存再读取，避免 identity map 脏读
    db_session.expire_all()
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.retry_count == 1

    # 模拟 ARQ 再次调度且已是最后一次重试（retry_count 达到 max_retry-1）
    task.retry_count = 2
    await db_session.commit()

    result = await generate_video({}, task_id)
    assert result["status"] == "done"
    assert result.get("degraded") is True

    db_session.expire_all()
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.DONE
    assert task.cost_points == 0
    assert "降级生成(mock)" in (task.error_message or "")


async def test_unrecoverable_401_marks_dead_after_retries_exhausted(
    make_project, make_task, db_session, session_factory, monkeypatch
):
    """不可恢复错误（401 鉴权失败，普通 RuntimeError）重试耗尽 → DEAD，不兜底。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        session_factory: 内存库会话工厂夹具。
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    fake = _FakeZhipuProvider(submit_exc=RuntimeError("智谱视频 API 返回 401: unauthorized"))
    _patch_video_task_env(monkeypatch, session_factory, fake)
    task_id = await _make_queued_video_task(make_project, make_task, db_session, max_retry=1)

    result = await generate_video({}, task_id)

    assert result["status"] == "dead"
    # generate_video 使用独立会话写库，先过期本地缓存再读取，避免 identity map 脏读
    db_session.expire_all()
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.DEAD
    assert "401" in (task.error_message or "")
    # 不可恢复错误不产生降级结果
    assert "降级生成(mock)" not in (task.error_message or "")


async def test_mock_provider_explicit_path_unchanged(
    make_project, make_task, db_session, session_factory, monkeypatch
):
    """显式指定 mock（provider=mock 标记）正常生成路径不变：DONE 且 0 点数。

    Args:
        make_project: 项目造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。
        session_factory: 内存库会话工厂夹具。
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    # fake provider 若被误调用会抛错，验证确实走了 mock
    fake = _FakeZhipuProvider(submit_exc=AssertionError("不应调用非 mock provider"))
    _patch_video_task_env(monkeypatch, session_factory, fake)
    task_id = await _make_queued_video_task(
        make_project, make_task, db_session, max_retry=3, error_message="provider=mock;"
    )

    result = await generate_video({}, task_id)

    assert result["status"] == "done"
    assert "degraded" not in result  # 正常 mock 生成不是降级
    # generate_video 使用独立会话写库，先过期本地缓存再读取，避免 identity map 脏读
    db_session.expire_all()
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.DONE
    assert task.cost_points == 0
    assert task.result_url == MockVideoProvider.PLACEHOLDER_VIDEO_URL
