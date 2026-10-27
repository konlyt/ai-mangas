"""
图像 Provider 参考图（ref_images，方案 A2）接口测试。

覆盖点：
    1. MockImageProvider：接受 ref_images 且不消费（签名兼容，正常返回占位图）；
    2. AgnesImageProvider 无 ref_images：行为与旧版一致（未配置凭证 → 直接降级
       mock），last_ref_dropped 保持 False；
    3. AgnesImageProvider 带 ref_images（通过伪造 httpx.AsyncClient 精确验证）：
       a) i2i 请求按协议构造：body 含 "image" 字段（首张参考图裸 base64），
          不含网关显式拒绝的 "ref_images" 字段；
       b) data URI / 裸 base64 字符串形态的参考图同样可被提取；
       c) i2i 通道失败（400）→ 自动降级纯 t2i 继续出图
          （last_ref_dropped=True、last_degraded=False，返回 t2i 产物 URL）；
       d) 参考图仅含 http URL（无法直接用作 i2i base64）→ 跳过 i2i 直接 t2i；
    4. 完整降级链（无效 Key + 不可达网关，不依赖伪造客户端）：
       i2i 失败 → t2i 失败 → mock，全程不抛异常，双标记置位。
"""

import base64
import json

from app.core.config import settings
from app.providers.image import agnes as agnes_module
from app.providers.image.agnes import AgnesImageProvider
from app.providers.image.mock import MockImageProvider

# 不可达的本机地址（端口 9 / discard），保证连接立刻被拒绝、测试快速降级
_UNREACHABLE_BASE_URL = "http://127.0.0.1:9/v1"


class _FakeHttpxModule:
    """伪造的 httpx 模块壳，仅暴露被 agnes.py 使用的 AsyncClient。"""

    AsyncClient = None  # 由 _install_fake_httpx 动态注入


def _install_fake_httpx(monkeypatch, status_for) -> list[dict]:
    """将 agnes 模块内的 httpx.AsyncClient 替换为伪造实现，捕获请求体。

    Args:
        monkeypatch: pytest 夹具，用于替换 agnes_module.httpx 并在用例结束后还原。
        status_for: Callable[[dict], tuple[int, dict]]，根据请求体返回
            (HTTP 状态码, 响应 JSON)，用于模拟 i2i/t2i 通道的不同行为。

    Returns:
        list[dict]: 捕获的请求记录列表，每项含 "url"、"headers"、"json" 三个键。
    """
    captured: list[dict] = []

    class _FakeResponse:
        """伪造的 httpx.Response，仅实现 agnes 解析路径用到的属性。"""

        def __init__(self, status_code: int, payload: dict) -> None:
            """保存状态码与响应体。

            Args:
                status_code: HTTP 状态码。
                payload: 响应 JSON 对象。
            """
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload, ensure_ascii=False)

        def json(self) -> dict:
            """返回响应 JSON 对象。

            Returns:
                dict: 响应 JSON。
            """
            return self._payload

    class _FakeAsyncClient:
        """伪造的 httpx.AsyncClient（异步上下文管理器 + post 记录）。"""

        def __init__(self, **kwargs) -> None:
            """接收并忽略超时等构造参数。

            Args:
                **kwargs: 原生 AsyncClient 的构造参数（本伪实现全部忽略）。
            """
            del kwargs

        async def __aenter__(self) -> "_FakeAsyncClient":
            """进入异步上下文。

            Returns:
                _FakeAsyncClient: 自身实例。
            """
            return self

        async def __aexit__(self, *args) -> bool:
            """退出异步上下文（无资源需要释放）。

            Args:
                *args: 异常信息（若有）。

            Returns:
                bool: 不吞异常。
            """
            del args
            return False

        async def post(self, url: str, headers: dict | None = None, json: dict | None = None) -> _FakeResponse:
            """记录请求并按 status_for 规则返回伪造响应。

            Args:
                url: 请求地址。
                headers: 请求头。
                json: 请求体。

            Returns:
                _FakeResponse: 按 status_for 规则构造的伪造响应。
            """
            captured.append({"url": url, "headers": headers, "json": json})
            status_code, payload = status_for(json or {})
            return _FakeResponse(status_code, payload)

    fake_module = type(_FakeHttpxModule.__name__, (_FakeHttpxModule,), {"AsyncClient": _FakeAsyncClient})
    monkeypatch.setattr(agnes_module, "httpx", fake_module)
    return captured


async def test_mock_provider_accepts_ref_images():
    """mock Provider：接受 ref_images 不报错，且不消费参考图（返回占位图）。

    Returns:
        None
    """
    provider = MockImageProvider()
    url = await provider.generate(
        "测试提示词：主角特写",
        ref_images=[{"data": b"\x89PNG-fake-bytes", "mime": "image/png"}],
        params={"width": 512, "height": 512},
    )
    assert url.startswith("https://picsum.photos/seed/")


async def test_agnes_without_ref_behavior_unchanged(monkeypatch):
    """无 ref_images：行为与旧版一致（未配置凭证 → 直接降级 mock），ref 标记不置位。

    Args:
        monkeypatch: pytest 夹具，用于清空 settings 凭证配置。

    Returns:
        None
    """
    monkeypatch.setattr(settings, "AGNES_BASE_URL", "")
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "")
    provider = AgnesImageProvider()

    url = await provider.generate("测试提示词：一个少年站在未来城市街头")

    assert url.startswith("https://picsum.photos/seed/")
    assert provider.last_degraded is True
    assert provider.last_ref_dropped is False


