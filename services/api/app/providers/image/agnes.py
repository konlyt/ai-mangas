"""
Agnes AI 图像生成 Provider。

通过 Agnes AI APIHub（OpenAI 兼容网关）的 /images/generations 端点
真实生成图像。实测响应结构（2026-10-08）：

    {"data": [{"url": "https://...png", "b64_json": "", "revised_prompt": ""}],
     "created": 1791427346, "task_id": "task_xxx"}

即优先返回产物 URL；若后续返回 b64_json 则解码落盘到静态目录。

参考图（i2i，方案 A2，2026-10 实测结论）：
    - /v1/images/edits（multipart）→ 503 "no available server"（端点存在无上游）；
    - /v1/images/generations + JSON "image": "<base64>" → 网关识别该字段并
      分流到独立 i2i 队列（当前 503 "image queue is full"，队列暂无产能）；
    - /v1/images/generations + "ref_images" → 400 显式拒绝（不可用）。
    因此本 Provider 在 ref_images 非空时以 "image" 字段（base64）尝试 i2i；
    i2i 失败（400/503/超时等）时降级为纯 t2i 继续出图（t2i 队列独立可用，
    并非 mock）；仅当纯 t2i 也失败才降级 mock 占位图。
    i2i 队列恢复后无需改动代码，i2i 分支自动生效。

任何网络/HTTP 异常均记录日志后按上述链路降级，
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
    """Agnes AI 图像生成 Provider（t2i + i2i 尝试 + 双级降级）。

    调用链（ref_images 非空时）：
        i2i（"image" 字段 base64）→ 失败降级纯 t2i（last_ref_dropped=True）
        → 失败降级 mock（last_degraded=True）。
    ref_images 为空时与旧版完全一致：t2i → mock，行为零变化。

    Attributes:
        _api_base: Agnes APIHub 基础地址（如 https://apihub.agnes-ai.com/v1）。
        _api_key: 图像生成 API Key。
        _model: 图像生成模型名（如 agnes-image-2.5-flash）。
        _mock: 内部持有的 Mock Provider，用于最终降级。
        last_degraded: 最近一次 generate 是否发生了 mock 降级（仅供调用方诊断参考）。
        last_ref_dropped: 最近一次 generate 传入的参考图是否最终未被消费
            （i2i 尝试失败降级 t2i / 参考图数据不可用 / 直接 mock 降级时为 True）。
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
        self.last_ref_dropped: bool = False

    async def generate(
        self,
        prompt: str,
        ref_images: list[dict] | None = None,
        params: dict | None = None,
    ) -> str:
        """根据提示词生成图像（ref_images 非空时优先 i2i，失败逐级降级）。

        Args:
            prompt: 图像生成提示词。
            ref_images: 参考图列表（方案 A2 协议：每项 {"data": bytes|str(base64),
                "mime": "image/png"|...}，兼容裸 base64/data URI 字符串形态）。
                为空（None/[]）时走与旧版一致的纯 t2i 路径，行为零变化。
                多张参考图时仅取首张可用者（实测网关仅确认 "image" 单字段可用，
                保守策略避免多图字段引发 400 导致整次 i2i 失败）。
                http(s) URL 形态无法直接用作 i2i base64，会被跳过。
            params: 额外参数，支持 width/height（拼接为 size，默认 1024x1024）、n。

        Returns:
            str: 生成图像的访问 URL（i2i 产物 URL / t2i 产物 URL / 降级后的
                mock 占位图 URL）。因接口约定返回 str，参考图是否被真实消费
                通过 last_ref_dropped 属性与日志标识，不内嵌 dict 标记。

        Raises:
            RuntimeError: 仅当降级 mock 也失败时向外抛出，交由上层任务重试。
        """
        # 未配置 API Key 时直接走 mock，避免无效网络请求
        if not self._api_base or not self._api_key:
            logger.warning("[agnes-image] 未配置 AGNES_BASE_URL/AGNES_IMAGE_API_KEY，降级 mock。")
            self.last_degraded = True
            if ref_images:
                self.last_ref_dropped = True
                logger.warning("[agnes-image] mock 不消费参考图，ref_images 已丢弃。")
            return await self._mock.generate(prompt, ref_images, params)

        # 方案 A2：ref_images 非空时优先尝试 i2i（网关识别 "image" 字段并分流到独立 i2i 队列）
        if ref_images:
            image_b64 = self._extract_first_ref_base64(ref_images)
            if image_b64:
                try:
                    # i2i 成功：参考图被真实消费，直接返回 i2i 产物 URL
                    return await self._request_image(
                        self._build_body(prompt, params, image_b64=image_b64)
                    )
                except Exception as exc:  # noqa: BLE001
                    # 关键降级约定：i2i 通道不可用（400/503/超时等）时降级纯 t2i
                    # 继续出图（t2i 队列独立可用，不是 mock）。i2i 队列恢复后
                    # 本分支不再触发，真实参考图生成自动生效。
                    self.last_ref_dropped = True
                    logger.warning(f"[agnes-image] i2i 通道不可用({exc})，降级纯 t2i 继续出图。")
            else:
                # 参考图数据不可用（无可解码的 base64/data URI），无法发起 i2i
                self.last_ref_dropped = True
                logger.warning("[agnes-image] 参考图数据不可用（无可解码的 base64/data URI），忽略 ref_images 走纯 t2i。")

        try:
            # 关键逻辑：纯 t2i 路径（与旧版行为一致），成功返回真实产物 URL
            return await self._request_image(self._build_body(prompt, params))
        except Exception as exc:  # noqa: BLE001
            # 降级约定：记录 error 日志后调用 mock 完成本次请求。
            # 注意：base 接口约定返回 str URL（现有调用方按字符串使用），
            # 因此降级结果无法内嵌 dict 标记，仅能通过日志与 last_degraded 属性标识。
            logger.error(f"[agnes-image] 真实生成失败，降级 mock: {exc}")
            self.last_degraded = True
            return await self._mock.generate(prompt, ref_images, params)

    @staticmethod
    def _extract_first_ref_base64(ref_images: list[dict | str]) -> str | None:
        """从参考图列表中提取第一张可用的裸 base64 数据。

        兼容三种输入形态：
            1. {"data": bytes, ...}：二进制内容，直接编码为 base64；
            2. {"data": str, ...}：裸 base64 或 data URI（data:image/png;base64,xxx）；
            3. 裸 str（历史 list[str] URL 协议兼容）：data URI/裸 base64 可用，
               http(s) URL 无法直接作为 i2i base64，跳过并记录警告
               （调用方应预取图像后按 {data, mime} 协议传入）。

        Args:
            ref_images: 参考图列表（dict 项按协议取 "data" 字段，str 项按
                data URI/裸 base64/URL 解析）。

        Returns:
            str | None: 第一张可用参考图的裸 base64 字符串；全部不可用时返回 None。
        """
        for idx, item in enumerate(ref_images):
            data = item.get("data") if isinstance(item, dict) else item
            if data is None:
                continue
            if isinstance(data, (bytes, bytearray)):
                encoded = base64.b64encode(bytes(data)).decode("ascii")
                # 空 bytes 编码结果为空串，视为不可用
                return encoded or None
            text = str(data).strip()
            # data URI 形态：去掉 "data:*/*;base64," 前缀
            if text.lower().startswith("data:"):
                text = text.partition(",")[2].strip()
            if not text:
                continue
            if text.lower().startswith(("http://", "https://")):
                logger.warning(
                    f"[agnes-image] 第 {idx + 1} 张参考图为 URL，无法直接用作 i2i base64"
                    "（应按方案 A2 协议传 data/mime 结构），已跳过。"
                )
                continue
            return text
        return None

    def _build_body(
        self,
        prompt: str,
        params: dict | None,
        image_b64: str | None = None,
    ) -> dict:
        """组装 OpenAI images API 风格请求体。

        Args:
            prompt: 图像生成提示词。
            params: 额外参数（width/height/n/size）。
            image_b64: 参考图裸 base64；非空时附加 "image" 字段走 i2i
                （网关识别该字段并分流到独立 i2i 队列）；为空时为纯 t2i 请求体。
                注意：不使用 "ref_images" 字段（实测网关对该字段返回 400 显式拒绝）。

        Returns:
            dict: 可直接作为 JSON body 的请求体。
        """
        p = params or {}
        width = p.get("width", 1024)
        height = p.get("height", 1024)
        body: dict = {
            "model": self._model,
            "prompt": prompt,
            "n": int(p.get("n", 1)),
            "size": p.get("size", f"{width}x{height}"),
        }
        if image_b64:
            body["image"] = image_b64
        return body

    async def _request_image(self, body: dict) -> str:
        """调用 Agnes APIHub /images/generations 完成真实生成并解析产物。

        Args:
            body: OpenAI images API 风格请求体（纯 t2i 或带 "image" 字段的 i2i）。

        Returns:
            str: 生成图像的访问 URL；b64 返回时为落盘后的 /static/... URL。

        Raises:
            RuntimeError: 非 200 响应或响应结构无法解析时抛出（含状态码与响应摘要）。
            httpx.HTTPError: 网络层异常（超时、连接失败等）向上透传。
        """
        # 发起真实请求（超时 120s）
        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{self._api_base}/images/generations",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )

        # 非 200 视为失败，抛出后由 generate 按降级链处理（i2i→t2i→mock）
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
