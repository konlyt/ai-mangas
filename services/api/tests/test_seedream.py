"""
SeedreamImageProvider（APIMart 异步任务型图像 Provider）单元测试。

覆盖点：
    1. 未配置 Key → 直接降级 mock，带参考图时 last_ref_dropped=True；
    2. 纯 t2i 全链路：提交 → task_id → 轮询 completed → 产物下载落盘，
       返回 /static/... 永久 URL（实测包裹结构 {"code":200,"data":{...}}、
       终态 "completed"、result.images[0].url 为数组均按实测模拟）；
    3. i2i：ref_images（bytes/裸 base64/data URI/http URL 混合形态）
       全量转为 image_urls 注入请求体，参考图被真实消费（last_ref_dropped=False）；
    4. 降级链：i2i 任务终态 failed → 自动降级纯 t2i 重试（请求体不含
       image_urls，last_ref_dropped=True）→ 成功返回；
    5. 完整降级：i2i 提交 400 + t2i 提交 400 → mock 兜底
       （last_ref_dropped=True、last_degraded=True，不抛异常）。
"""

import base64
import json

import pytest

from app.providers.image import seedream as seedream_module
from app.providers.image.mock import MockImageProvider
from app.providers.image.seedream import SeedreamImageProvider

# 伪造的 /static 产物 URL（save_artifact 被 monkeypatch 后返回）
_FAKE_STATIC_URL = "/static/images/test_seedream.png"
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)


