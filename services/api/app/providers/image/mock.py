"""
图像生成 Mock Provider。

用于开发与测试环境，返回一个 picsum 占位图 URL，不产生真实调用费用。
"""

import random

from app.providers.image.base import ImageProvider


class MockImageProvider(ImageProvider):
    """Mock 图像生成 Provider。

    返回基于 picsum.photos 的随机占位图 URL，模拟真实图像生成结果。
    """

    async def generate(
        self,
        prompt: str,
        ref_images: list[dict] | None = None,
        params: dict | None = None,
    ) -> str:
        """生成占位图 URL。

        Args:
            prompt: 图像提示词（mock 模式下仅作日志用途）。
            ref_images: 参考图列表（方案 A2 协议 [{data, mime}]）。
                mock 不消费参考图，仅接受该参数以保持与 base 协议签名兼容。
            params: 额外参数，可包含 width/height 控制占位图尺寸。

        Returns:
            str: picsum 占位图 URL。
        """
        width = (params or {}).get("width", 1024)
        height = (params or {}).get("height", 1024)
        seed = random.randint(1, 100000)
        return f"https://picsum.photos/seed/{seed}/{width}/{height}"