async def test_agnes_i2i_request_built_with_first_ref(monkeypatch):
    """带 ref_images：i2i 请求按协议构造（"image"=首张裸 base64，无 "ref_images" 字段）。

    Args:
        monkeypatch: pytest 夹具，用于注入伪造 httpx 与凭证配置。

    Returns:
        None
    """
    monkeypatch.setattr(settings, "AGNES_BASE_URL", "https://fake.agnes.example/v1")
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "sk-test")
    captured = _install_fake_httpx(
        monkeypatch,
        lambda body: (200, {"data": [{"url": "https://img.example/i2i.png", "b64_json": ""}]}),
    )
    provider = AgnesImageProvider()

    url = await provider.generate(
        "主角特写：保持参考图角色外观",
        ref_images=[
            {"data": b"fake-png-bytes-1", "mime": "image/png"},
            {"data": b"fake-png-bytes-2", "mime": "image/png"},
        ],
    )

    # i2i 成功：返回 i2i 产物 URL，参考图未被丢弃
    assert url == "https://img.example/i2i.png"
    assert provider.last_ref_dropped is False
    assert provider.last_degraded is False
    # 仅发起一次请求（i2i），端点与请求体符合协议
    assert len(captured) == 1
    assert captured[0]["url"].endswith("/images/generations")
    body = captured[0]["json"]
    assert body["image"] == base64.b64encode(b"fake-png-bytes-1").decode("ascii")  # 多张仅取首张
    assert "ref_images" not in body  # 实测网关对 "ref_images" 字段返回 400，不可使用


async def test_agnes_i2i_accepts_data_uri_and_b64_str(monkeypatch):
    """参考图为 data URI / 裸 base64 字符串形态时同样可被提取用于 i2i。

    Args:
        monkeypatch: pytest 夹具，用于注入伪造 httpx 与凭证配置。

    Returns:
        None
    """
    monkeypatch.setattr(settings, "AGNES_BASE_URL", "https://fake.agnes.example/v1")
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "sk-test")
    captured = _install_fake_httpx(
        monkeypatch,
        lambda body: (200, {"data": [{"url": "https://img.example/i2i.png", "b64_json": ""}]}),
    )
    provider = AgnesImageProvider()

    url = await provider.generate(
        "主角特写",
        ref_images=[{"data": "data:image/png;base64,QUJD", "mime": "image/png"}],
    )

    assert url == "https://img.example/i2i.png"
    assert captured[0]["json"]["image"] == "QUJD"  # data URI 前缀被剥离


async def test_agnes_i2i_failure_degrades_to_t2i(monkeypatch):
    """i2i 通道失败（400）→ 自动降级纯 t2i 继续出图（不是 mock）。

    Args:
        monkeypatch: pytest 夹具，用于注入伪造 httpx 与凭证配置。

    Returns:
        None
    """

    def _status_for(body: dict) -> tuple[int, dict]:
        """i2i 请求返回 400（模拟网关 i2i 队列不可用），纯 t2i 请求返回 200。

        Args:
            body: 请求体。

        Returns:
            tuple[int, dict]: (状态码, 响应 JSON)。
        """
        if "image" in body:
            return 503, {"error": {"message": "image queue is full"}}
        return 200, {"data": [{"url": "https://img.example/t2i.png", "b64_json": ""}]}

    captured = _install_fake_httpx(monkeypatch, _status_for)
    monkeypatch.setattr(settings, "AGNES_BASE_URL", "https://fake.agnes.example/v1")
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "sk-test")
    provider = AgnesImageProvider()

    url = await provider.generate(
        "主角特写",
        ref_images=[{"data": b"fake-png-bytes", "mime": "image/png"}],
    )

    # 降级 t2i 成功：返回 t2i 产物 URL，参考图被丢弃但未触发 mock 降级
    assert url == "https://img.example/t2i.png"
    assert provider.last_ref_dropped is True
    assert provider.last_degraded is False
    # 共两次请求：第一次 i2i（带 image，503），第二次纯 t2i（不带 image）
    assert len(captured) == 2
    assert "image" in captured[0]["json"]
    assert "image" not in captured[1]["json"]


async def test_agnes_url_refs_skip_i2i(monkeypatch):
    """参考图仅含 http URL（历史 list[str] 形态）→ 无法用作 i2i base64，跳过 i2i 直接 t2i。

    Args:
        monkeypatch: pytest 夹具，用于注入伪造 httpx 与凭证配置。

    Returns:
        None
    """
    captured = _install_fake_httpx(
        monkeypatch,
        lambda body: (200, {"data": [{"url": "https://img.example/t2i.png", "b64_json": ""}]}),
    )
    monkeypatch.setattr(settings, "AGNES_BASE_URL", "https://fake.agnes.example/v1")
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "sk-test")
    provider = AgnesImageProvider()

    url = await provider.generate("主角特写", ref_images=["https://cdn.example/pose.png"])

    assert url == "https://img.example/t2i.png"
    assert provider.last_ref_dropped is True  # 参考图被提供但最终未被消费
    assert len(captured) == 1
    assert "image" not in captured[0]["json"]


async def test_agnes_with_refs_full_degrade_chain(monkeypatch):
    """完整降级链（真实网络层，不可达网关）：i2i 失败 → t2i 失败 → mock，全程不抛异常。

    Args:
        monkeypatch: pytest 夹具，用于配置不可达网关与无效 Key。

    Returns:
        None
    """
    monkeypatch.setattr(settings, "AGNES_BASE_URL", _UNREACHABLE_BASE_URL)
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "sk-invalid")
    provider = AgnesImageProvider()

    url = await provider.generate(
        "测试提示词",
        ref_images=[{"data": b"fake-png-bytes", "mime": "image/png"}],
    )

    assert url.startswith("https://picsum.photos/seed/")
    assert provider.last_ref_dropped is True
    assert provider.last_degraded is True
