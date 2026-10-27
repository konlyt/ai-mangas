"""
视频生成 Provider 注册表。

集中管理所有已注册的视频生成 Provider，默认使用 Agnes AI 真实实现
（未配置 Key 或调用失败时在其内部自动降级 mock），同时保留 mock 实现，
通过 get_provider(name) 获取具体实例。
"""

from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.video.agnes import AgnesVideoProvider
from app.providers.video.base import VideoProvider
from app.providers.video.minimax import MinimaxVideoProvider
from app.providers.video.mock import MockVideoProvider
from app.providers.video.zhipu import ZhipuVideoProvider

logger = get_logger()


class VideoProviderRegistry:
    """视频生成 Provider 注册表。

    Attributes:
        _providers: 已注册的 Provider 字典，key 为厂商标识。
        _default: 默认 Provider 名称。
    """

    def __init__(self) -> None:
        """初始化注册表并注册各厂商 Provider。

        Returns:
            None
        """
        self._providers: dict[str, VideoProvider] = {}
        # 默认视频 Provider，可通过环境变量 VIDEO_PROVIDER_DEFAULT 配置
        self._default: str = getattr(settings, "VIDEO_PROVIDER_DEFAULT", "zhipu")
        self.register("mock", MockVideoProvider())
        self.register("agnes", AgnesVideoProvider())
        self.register("zhipu", ZhipuVideoProvider())
        self.register("minimax", MinimaxVideoProvider())

    def register(self, name: str, provider: VideoProvider) -> None:
        """注册一个视频生成 Provider。

        Args:
            name: Provider 名称（厂商标识）。
            provider: Provider 实例。

        Returns:
            None
        """
        self._providers[name] = provider
        logger.info(f"[video-registry] 注册 provider: {name}")

    def get_provider(self, name: Optional[str] = None) -> VideoProvider:
        """根据名称获取 Provider 实例。

        Args:
            name: Provider 名称；为 None 时返回默认 Provider。

        Returns:
            VideoProvider: 对应的 Provider 实例。

        Raises:
            ValueError: 当指定名称的 Provider 未注册时抛出。
        """
        target = name or self._default
        provider = self._providers.get(target)
        if provider is None:
            raise ValueError(f"未注册的视频 Provider: {target}")
        return provider

    def list_providers(self) -> list[str]:
        """列出所有已注册的 Provider 名称。

        Returns:
            list[str]: Provider 名称列表。
        """
        return list(self._providers.keys())


# 单例
_video_registry: Optional[VideoProviderRegistry] = None


def get_video_registry() -> VideoProviderRegistry:
    """获取 VideoProviderRegistry 单例。

    Returns:
        VideoProviderRegistry: 全局唯一的视频 Provider 注册表实例。
    """
    global _video_registry
    if _video_registry is None:
        _video_registry = VideoProviderRegistry()
    return _video_registry
