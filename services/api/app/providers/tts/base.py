"""
语音合成（TTS）Provider 抽象基类。

定义所有语音合成厂商必须实现的统一接口。
"""

from abc import ABC, abstractmethod
from typing import Optional


class TTSProvider(ABC):
    """语音合成 Provider 抽象基类。

    所有具体 TTS 厂商均需继承本类并实现 synthesize 方法。
    """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        params: Optional[dict] = None,
    ) -> str:
        """将文本合成为语音并返回音频 URL。

        Args:
            text: 待合成的文本内容。
            voice_id: 音色 ID。
            params: 额外参数（如语速、音调、音量等）。

        Returns:
            str: 合成音频的访问 URL。

        Raises:
            NotImplementedError: 子类未实现时抛出。
        """
        raise NotImplementedError