def _install_fake_httpx(monkeypatch, handler, poll_interval: float = 0.0) -> list[dict]:
    """将 seedream 模块内的 httpx 替换为按 handler 路由的伪造实现，并捕获请求。

    Args:
        monkeypatch: pytest 夹具。
        handler: Callable[[str, str, dict | None], tuple[int, dict | bytes]]，
            按 (method, url, json_body) 返回 (status_code, 响应体)；
            响应体为 dict（JSON）或 bytes（二进制产物）。
        poll_interval: 覆盖模块级轮询间隔（默认 0 加速测试）。

    Returns:
        list[dict]: 请求记录（method/url/json）。
    """
    captured: list[dict] = []

    class _FakeResponse:
        def __init__(self, status_code: int, payload) -> None:
            self.status_code = status_code
            self._payload = payload
            if isinstance(payload, (bytes, bytearray)):
                self.content = bytes(payload)
                self.text = "<binary>"
            else:
                self.content = json.dumps(payload).encode()
                self.text = json.dumps(payload, ensure_ascii=False)

        def json(self) -> dict:
            return self._payload

    class _FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url: str, headers=None, json=None):
            captured.append({"method": "POST", "url": url, "json": json})
            status, payload = handler("POST", url, json)
            return _FakeResponse(status, payload)

        async def get(self, url: str, headers=None):
            captured.append({"method": "GET", "url": url, "json": None})
            status, payload = handler("GET", url, None)
            return _FakeResponse(status, payload)

    class _FakeHttpx:
        AsyncClient = _FakeAsyncClient

    monkeypatch.setattr(seedream_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(seedream_module, "POLL_INTERVAL", poll_interval)
    return captured


@pytest.fixture()
def _no_key(monkeypatch):
    monkeypatch.setattr(seedream_module.settings, "APIMART_API_KEY", "")
    monkeypatch.setattr(seedream_module.settings, "APIMART_BASE_URL", "http://127.0.0.1:9/v1")


@pytest.fixture()
def _with_key(monkeypatch):
    monkeypatch.setattr(seedream_module.settings, "APIMART_API_KEY", "test-key")
    monkeypatch.setattr(seedream_module.settings, "APIMART_BASE_URL", "http://apimart.test/v1")
    monkeypatch.setattr(seedream_module.settings, "SEEDREAM_IMAGE_MODEL", "seedream-5-0-flash")


@pytest.fixture()
def _fake_save(monkeypatch):
    monkeypatch.setattr(seedream_module, "save_artifact", lambda data, sub, ext: _FAKE_STATIC_URL)


@pytest.mark.asyncio
async def test_no_key_falls_back_to_mock(_no_key):
    """未配置 Key：直接降级 mock；参考图被丢弃（last_ref_dropped=True）。"""
    provider = SeedreamImageProvider()
    url = await provider.generate("测试提示词", ref_images=[{"data": b"abc", "mime": "image/png"}])
    assert url
    assert provider.last_degraded is True
    assert provider.last_ref_dropped is True


@pytest.mark.asyncio
async def test_t2i_full_pipeline(_with_key, _fake_save, monkeypatch):
    """纯 t2i：提交 → 轮询 completed（包裹结构）→ 下载落盘返回 /static URL。"""
    calls = {"poll": 0}

    def handler(method: str, url: str, body):
        if method == "POST" and url.endswith("/images/generations"):
            assert body["model"] == "seedream-5-0-flash"
            assert "image_urls" not in body
            return 200, {"code": 200, "data": [{"status": "submitted", "task_id": "task_t2i"}]}
        if method == "GET" and "/tasks/task_t2i" in url:
            calls["poll"] += 1
            return 200, {"code": 200, "data": {
                "id": "task_t2i", "status": "completed", "progress": 100, "cost": 0.0137,
                "result": {"images": [{"url": ["https://cdn.test/out.png"],
                                       "sizes": ["1536x1536"], "output_formats": ["png"]}]},
            }}
        if method == "GET" and url.startswith("https://cdn.test/"):
            return 200, _PNG_1PX
        return 500, {"error": "unexpected"}

    _install_fake_httpx(monkeypatch, handler)
    provider = SeedreamImageProvider()
    url = await provider.generate("日式动画风格少女")
    assert url == _FAKE_STATIC_URL
    assert provider.last_degraded is False
    assert provider.last_ref_dropped is False
    assert calls["poll"] >= 1


@pytest.mark.asyncio
async def test_i2i_refs_injected_as_image_urls(_with_key, _fake_save, monkeypatch):
    """i2i：ref_images 混合形态全量转 data URI/URL 注入 image_urls，消费成功。"""
    seen: dict = {}

    def handler(method: str, url: str, body):
        if method == "POST" and url.endswith("/images/generations"):
            seen["body"] = body
            return 200, {"code": 200, "data": [{"status": "submitted", "task_id": "task_i2i"}]}
        if method == "GET" and "/tasks/task_i2i" in url:
            return 200, {"code": 200, "data": {
                "status": "completed", "progress": 100,
                "result": {"images": [{"url": ["https://cdn.test/out.png"]}]},
            }}
        if method == "GET" and url.startswith("https://cdn.test/"):
            return 200, _PNG_1PX
        return 500, {"error": "unexpected"}

    _install_fake_httpx(monkeypatch, handler)
    provider = SeedreamImageProvider()
    refs = [
        {"data": b"binary-bytes", "mime": "image/png"},          # bytes → data URI
        {"data": "aGVsbG8=", "mime": "image/jpeg"},               # 裸 base64 → 补前缀
        {"data": "data:image/webp;base64,AAAA", "mime": "image/webp"},  # data URI 透传
        {"data": "https://cdn.test/ref.png", "mime": "image/png"},      # http URL 透传
    ]
    url = await provider.generate("{{ref 1}} 少女", ref_images=refs)
    assert url == _FAKE_STATIC_URL
    assert provider.last_ref_dropped is False
    image_urls = seen["body"]["image_urls"]
    assert len(image_urls) == 4
    assert image_urls[0].startswith("data:image/png;base64,")
    assert image_urls[0].endswith(base64.b64encode(b"binary-bytes").decode())
    assert image_urls[1] == "data:image/jpeg;base64,aGVsbG8="
    assert image_urls[2] == "data:image/webp;base64,AAAA"
    assert image_urls[3] == "https://cdn.test/ref.png"


@pytest.mark.asyncio
async def test_i2i_failed_task_falls_back_to_t2i(_with_key, _fake_save, monkeypatch):
    """i2i 任务终态 failed → 降级纯 t2i 重试（不含 image_urls）→ 成功。"""
    submits: list[dict] = []

    def handler(method: str, url: str, body):
        if method == "POST" and url.endswith("/images/generations"):
            submits.append(body)
            if "image_urls" in body:
                return 200, {"code": 200, "data": [{"status": "submitted", "task_id": "task_bad"}]}
            return 200, {"code": 200, "data": [{"status": "submitted", "task_id": "task_good"}]}
        if method == "GET" and "/tasks/task_bad" in url:
            return 200, {"code": 200, "data": {"status": "failed", "progress": 0,
                                               "error": "content policy"}}
        if method == "GET" and "/tasks/task_good" in url:
            return 200, {"code": 200, "data": {
                "status": "completed", "progress": 100,
                "result": {"images": [{"url": ["https://cdn.test/out.png"]}]},
            }}
        if method == "GET" and url.startswith("https://cdn.test/"):
            return 200, _PNG_1PX
        return 500, {"error": "unexpected"}

    _install_fake_httpx(monkeypatch, handler)
    provider = SeedreamImageProvider()
    url = await provider.generate("新镜头", ref_images=[{"data": b"abc", "mime": "image/png"}])
    assert url == _FAKE_STATIC_URL
    assert provider.last_ref_dropped is True
    assert provider.last_degraded is False
    assert len(submits) == 2
    assert "image_urls" in submits[0]
    assert "image_urls" not in submits[1]


@pytest.mark.asyncio
async def test_full_degrade_to_mock(_with_key, _fake_save, monkeypatch):
    """i2i 提交 400 + t2i 提交 400 → mock 兜底，双标记置位，不抛异常。"""

    def handler(method: str, url: str, body):
        if method == "POST" and url.endswith("/images/generations"):
            return 400, {"error": {"code": "invalid_size", "message": "bad request"}}
        return 500, {"error": "unexpected"}

    _install_fake_httpx(monkeypatch, handler)
    provider = SeedreamImageProvider()
    url = await provider.generate("提示词", ref_images=[{"data": b"abc", "mime": "image/png"}])
    assert url  # mock 占位图 URL
    assert provider.last_ref_dropped is True
    assert provider.last_degraded is True


@pytest.mark.asyncio
async def test_poll_timeout_raises_and_degrades(_with_key, _fake_save, monkeypatch):
    """轮询一直 pending 至超时 → 降级纯 t2i（同样超时）→ mock 兜底。"""
    monkeypatch.setattr(SeedreamImageProvider, "POLL_MAX_WAIT", 0.05)

    def handler(method: str, url: str, body):
        if method == "POST" and url.endswith("/images/generations"):
            return 200, {"code": 200, "data": [{"status": "submitted", "task_id": "task_slow"}]}
        if method == "GET" and "/tasks/task_slow" in url:
            return 200, {"code": 200, "data": {"status": "pending", "progress": 0}}
        return 500, {"error": "unexpected"}

    _install_fake_httpx(monkeypatch, handler, poll_interval=0.01)
    provider = SeedreamImageProvider()
    url = await provider.generate("提示词")
    assert url
    assert provider.last_degraded is True
    assert provider.last_ref_dropped is False  # 无参考图，不置丢弃标记
