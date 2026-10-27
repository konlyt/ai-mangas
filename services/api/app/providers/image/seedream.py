"""
APIMart Seedream 图像生成 Provider（异步任务型，方案 A2 参考图协议完整实现）。

通过 APIMart 网关调用字节 Seedream 5.0 Flash（模型名 seedream-5-0-flash），
接口形态与 OpenAI 风格网关不同——为「提交任务 + 轮询」两阶段（与智谱视频
Provider 同模式），2026-10-19 真实 Key 实测确认：

    1. POST /v1/images/generations（JSON）
       → 200 {"code": 200, "data": [{"status": "submitted", "task_id": "task_xxx"}]}
    2. GET /v1/tasks/{task_id}
       → 200 {"code": 200, "data": {"status": "completed", "progress": 100,
            "cost": 0.0137, "result": {"images": [{"url": ["https://..."]}]}}}

实测要点（与官方文档有出入，以实测为准）：
    - 轮询返回体为 {"code": 200, "data": {...}} 包裹结构；
    - 任务终态为 "completed"（文档写 "success"，两种均兼容）；
    - result.images[0].url 为数组（取首项）；产物 URL 72 小时过期，
      因此本 Provider 下载图片并落盘静态目录（save_artifact），
      返回永久的 /static/... 相对 URL——72h 过期风险由落盘根治；
    - image_urls 支持公共 URL 或 data:image/<fmt>;base64,<data>，
      最多 10 张——本 Provider 将 ref_images 协议（{data, mime}）全部
      转为 data URI 注入，原生多参考图（无 Agnes 单图限制）；
    - n 仅支持 1（n>1 返回 400 且不计费），分辨率档位 1K/1.5K/2K。

降级约定（与 base.py 一致）：
    1. ref_images 非空 → 携带 image_urls 真实 i2i（参考图被真实消费）；
    2. i2i 失败（提交/轮询/下载任一环节异常）→ 降级纯 t2i 重试一次
       （last_ref_dropped=True）；
    3. 纯 t2i 也失败 → 降级 mock 占位图（last_degraded=True）。
    未配置 API Key 时直接降级 mock，避免无效网络请求。
"""

import asyncio
import base64

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.image.base import ImageProvider
from app.providers.image.mock import MockImageProvider
from app.providers.storage import save_artifact

logger = get_logger()

# 参考图数量上限（APIMart Seedream 实测约束，超出返回 400）
MAX_REF_IMAGES = 10

# 轮询间隔（秒，模块级常量便于测试加速替换）
POLL_INTERVAL = 8.0


