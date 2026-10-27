"""
probe_i2i_queue 脚本单元测试（09 号文档 R15 恢复分支逻辑验证）。

全部通过 monkeypatch 注入假响应 / 假函数，绝不发起真实网络请求、
不触碰真实数据库与报告路径（报告 / 历史日志重定向到 tmp_path）：

    1. probe_i2i 探测判定：
       a) 网关 200 → recovered=True（i2i 恢复）；
       b) 网关 503 → recovered=False（队列仍满）；
       c) 连接异常 → recovered=False 且 status=None；
    2. main 分支编排：
       a) 探测恢复时复测函数被调用且退出码为 2，报告落盘 tmp_path；
       b) 探测未恢复时复测函数不被调用，退出码为 0；
       c) 复测数据带 error 时退出码为 1；
    3. 报告内容断言：恢复场景报告含探测结果 / 两项复测 / 验收结论。
"""

import sys
from pathlib import Path

import httpx
import pytest

# 将 scripts 目录加入 sys.path，按模块名导入自包含脚本
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import probe_i2i_queue as probe_mod  # noqa: E402

# 测试用假网关地址（配合 _load_agnes_config 打桩使用，不发真实请求）
_FAKE_CONFIG = ("https://fake-gateway.test/v1", "sk-test-key", "agnes-image-2.5-flash")


class _FakeResponse:
    """httpx.Response 的最小假实现（status_code / text / json）。

    Attributes:
        status_code: HTTP 状态码。
        text: 响应正文文本。
        _json: json() 方法返回的字典。
    """

    def __init__(self, status_code: int, text: str = "", json_data: dict | None = None) -> None:
        """初始化假响应。

        Args:
            status_code: HTTP 状态码。
            text: 响应正文文本。
            json_data: json() 返回内容；None 时为空字典。
        """
        self.status_code = status_code
        self.text = text
        self._json = json_data if json_data is not None else {}

    def json(self) -> dict:
        """返回预设的 JSON 内容。

        Returns:
            dict: 预设的响应字典。
        """
        return self._json


def _install_fake_client(monkeypatch, response: _FakeResponse | None = None, error: Exception | None = None) -> list[dict]:
    """向 probe 模块注入 httpx.AsyncClient 假实现并记录调用入参。

    Args:
        monkeypatch: pytest 夹具。
        response: post 调用返回的假响应；None 表示不返回。
        error: 非空时 post 抛出该异常（模拟网络故障）。

    Returns:
        list[dict]: 每次 post 的调用入参记录（url/json/headers），供断言。
    """
    calls: list[dict] = []

    class _FakeAsyncClient:
        """httpx.AsyncClient 的最小假实现（异步上下文管理器 + post）。"""

        def __init__(self, **kwargs) -> None:
            """忽略全部构造参数（timeout 等）。

            Args:
                **kwargs: 原实现的关键字参数，测试中一律忽略。
            """

        async def __aenter__(self) -> "_FakeAsyncClient":
            """进入异步上下文，返回自身。

            Returns:
                _FakeAsyncClient: 自身实例。
            """
            return self

        async def __aexit__(self, *args) -> bool:
            """退出异步上下文，不吞异常。

            Args:
                *args: 异常信息（如有）。

            Returns:
                bool: False，异常继续向上传播。
            """
            return False

        async def post(self, url: str, **kwargs) -> _FakeResponse:
            """记录入参并按预设返回响应或抛出异常。

            Args:
                url: 请求地址。
                **kwargs: headers/json 等请求参数。

            Returns:
                _FakeResponse: 预设的假响应。

            Raises:
                Exception: 预设 error 非空时抛出。
            """
            calls.append({"url": url, **kwargs})
            if error is not None:
                raise error
            return response

    monkeypatch.setattr(probe_mod.httpx, "AsyncClient", _FakeAsyncClient)
    return calls


def _patch_config(monkeypatch) -> None:
    """把 _load_agnes_config 打桩为固定假配置，隔离真实 .env。

    Args:
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    monkeypatch.setattr(probe_mod, "_load_agnes_config", lambda: _FAKE_CONFIG)


def _patch_log_paths(monkeypatch, tmp_path: Path) -> None:
    """把报告与历史日志路径重定向到 tmp_path，避免污染项目 logs。

    Args:
        monkeypatch: pytest 夹具。
        tmp_path: pytest 临时目录。

    Returns:
        None
    """
    monkeypatch.setattr(probe_mod, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(probe_mod, "HISTORY_LOG_PATH", tmp_path / "history.log")


# ============================================================
# 1. probe_i2i 探测判定
# ============================================================


async def test_probe_i2i_recovered_on_200(monkeypatch):
    """网关返回 200：判定 i2i 已恢复，状态码与响应要点正确回传。

    Args:
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    calls = _install_fake_client(
        monkeypatch,
        response=_FakeResponse(200, "ok", {"data": [{"url": "https://img.example/a.png"}]}),
    )

    result = await probe_mod.probe_i2i()

    assert result["recovered"] is True
    assert result["status"] == 200
    assert "a.png" in result["detail"]
    # 请求体必须携带 "image" 字段（网关据此分流 i2i 队列）与 model
    assert len(calls) == 1
    assert calls[0]["json"]["image"]
    assert calls[0]["json"]["model"] == _FAKE_CONFIG[2]
    assert calls[0]["url"] == f"{_FAKE_CONFIG[0]}/images/generations"


