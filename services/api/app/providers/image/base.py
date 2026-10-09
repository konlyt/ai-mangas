"""
图像生成 Provider 抽象基类。

定义所有图像生成厂商（如 Mock、即梦、可灵等）必须实现的统一接口，
便于通过 Registry 进行插拔式替换。
"""

from abc import ABC, abstractmethod
from typing import Optional


class ImageProvider(ABC):
    """图像生成 Provider 抽象基类。

    所有具体图像生成厂商均需继承本类并实现 generate 方法。
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        ref_images: Optional[list[str]] = None,
        params: Optional[dict] = None,
    ) -> str:
        """根据提示词生成图像并返回图像 URL。

        Args:
            prompt: 图像生成提示词。
            ref_images: 参考图 URL 列表，用于图生图或一致性约束。
            params: 额外参数（如尺寸、风格、seed 等）。

        Returns:
            str: 生成图像的访问 URL。

        Raises:
            NotImplementedError: 子类未实现时抛出。
        """
        raise NotImplementedError
