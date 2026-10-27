"""
语音合成 Provider 注册表。

集中管理所有已注册的 TTS Provider，默认使用 Agnes AI 实现
（当前网关暂不支持 TTS，其内部自动降级 mock），同时保留 mock 实现，
通过 get_provider(name) 获取具体实例。
"""

from typing import Optional

from app.core.logging import get_logger
from app.providers.tts.agnes import AgnesTTSProvider
from app.providers.tts.base import TTSProvider
from app.providers.tts.mock import MockTTSProvider
from app.providers.tts.qianwen import QianwenTTSProvider

logger = get_logger()


class TTSProviderRegistry:
    """语音合成 Provider 注册表。

    Attributes:
        _providers: 已注册的 Provider 字典，key 为厂商标识。
        _default: 默认 Provider 名称。
    """

    def __init__(self) -> None:
        """初始化注册表并注册 qianwen（默认）、agnes 与 mock Provider。

        Returns:
            None
        """
        self._providers: dict[str, TTSProvider] = {}
        # 默认使用通义千问 qwen3-tts-flash（已实测可用），失败自动降级 mock
        self._default: str = "qianwen"
        self.register("mock", MockTTSProvider())
        self.register("agnes", AgnesTTSProvider())
        self.register("qianwen", QianwenTTSProvider())

    def register(self, name: str, provider: TTSProvider) -> None:
        """注册一个 TTS Provider。

        Args:
            name: Provider 名称（厂商标识）。
            provider: Provider 实例。

        Returns:
            None
        """
        self._providers[name] = provider
        logger.info(f"[tts-registry] 注册 provider: {name}")

    def get_provider(self, name: Optional[str] = None) -> TTSProvider:
        """根据名称获取 Provider 实例。

        Args:
            name: Provider 名称；为 None 时返回默认 Provider。

        Returns:
            TTSProvider: 对应的 Provider 实例。

        Raises:
            ValueError: 当指定名称的 Provider 未注册时抛出。
        """
        target = name or self._default
        provider = self._providers.get(target)
        if provider is None:
            raise ValueError(f"未注册的 TTS Provider: {target}")
        return provider

    def list_providers(self) -> list[str]:
        """列出所有已注册的 Provider 名称。

        Returns:
            list[str]: Provider 名称列表。
        """
        return list(self._providers.keys())


# 单例
_tts_registry: Optional[TTSProviderRegistry] = None


def get_tts_registry() -> TTSProviderRegistry:
    """获取 TTSProviderRegistry 单例。

    Returns:
        TTSProviderRegistry: 全局唯一的 TTS Provider 注册表实例。
    """
    global _tts_registry
    if _tts_registry is None:
        _tts_registry = TTSProviderRegistry()
    return _tts_registry