async def test_probe_i2i_not_recovered_on_503(monkeypatch):
    """网关返回 503（队列满）：判定未恢复。

    Args:
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    _install_fake_client(
        monkeypatch,
        response=_FakeResponse(503, '{"error":{"message":"image queue is full"}}'),
    )

    result = await probe_mod.probe_i2i()

    assert result["recovered"] is False
    assert result["status"] == 503
    assert "image queue is full" in result["detail"]


async def test_probe_i2i_not_recovered_on_4xx(monkeypatch):
    """网关返回 400（4xx）：判定未恢复。

    Args:
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    _install_fake_client(monkeypatch, response=_FakeResponse(400, "bad request"))

    result = await probe_mod.probe_i2i()

    assert result["recovered"] is False
    assert result["status"] == 400


async def test_probe_i2i_not_recovered_on_network_error(monkeypatch):
    """网络层异常（连接拒绝）：判定未恢复且 status 为 None。

    Args:
        monkeypatch: pytest 夹具。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    _install_fake_client(monkeypatch, error=httpx.ConnectError("connection refused"))

    result = await probe_mod.probe_i2i()

    assert result["recovered"] is False
    assert result["status"] is None
    assert "ConnectError" in result["detail"]


# ============================================================
# 2. main 分支编排
# ============================================================


def _make_retest_result(error: str | None = None) -> dict:
    """构造一份 run_reflock_retest 的标准假返回数据。

    Args:
        error: 复测异常摘要；None 表示复测成功。

    Returns:
        dict: 与 run_reflock_retest 返回结构一致的假数据。
    """
    return {
        "ref_source": "characters 表参考板（角色：测试角色）",
        "ref_dropped": [False, False],
        "ref_lock_triggered": True,
        "generated_urls": ["https://img.example/shot1.png", "https://img.example/shot2.png"],
        "similarity": {
            "hash_similarity": 0.72,
            "histogram_similarity": 0.81,
            "score": 0.756,
            "reference_hash": "a" * 16,
            "candidate_hash": "b" * 16,
        },
        "baseline": 0.58,
        "above_baseline": True,
        "significantly_above": True,
        "error": error,
    }


async def test_main_triggers_retest_and_returns_2_when_recovered(monkeypatch, tmp_path):
    """探测恢复：复测函数被恰好调用一次、报告落盘、退出码为 2。

    Args:
        monkeypatch: pytest 夹具。
        tmp_path: pytest 临时目录。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    _patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        probe_mod,
        "probe_i2i",
        lambda: _async_return({"recovered": True, "status": 200, "detail": "https://img.example/x.png"}),
    )
    call_count = {"n": 0}

    async def _fake_retest() -> dict:
        """替身复测函数：记录被调用次数并返回成功数据。

        Returns:
            dict: 标准假复测数据。
        """
        call_count["n"] += 1
        return _make_retest_result()

    monkeypatch.setattr(probe_mod, "run_reflock_retest", _fake_retest)

    code = await probe_mod.main()

    assert call_count["n"] == 1  # 恢复时复测函数被调用
    assert code == 2
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "i2i 恢复复测报告" in report
    assert "ref_lock" in report
    assert "0.756" in report  # 复测得分写入报告
    assert "正式验收" in report
    history = (tmp_path / "history.log").read_text(encoding="utf-8")
    assert "复测完成" in history


async def test_main_skips_retest_and_returns_0_when_not_recovered(monkeypatch, tmp_path):
    """探测未恢复：复测函数不被调用、不写报告、退出码为 0。

    Args:
        monkeypatch: pytest 夹具。
        tmp_path: pytest 临时目录。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    _patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        probe_mod,
        "probe_i2i",
        lambda: _async_return({"recovered": False, "status": 503, "detail": "image queue is full"}),
    )

    async def _unexpected_retest() -> dict:
        """替身复测函数：被调用即断言失败。

        Raises:
            AssertionError: 未恢复场景下不应执行复测。
        """
        raise AssertionError("未恢复时不应执行复测")

    monkeypatch.setattr(probe_mod, "run_reflock_retest", _unexpected_retest)

    code = await probe_mod.main()

    assert code == 0
    assert not (tmp_path / "report.md").exists()


async def test_main_returns_1_when_retest_has_error(monkeypatch, tmp_path):
    """复测数据带 error：退出码为 1（恢复但复测异常）。

    Args:
        monkeypatch: pytest 夹具。
        tmp_path: pytest 临时目录。

    Returns:
        None
    """
    _patch_config(monkeypatch)
    _patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        probe_mod,
        "probe_i2i",
        lambda: _async_return({"recovered": True, "status": 200, "detail": "ok"}),
    )

    async def _failing_retest() -> dict:
        """替身复测函数：返回带 error 的复测数据。

        Returns:
            dict: error 字段非空的假复测数据。
        """
        return _make_retest_result(error="RuntimeError: 产物下载失败 HTTP 404")

    monkeypatch.setattr(probe_mod, "run_reflock_retest", _failing_retest)

    code = await probe_mod.main()

    assert code == 1
    assert (tmp_path / "report.md").exists()  # 报告仍应落盘（可能不完整）


# ============================================================
# 辅助
# ============================================================


def _async_return(value: dict):
    """构造直接返回给定值的 awaitable，替身 async 函数用。

    Args:
        value: 要返回的字典。

    Returns:
        可 await 的协程对象。
    """

    async def _inner() -> dict:
        """返回预设值。

        Returns:
            dict: 预设字典。
        """
        return value

    return _inner()


def test_module_importable():
    """脚本模块可被独立导入（自包含脚本的基本要求）。

    Returns:
        None
    """
    assert probe_mod.PROBE_SIZE == 512
    assert probe_mod.BASELINE_SCORE == 0.58