class SeedreamImageProvider(ImageProvider):
    """APIMart Seedream 5.0 Flash 图像 Provider（提交+轮询，多参考图原生支持）。

    调用链（ref_images 非空时）：
        i2i（image_urls 多参考）→ 失败降级纯 t2i（last_ref_dropped=True）
        → 失败降级 mock（last_degraded=True）。
    ref_images 为空时直接 t2i → mock，行为与 Agnes Provider 降级语义一致。

    Attributes:
        _api_base: APIMart API 基础地址（默认 https://api.apimart.ai/v1）。
        _api_key: APIMart API Key。
        _model: 模型名（默认 seedream-5-0-flash）。
        _mock: 内部持有的 Mock Provider，用于最终降级。
        last_degraded: 最近一次 generate 是否发生了 mock 降级。
        last_ref_dropped: 最近一次 generate 传入的参考图是否最终未被消费。
    """

    # 提交请求超时（秒）
    SUBMIT_TIMEOUT = 60.0
    # 轮询单次请求超时（秒）
    POLL_TIMEOUT = 30.0
    # 产物下载超时（秒）
    DOWNLOAD_TIMEOUT = 120.0
    # 轮询总时长上限（秒）：实测 1.5K 约 20-90s，预留足够缓冲
    POLL_MAX_WAIT = 420.0

    def __init__(self) -> None:
        """初始化 Seedream Provider，从全局配置读取凭证。

        Returns:
            None
        """
        self._api_base = (settings.APIMART_BASE_URL or "https://api.apimart.ai/v1").rstrip("/")
        self._api_key = settings.APIMART_API_KEY or ""
        self._model = settings.SEEDREAM_IMAGE_MODEL or "seedream-5-0-flash"
        # 网络代理（海外 API 需要走代理）
        self._proxy = (settings.HTTPS_PROXY or settings.HTTP_PROXY or "").strip() or None
        self._mock = MockImageProvider()
        self.last_degraded: bool = False
        self.last_ref_dropped: bool = False

    async def generate(
        self,
        prompt: str,
        ref_images: list[dict] | None = None,
        params: dict | None = None,
    ) -> str:
        """根据提示词生成图像（ref_images 全量注入 image_urls，失败逐级降级）。

        Args:
            prompt: 图像生成提示词（含 {{ref N}} 协议段时与 image_urls 顺序对应）。
            ref_images: 参考图列表（方案 A2 协议：每项 {"data": bytes|str(base64),
                "mime": "image/png"|...}，兼容裸 base64/data URI 字符串形态）。
                最多取前 MAX_REF_IMAGES 张，全部转为 data URI 注入 image_urls。
                为空（None/[]）时走纯 t2i 路径。
            params: 额外参数，支持 size（如 "16:9" 或 "2048x1152"）、
                ratio（16:9 等比例，size 未指定时使用）、resolution
                （1K/1.5K/2K，默认 1.5K）、width/height（拼接精确像素 size）。
                注意 Seedream 仅支持 n=1，n>1 会被忽略并告警。

        Returns:
            str: 生成图像的永久访问 URL（产物已落盘为 /static/... 相对路径）。
                参考图是否被真实消费通过 last_ref_dropped 属性与日志标识。

        Raises:
            RuntimeError: 仅当降级 mock 也失败时向外抛出，交由上层任务重试。
        """
        # 未配置 API Key 时直接走 mock，避免无效网络请求
        if not self._api_key:
            logger.warning("[seedream] 未配置 APIMART_API_KEY，降级 mock。")
            self.last_degraded = True
            if ref_images:
                self.last_ref_dropped = True
                logger.warning("[seedream] mock 不消费参考图，ref_images 已丢弃。")
            return await self._mock.generate(prompt, ref_images, params)

        ref_uris: list[str] = []
        if ref_images:
            ref_uris = self._build_image_urls(ref_images)
            if not ref_uris:
                # 参考图数据全部不可用（无可解码的 base64/data URI）
                self.last_ref_dropped = True
                logger.warning("[seedream] 参考图数据不可用（无可解码的 base64/data URI），忽略 ref_images 走纯 t2i。")

        # 第 1 次：ref_images 非空且可用时为 i2i（多参考图），否则为纯 t2i
        first_body = self._build_body(prompt, params, image_urls=ref_uris or None)
        try:
            return await self._request_task(first_body)
        except Exception as exc:  # noqa: BLE001
            if ref_uris:
                # 关键降级约定：i2i 通道不可用时降级纯 t2i 重试（不是 mock）
                self.last_ref_dropped = True
                logger.warning(f"[seedream] i2i 通道不可用({exc})，降级纯 t2i 重试。")
                try:
                    return await self._request_task(self._build_body(prompt, params))
                except Exception as exc2:  # noqa: BLE001
                    logger.error(f"[seedream] 纯 t2i 也失败，降级 mock: {exc2}")
                    self.last_degraded = True
                    return await self._mock.generate(prompt, ref_images, params)
            logger.error(f"[seedream] 真实生成失败，降级 mock: {exc}")
            self.last_degraded = True
            return await self._mock.generate(prompt, ref_images, params)

    def _build_image_urls(self, ref_images: list[dict | str]) -> list[str]:
        """将 ref_images 协议列表转换为 APIMart image_urls（data URI）数组。

        兼容三种输入形态（与 Agnes._extract_first_ref_base64 的解析规则一致，
        区别在于本 Provider 支持多张全量注入）：
            1. {"data": bytes, ...}：二进制内容，按 mime 编码为 data URI；
            2. {"data": str, ...}：裸 base64（按 mime 补前缀）或 data URI（透传）；
            3. 裸 str：data URI / 裸 base64 可用；http(s) URL 亦可直接透传
               （APIMart 原生支持公共 URL 参考图）。

        Args:
            ref_images: 参考图列表。

        Returns:
            list[str]: 可用的 image_urls 数组（最多 MAX_REF_IMAGES 张）。
        """
        urls: list[str] = []
        for idx, item in enumerate(ref_images):
            if len(urls) >= MAX_REF_IMAGES:
                logger.warning(
                    f"[seedream] 参考图超过 {MAX_REF_IMAGES} 张上限，第 {idx + 1} 张起已截断。"
                )
                break
            data = item.get("data") if isinstance(item, dict) else item
            mime = (item.get("mime", "image/png") if isinstance(item, dict) else "image/png") or "image/png"
            if data is None:
                continue
            if isinstance(data, (bytes, bytearray)):
                b64 = base64.b64encode(bytes(data)).decode("ascii")
                if b64:
                    urls.append(f"data:{mime};base64,{b64}")
                continue
            text = str(data).strip()
            if not text:
                continue
            if text.lower().startswith("data:"):
                # data URI 形态直接透传
                urls.append(text)
            elif text.lower().startswith(("http://", "https://")):
                # APIMart 原生支持公共 URL 参考图，直接透传
                urls.append(text)
            else:
                # 裸 base64：按 mime 补全 data URI 前缀
                urls.append(f"data:{mime};base64,{text}")
        return urls

    def _build_body(
        self,
        prompt: str,
        params: dict | None,
        image_urls: list[str] | None = None,
    ) -> dict:
        """组装 APIMart Seedream 请求体。

        Args:
            prompt: 图像生成提示词。
            params: 额外参数（size/ratio/resolution/width/height）。
            image_urls: 参考图 data URI/URL 数组；非空时走 i2i（多参考图）。

        Returns:
            dict: 可直接作为 JSON body 的请求体。
        """
        p = params or {}
        size = p.get("size")
        if not size and p.get("ratio"):
            size = str(p["ratio"])
        if not size and (p.get("width") and p.get("height")):
            size = f"{int(p['width'])}x{int(p['height'])}"
        body: dict = {"model": self._model, "prompt": prompt}
        if size:
            body["size"] = str(size)
        # 分辨率档位（1K/1.5K/2K）；size 为精确像素时网关忽略 resolution，无副作用
        body["resolution"] = str(p.get("resolution", "1.5K"))
        if image_urls:
            body["image_urls"] = image_urls
        n = int(p.get("n", 1))
        if n > 1:
            # Seedream 仅支持 n=1（n>1 返回 400 且不计费），忽略并告警
            logger.warning("[seedream] Seedream 仅支持 n=1，params.n>1 已忽略。")
        return body

    async def _request_task(self, body: dict) -> str:
        """提交生成任务 → 轮询至终态 → 下载产物落盘并返回永久 URL。

        Args:
            body: APIMart 请求体（t2i 或带 image_urls 的 i2i）。

        Returns:
            str: 生成图像的永久访问 URL（/static/... 相对路径）。

        Raises:
            RuntimeError: 提交失败、轮询超时、任务失败或产物无法解析时抛出。
            httpx.HTTPError: 网络层异常（超时、连接失败等）向上透传。
        """
        headers = {"Authorization": f"Bearer {self._api_key}"}

        # 阶段 1：提交任务
        async with httpx.AsyncClient(timeout=self.SUBMIT_TIMEOUT, proxy=self._proxy) as client:
            resp = await client.post(
                f"{self._api_base}/images/generations",
                headers=headers,
                json=body,
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Seedream 提交失败 HTTP {resp.status_code}: {resp.text[:300]}"
            )
        payload = resp.json()
        task_id = self._extract_task_id(payload)
        if not task_id:
            # 同步返回形态（非本网关实测行为，防御性兼容）：直接解析产物
            return await self._extract_sync_result(payload)
        logger.info(f"[seedream] 任务已提交 task_id={task_id}")

        # 阶段 2：轮询至终态（实测返回 {"code":200,"data":{...}} 包裹结构）
        deadline = asyncio.get_event_loop().time() + self.POLL_MAX_WAIT
        while True:
            async with httpx.AsyncClient(timeout=self.POLL_TIMEOUT, proxy=self._proxy) as client:
                pr = await client.get(f"{self._api_base}/tasks/{task_id}", headers=headers)
            if pr.status_code == 200:
                inner = pr.json()
                if isinstance(inner.get("data"), dict):
                    inner = inner["data"]
                status = str(inner.get("status") or "").lower()
                if status in ("completed", "success"):
                    urls = self._extract_result_urls(inner)
                    if not urls:
                        raise RuntimeError(
                            f"Seedream 任务成功但无产物 URL: {str(inner)[:300]}"
                        )
                    return await self._download(urls[0])
                if status in ("failed", "cancelled", "error"):
                    raise RuntimeError(f"Seedream 任务失败: {str(inner.get('error') or inner)[:300]}")
                logger.info(
                    f"[seedream] 轮询 task_id={task_id} status={status} "
                    f"progress={inner.get('progress', 0)}"
                )
            else:
                logger.warning(
                    f"[seedream] 轮询 HTTP {pr.status_code}: {pr.text[:200]}"
                )
            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(f"Seedream 轮询超时({self.POLL_MAX_WAIT:.0f}s): task_id={task_id}")
            await asyncio.sleep(POLL_INTERVAL)

    @staticmethod
    def _extract_task_id(payload: dict) -> str | None:
        """从提交响应中提取 task_id（兼容包裹/裸结构）。

        Args:
            payload: 提交响应 JSON。

        Returns:
            str | None: task_id；无法识别时返回 None。
        """
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0].get("task_id") or None
        if isinstance(data, dict):
            return data.get("task_id") or None
        return payload.get("task_id") or None

    @staticmethod
    def _extract_result_urls(inner: dict) -> list[str]:
        """从轮询终态响应中提取产物 URL 列表。

        实测结构：result.images[0].url 为字符串数组（取其全部项）。

        Args:
            inner: 轮询响应的 data 层对象（已解包）。

        Returns:
            list[str]: 产物 URL 列表（可能为空）。
        """
        result = inner.get("result") or {}
        images = result.get("images") or []
        urls: list[str] = []
        for img in images:
            raw = (img or {}).get("url")
            if isinstance(raw, list):
                urls.extend([u for u in raw if isinstance(u, str) and u.strip()])
            elif isinstance(raw, str) and raw.strip():
                urls.append(raw.strip())
        return urls

    async def _extract_sync_result(self, payload: dict) -> str:
        """防御性解析同步返回形态的产物（OpenAI 风格 data[0].url/b64_json）。

        Args:
            payload: 提交响应 JSON。

        Returns:
            str: 产物永久 URL（URL 下载落盘 / b64 解码落盘）。

        Raises:
            RuntimeError: 无法解析出产物时抛出。
        """
        items = payload.get("data") or []
        if not items:
            raise RuntimeError(f"Seedream 响应无 task_id 且无产物: {str(payload)[:300]}")
        item = items[0] or {}
        url = (item.get("url") or "").strip()
        if url:
            return await self._download(url)
        b64 = (item.get("b64_json") or "").strip()
        if b64:
            return save_artifact(base64.b64decode(b64), "images", "png")
        raise RuntimeError(f"Seedream 同步响应无 url/b64_json: {str(payload)[:300]}")

    async def _download(self, url: str) -> str:
        """下载产物图片并落盘静态目录（产物 URL 72h 过期，必须及时持久化）。

        Args:
            url: 产物临时 URL。

        Returns:
            str: 落盘后的永久 /static/... 相对访问 URL。

        Raises:
            RuntimeError: 下载失败时抛出。
        """
        async with httpx.AsyncClient(timeout=self.DOWNLOAD_TIMEOUT, proxy=self._proxy) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Seedream 产物下载失败 HTTP {resp.status_code}: {url[:200]}")
        ext = "png"
        path = str(url).lower().split("?")[0]
        for cand in ("png", "jpg", "jpeg", "webp"):
            if path.endswith(f".{cand}"):
                ext = "jpg" if cand == "jpeg" else cand
                break
        return save_artifact(resp.content, "images", ext)
