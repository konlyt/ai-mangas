"""
图像生成 Provider 抽象基类。

定义所有图像生成厂商（如 Mock、Agnes、即梦、可灵等）必须实现的统一接口，
便于通过 Registry 进行插拔式替换。

参考图协议（方案 A2，与《项目开发文档/06-角色一致性技术方案建议》及
《07-无限画布与人物一致性优化重构方案》中的 ref_images 预留位对齐）：

    ref_images: Optional[list[dict]] = None

    每项形如 {"data": bytes | str(base64), "mime": "image/png" | ...}：
      - data: 参考图二进制内容（bytes）或裸 base64 字符串（兼容 data URI 形态）；
      - mime: 图片 MIME 类型（如 image/png、image/jpeg），
        供支持参考图的厂商注入请求头/请求体。

降级约定（保证业务流程不中断，且不产出"假参考图生效"的错觉）：
    1. Provider 原生支持参考图 → 携带参考图真实调用图生图（i2i）；
    2. Provider/网关不支持参考图（非 200、超时等）→ 记录 warning 后
       降级为纯文生图（t2i）继续出图（t2i 队列独立可用，并非 mock）；
    3. 仅当纯 t2i 也失败时 → 才降级 mock 占位图或向上抛错。
    实现方建议暴露 last_ref_dropped 实例属性，标识"本次传入的参考图
    最终是否未被消费"，供调用方诊断（接口返回 str URL 时无法内嵌标记）。
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
        ref_images: Optional[list[dict]] = None,
        params: Optional[dict] = None,
    ) -> str:
        """根据提示词生成图像并返回图像 URL。

        Args:
            prompt: 图像生成提示词。
            ref_images: 参考图列表（可选，方案 A2 协议）。每项为
                {"data": bytes | str(base64), "mime": "image/png" | ...}；
                Provider 原生支持时用于图生图（i2i）/一致性约束，
                不支持时按模块 docstring 的降级约定回退纯 t2i。
            params: 额外参数（如尺寸、风格、seed 等）。

        Returns:
            str: 生成图像的访问 URL。

        Raises:
            NotImplementedError: 子类未实现时抛出。
        """
        raise NotImplementedError
