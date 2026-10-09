"""
图像生成 Provider 注册表。

集中管理所有已注册的图像生成 Provider，默认使用 Agnes AI 真实实现
（未配置 Key 或调用失败时在其内部自动降级 mock），同时保留 mock 实现，
通过 get_provider(name) 获取具体实例。
"""

from typing import Optional

from app.core.logging import get_logger
from app.providers.image.agnes import AgnesImageProvider
from app.providers.image.base import ImageProvider
from app.providers.image.mock import MockImageProvider

logger = get_logger()


class ImageProviderRegistry:
    """图像生成 Provider 注册表。

    Attributes:
        _providers: 已注册的 Provider 字典，key 为厂商标识。
        _default: 默认 Provider 名称。
    """

    def __init__(self) -> None:
        """初始化注册表并注册 agnes（默认）与 mock Provider。

        Returns:
            None
        """
        self._providers: dict[str, ImageProvider] = {}
        # 默认使用 Agnes 真实生成；其内部在未配置 Key/调用失败时自动降级 mock
        self._default: str = "agnes"
        self.register("mock", MockImageProvider())
        self.register("agnes", AgnesImageProvider())

    def register(self, name: str, provider: ImageProvider) -> None:
        """注册一个图像生成 Provider。

        Args:
            name: Provider 名称（厂商标识）。
            provider: Provider 实例。

        Returns:
            None
        """
        self._providers[name] = provider
        logger.info(f"[image-registry] 注册 provider: {name}")

    def get_provider(self, name: Optional[str] = None) -> ImageProvider:
        """根据名称获取 Provider 实例。

        Args:
            name: Provider 名称；为 None 时返回默认 Provider。

        Returns:
            ImageProvider: 对应的 Provider 实例。

        Raises:
            ValueError: 当指定名称的 Provider 未注册时抛出。
        """
        target = name or self._default
        provider = self._providers.get(target)
        if provider is None:
            raise ValueError(f"未注册的图像 Provider: {target}")
        return provider

    def list_providers(self) -> list[str]:
        """列出所有已注册的 Provider 名称。

        Returns:
            list[str]: Provider 名称列表。
        """
        return list(self._providers.keys())


# 单例
_image_registry: Optional[ImageProviderRegistry] = None


def get_image_registry() -> ImageProviderRegistry:
    """获取 ImageProviderRegistry 单例。

    Returns:
        ImageProviderRegistry: 全局唯一的图像 Provider 注册表实例。
    """
    global _image_registry
    if _image_registry is None:
        _image_registry = ImageProviderRegistry()
    return _image_registry
