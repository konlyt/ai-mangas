"""
Provider 注册表、Agnes 图像 Provider 降级路径与音色库端点冒烟测试。

覆盖点：
    1. image / video / tts 三个注册表：默认 Provider 解析、按名获取、
       未注册名称抛 ValueError；
    2. AgnesImageProvider 降级路径：
       a) 无效 Key + 不可达网关地址 → 真实调用失败后自动降级 mock
          （返回占位图 URL 且 last_degraded=True）；
       b) 完全未配置 Key/BaseURL → 直接降级 mock；
    3. GET /tts/voices 音色库端点返回非空列表，含 mock 与 agnes 音色。
"""

import pytest

from app.core.config import settings
from app.providers.image.agnes import AgnesImageProvider
from app.providers.image.mock import MockImageProvider
from app.providers.image.registry import get_image_registry
from app.providers.tts.registry import get_tts_registry
from app.providers.video.registry import get_video_registry

# 统一 API 前缀
API_PREFIX = "/api/v1"

# 不可达的本机地址（端口 9 / discard），保证连接立刻被拒绝、测试快速降级
_UNREACHABLE_BASE_URL = "http://127.0.0.1:9/v1"


def test_image_registry():
    """图像注册表：mock/agnes/seedream 已注册，默认解析命中已注册 Provider，未注册名称报 ValueError。

    说明：默认 Provider 由配置决定（配置了 APIMART_API_KEY 时为 seedream，
    否则 agnes，见 ImageProviderRegistry.__init__），与视频注册表一致，
    不硬编码断言默认值，仅验证默认解析机制与显式按名获取。

    Returns:
        None
    """
    registry = get_image_registry()
    assert set(registry.list_providers()) >= {"mock", "agnes", "seedream"}
    default = registry.get_provider(None)
    assert default is registry.get_provider("seedream") or default is registry.get_provider("agnes")
    assert isinstance(registry.get_provider("mock"), MockImageProvider)
    with pytest.raises(ValueError):
        registry.get_provider("no-such-provider")


def test_video_registry():
    """视频注册表：mock/agnes/zhipu 已注册，默认解析命中已注册 Provider，未注册名称报 ValueError。

    说明：默认 Provider 由环境变量 VIDEO_PROVIDER_DEFAULT 决定（工作区并行开发，
    .env 当前为 zhipu），因此不硬编码断言默认值，仅验证默认解析机制与显式按名获取。

    Returns:
        None
    """
    registry = get_video_registry()
    assert set(registry.list_providers()) >= {"mock", "agnes", "zhipu"}
    # 显式按名获取：各已注册 Provider 均可成功解析（未注册名称会抛 ValueError）
    for name in ("mock", "agnes", "zhipu"):
        assert registry.get_provider(name) is not None
    # 默认解析动态断言：get_provider(None) 必须命中注册表中的某个 Provider
    registered = [registry.get_provider(name) for name in registry.list_providers()]
    assert registry.get_provider(None) in registered
    with pytest.raises(ValueError):
        registry.get_provider("no-such-provider")


def test_tts_registry():
    """TTS 注册表：mock/agnes/qianwen 已注册，默认解析命中已注册 Provider，未注册名称报 ValueError。

    说明：默认 Provider 由注册表内部策略决定（当前为 qianwen），不硬编码断言
    默认值，仅验证默认解析机制与显式按名获取。

    Returns:
        None
    """
    registry = get_tts_registry()
    assert set(registry.list_providers()) >= {"mock", "agnes", "qianwen"}
    # 显式按名获取：各已注册 Provider 均可成功解析（未注册名称会抛 ValueError）
    for name in ("mock", "agnes", "qianwen"):
        assert registry.get_provider(name) is not None
    # 默认解析动态断言：get_provider(None) 必须命中注册表中的某个 Provider
    registered = [registry.get_provider(name) for name in registry.list_providers()]
    assert registry.get_provider(None) in registered
    with pytest.raises(ValueError):
        registry.get_provider("no-such-provider")


async def test_agnes_image_degrade_with_invalid_key(monkeypatch):
    """无效 Key + 不可达网关：真实调用抛错后自动降级 mock。

    Args:
        monkeypatch: pytest 夹具，用于临时改写 settings 凭证配置。

    Returns:
        None
    """
    # 模拟配置了无效 Key 的 Agnes 网关（Provider 实例化时读取当前 settings）
    monkeypatch.setattr(settings, "AGNES_BASE_URL", _UNREACHABLE_BASE_URL)
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "sk-invalid")
    provider = AgnesImageProvider()

    url = await provider.generate("测试提示词：一个少年站在未来城市街头")

    # 降级 mock：返回 picsum 占位图 URL，且降级标记置位
    assert url.startswith("https://picsum.photos/seed/")
    assert provider.last_degraded is True


async def test_agnes_image_degrade_when_not_configured(monkeypatch):
    """未配置 Key/BaseURL：跳过网络请求直接降级 mock。

    Args:
        monkeypatch: pytest 夹具，用于临时清空 settings 凭证配置。

    Returns:
        None
    """
    monkeypatch.setattr(settings, "AGNES_BASE_URL", "")
    monkeypatch.setattr(settings, "AGNES_IMAGE_API_KEY", "")
    provider = AgnesImageProvider()

    url = await provider.generate("测试提示词")

    assert url.startswith("https://picsum.photos/seed/")
    assert provider.last_degraded is True


async def test_tts_voices_endpoint(auth_client):
    """音色库端点：返回非空列表，含 mock(default) 与 agnes(alloy) 音色。

    Args:
        auth_client: 已登录测试客户端。

    Returns:
        None
    """
    resp = await auth_client.get(f"{API_PREFIX}/tts/voices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    voices = body["data"]
    assert isinstance(voices, list) and len(voices) > 0, "音色库不应为空"
    for voice in voices:
        assert {"voice_id", "name", "gender", "style", "provider"} <= set(voice.keys())

    voice_ids = {v["voice_id"] for v in voices}
    assert "default" in voice_ids, "应包含 mock 占位音色 default"
    assert "alloy" in voice_ids, "应包含 agnes 默认音色 alloy"
