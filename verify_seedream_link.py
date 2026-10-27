# -*- coding: utf-8 -*-
"""Seedream Provider 项目内真实链路验证（使用 services/api 的配置与注册表）。

验证点：
    1. settings 从项目根 .env 读取 APIMART_API_KEY；
    2. ImageProviderRegistry 默认 Provider 自动切换为 seedream；
    3. i2i：以实测生成的四视图参考板（logs/apimart_test/R1a_board_A.jpg）为
       参考图，走 ref_images 协议 → image_urls 真实消费（last_ref_dropped=False）；
    4. 产物落盘静态目录，返回 /static/... 永久 URL。

Key 仅从 .env 读取，本脚本不落盘任何密钥。
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.core.config import settings  # noqa: E402
from app.providers.image.registry import get_image_registry  # noqa: E402

REF_BOARD = ROOT / "logs" / "apimart_test" / "R1a_board_A.jpg"

PROMPT = (
    "日式动画风格，{{ref 1}}：少女林小满，外观、发型、服装与参考图完全一致。"
    "她坐在教室窗边看向窗外，午后阳光洒在课桌上，窗外是操场与蓝天，"
    "Immutable locks：服装、发型、画风与参考图严格一致，16:9"
)


async def main() -> None:
    print(f"[1] APIMART_API_KEY 已配置: {bool(settings.APIMART_API_KEY)}")
    registry = get_image_registry()
    print(f"[2] 已注册 Provider: {registry.list_providers()}")
    provider = registry.get_provider(None)
    print(f"[3] 默认 Provider: {type(provider).__name__}")
    assert type(provider).__name__ == "SeedreamImageProvider", "默认 Provider 未切换为 seedream"
    assert REF_BOARD.exists(), f"参考板不存在: {REF_BOARD}"

    ref_bytes = REF_BOARD.read_bytes()
    url = await provider.generate(
        PROMPT,
        ref_images=[{"data": ref_bytes, "mime": "image/jpeg"}],
        params={"ratio": "16:9", "resolution": "1.5K"},
    )
    print(f"[4] 产物 URL: {url}")
    print(f"[5] 参考图被真实消费: {not provider.last_ref_dropped}（last_ref_dropped={provider.last_ref_dropped}）")
    print(f"[6] 是否 mock 降级: {provider.last_degraded}")
    assert not provider.last_ref_dropped, "参考图未被消费，i2i 链路未生效"
    assert not provider.last_degraded, "发生了 mock 降级"
    assert url.startswith("/static/"), f"产物未落盘静态目录: {url}"
    print("===== 真实链路验证全部通过 =====")


if __name__ == "__main__":
    asyncio.run(main())
