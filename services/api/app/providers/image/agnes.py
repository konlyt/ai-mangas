"""
Agnes AI 图像生成 Provider。

通过 Agnes AI APIHub（OpenAI 兼容网关）的 /images/generations 端点
真实生成图像。实测响应结构（2026-10-08）：

    {"data": [{"url": "https://...png", "b64_json": "", "revised_prompt": ""}],
     "created": 1791427346, "task_id": "task_xxx"}

即优先返回产物 URL；若后续返回 b64_json 则解码落盘到静态目录。
任何网络/HTTP 异常均记录 error 日志后降级为 Mock 实现，
保证上层业务流程（agent/任务队列）不中断。
"""

import base64

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.image.base import ImageProvider
from app.providers.image.mock import MockImageProvider
from app.providers.storage import save_artifact

logger = get_logger()


class AgnesImageProvider(ImageProvider):
    """Agnes AI 图像生成 Provider。

    调用 Agnes APIHub 的 OpenAI 兼容图像生成接口，
    失败时自动降级为 MockImageProvider（占位图），保证流程可演示。

    Attributes:
        _api_base: Agnes APIHub 基础地址（如 https://apihub.agnes-ai.com/v1）。
        _api_key: 图像生成 API Key。
        _model: 图像生成模型名（如 agnes-image-2.5-flash）。
        _mock: 内部持有的 Mock Provider，用于降级。
        last_degraded: 最近一次 generate 是否发生了降级（仅供调用方诊断参考）。
    """

    # 单次图像生成请求超时（秒），图像生成耗时较长，按任务要求设为 120s
    REQUEST_TIMEOUT = 120.0

    def __init__(self) -> None:
        """初始化 Agnes 图像 Provider，从全局配置读取凭证。

        Returns:
            None
        """
        self._api_base = (settings.AGNES_BASE_URL or "").rstrip("/")
        self._api_key = settings.AGNES_IMAGE_API_KEY or ""
        self._model = settings.AGNES_IMAGE_MODEL or "agnes-image-2.5-flash"
        self._mock = MockImageProvider()
        self.last_degraded: bool = False

    async def generate(
        self,
        prompt: str,
        ref_images: list[str] | None = None,
        params: dict | None = None,
    ) -> str:
        """根据提示词生成图像并返回图像 URL（失败自动降级 mock）。

        Args:
            prompt: 图像生成提示词。
            ref_images: 参考图 URL 列表（当前网关 t2i 端点不支持图生图，
                提供时仅记录警告并忽略，不影响文生图）。
            params: 额外参数，支持 width/height（拼接为 size，默认 1024x1024）、n。

        Returns:
            str: 生成图像的访问 URL（真实 URL 或降级后的 mock 占位图 URL）。

        Raises:
            RuntimeError: 仅当降级 mock 也失败时向外抛出，交由上层任务重试。
        """
        # 未配置 API Key 时直接走 mock，避免无效网络请求
        if not self._api_base or not self._api_key:
            logger.warning("[agnes-image] 未配置 AGNES_BASE_URL/AGNES_IMAGE_API_KEY，降级 mock。")
            self.last_degraded = True
            return await self._mock.generate(prompt, ref_images, params)

        try:
            # 关键逻辑：委托真实 API 调用，成功路径返回原始产物 URL
            return await self._generate_via_api(prompt, ref_images, params)
        except Exception as exc:  # noqa: BLE001
            # 降级约定：记录 error 日志后调用 mock 完成本次请求。
            # 注意：base 接口约定返回 str URL（现有调用方按字符串使用），
            # 因此降级结果无法内嵌 dict 标记，仅能通过日志与 last_degraded 属性标识。
            logger.error(f"[agnes-image] 真实生成失败，降级 mock: {exc}")
            self.last_degraded = True
            return await self._mock.generate(prompt, ref_images, params)

    async def _generate_via_api(
        self,
        prompt: str,
        ref_images: list[str] | None,
        params: dict | None,
    ) -> str:
        """调用 Agnes APIHub /images/generations 完成真实生成。

        Args:
            prompt: 图像生成提示词。
            ref_images: 参考图列表（非空时记录警告并忽略）。
            params: 额外参数（width/height/n）。

        Returns:
            str: 生成图像的访问 URL；b64 返回时为落盘后的 /static/... URL。

        Raises:
            RuntimeError: 非 200 响应或响应结构无法解析时抛出。
            httpx.HTTPError: 网络层异常（超时、连接失败等）向上透传。
        """
        if ref_images:
            logger.warning("[agnes-image] 当前 t2i 端点不支持参考图，已忽略 ref_images。")

        # 组装 OpenAI images API 风格请求体
        p = params or {}
        width = p.get("width", 1024)
        height = p.get("height", 1024)
        body: dict = {
            "model": self._model,
            "prompt": prompt,
            "n": int(p.get("n", 1)),
            "size": p.get("size", f"{width}x{height}"),
        }

        # 发起真实请求（超时 120s）
        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{self._api_base}/images/generations",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )

        # 非 200 视为失败，抛出后由 generate 统一降级
        if resp.status_code != 200:
            raise RuntimeError(
                f"Agnes 图像 API 返回 {resp.status_code}: {resp.text[:300]}"
            )

        # 解析响应：data[0].url 优先；b64_json 非空则解码落盘
        data = resp.json().get("data") or []
        if not data:
            raise RuntimeError(f"Agnes 图像 API 响应缺少 data 字段: {resp.text[:300]}")

        item = data[0] or {}
        url = (item.get("url") or "").strip()
        if url:
            return url

        b64 = (item.get("b64_json") or "").strip()
        if b64:
            # 关键逻辑：b64 解码后保存到静态目录，返回 /static/... URL（与 mock 的 URL 落库格式一致）
            image_bytes = base64.b64decode(b64)
            return save_artifact(image_bytes, "images", "png")

        raise RuntimeError(f"Agnes 图像 API 响应中无 url/b64_json: {resp.text[:300]}")
