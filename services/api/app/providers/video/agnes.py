"""
Agnes AI 视频生成 Provider。

对接 Agnes AI 视频服务的异步任务 API（与文本/图像同为 apihub.agnes-ai.com，
视频 Key 仅在该域名有效，api.agnes-ai.cn 对其返回 401）：

1. 创建任务：POST {AGNES_VIDEO_BASE_URL}/videos
   - mode 必须为 "text"（文生视频）/ "keyframe"（首帧图生视频）/ "reference"（参考图生视频）；
   - seconds 必须为字符串（"4"–"12"）；aspect_ratio 如 "16:9"。
   创建响应含 id / task_id / video_id，其中 video_id 用于查询进度。

2. 查询任务：GET {域名根}/agnesapi?video_id=<VIDEO_ID>&model_name=<MODEL>
   （实测 2026-10-08：/agnesapi 与创建端点同域，位于域名根路径、不在 /v1 之下，
   需带 Bearer 鉴权；用假 video_id 请求返回 404 "task not found" 即端点存在且鉴权通过）
   完成响应示例：
   {"id": "task_xxx", "status": "completed", "url": "https://...mp4",
    "progress": 100, "seconds": "4", "size": "720P", "object": "video", ...}

降级策略：未配置凭证或发生不可恢复错误（4xx）时降级 Mock；
429/5xx（含队列满）/网络超时为可重试错误，抛 AgnesVideoRetryableError
透传给任务队列指数退避重试，重试耗尽后由任务层 mock 兜底。
"""

import uuid

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.video.base import VideoProvider
from app.providers.video.mock import MockVideoProvider

logger = get_logger()


class AgnesVideoRetryableError(RuntimeError):
    """Agnes 视频可重试错误。

    用于标识 429/5xx/队列满/网络超时等临时性错误：
    该类异常不会被 Provider 内部降级逻辑捕获，而是透传给上层任务队列，
    由 ARQ 指数退避重试，重试耗尽后再由任务层 mock 兜底。
    """


class AgnesVideoProvider(VideoProvider):
    """Agnes AI 视频生成 Provider。

    实现两阶段流程：submit 创建异步任务返回 video_id，
    poll 单次查询任务状态（外部调用方循环轮询直到 completed/failed，
    建议整体超时 10 分钟）。失败时自动降级为 MockVideoProvider。

    Attributes:
        _api_base: Agnes APIHub 基础地址（含 /v1）。
        _domain_root: 域名根地址（/agnesapi 查询端点所在）。
        _api_key: 视频生成 API Key。
        _model: 视频生成模型名（如 agnes-video-2.5-flash）。
        _mock: 内部持有的 Mock Provider，用于降级。
        _degraded_tasks: 已降级的 mock 任务 ID 集合，poll 时据此直接返回 mock 结果。
        last_degraded: 最近一次 submit/poll 是否发生了降级（仅供诊断参考）。
    """

    # 创建任务请求超时（秒）
    REQUEST_TIMEOUT = 120.0
    # 建议的轮询间隔（秒），官方文档建议 1–2s；免费档限流较严，取 3s 折中
    POLL_INTERVAL = 3.0
    # 整体轮询超时（秒）：10 分钟，供外部循环参考与验证脚本使用
    POLL_TIMEOUT = 600.0

    # 降级返回 dict 中的固定标记
    DEGRADED_PROVIDER_TAG = "mock(降级)"

    def __init__(self) -> None:
        """初始化 Agnes 视频 Provider，从全局配置读取凭证。

        Returns:
            None
        """
        # 视频服务独立域名（api.agnes-ai.cn），未配置时回退通用 AGNES_BASE_URL
        base = (settings.AGNES_VIDEO_BASE_URL or settings.AGNES_BASE_URL or "").rstrip("/")
        self._api_base = base
        # /agnesapi 查询端点位于域名根路径：去掉末尾的 /v1 得到域名根
        self._domain_root = base[: -len("/v1")] if base.endswith("/v1") else base
        self._api_key = settings.AGNES_VIDEO_API_KEY or ""
        self._model = settings.AGNES_VIDEO_MODEL or "agnes-video-2.5-flash"
        self._mock = MockVideoProvider()
        self._degraded_tasks: set[str] = set()
        self.last_degraded: bool = False

    async def submit(
        self,
        prompt: str,
        image_url: str,
        params: dict | None = None,
    ) -> str:
        """提交视频生成任务并返回厂商侧任务 ID（失败自动降级 mock）。

        Args:
            prompt: 视频生成提示词。
            image_url: 首帧图 URL；非空时走 keyframe 模式，为空时走 text 模式。
            params: 额外参数，支持 mode/seconds/aspect_ratio/size/seed/last_frame/images。

        Returns:
            str: 厂商侧 video_id（降级时为 mock 任务 ID）。

        Raises:
            RuntimeError: 仅当降级 mock 也失败时向外抛出，交由上层任务重试。
        """
        # 未配置 API Key 时直接走 mock
        if not self._api_base or not self._api_key:
            logger.warning("[agnes-video] 未配置 AGNES_BASE_URL/AGNES_VIDEO_API_KEY，降级 mock。")
            return await self._degrade_submit(prompt, image_url, params)

        try:
            # 关键逻辑：委托真实 API 创建任务，返回 video_id
            return await self._submit_via_api(prompt, image_url, params)
        except AgnesVideoRetryableError:
            # 可重试错误（队列满/限流/超时等）：透传给任务队列重试，不降级 mock
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[agnes-video] 真实提交失败，降级 mock: {exc}")
            return await self._degrade_submit(prompt, image_url, params)

    async def poll(self, task_id: str) -> dict:
        """查询视频生成任务的状态与结果（单次查询，外部循环轮询）。

        Args:
            task_id: submit 返回的任务 ID（video_id 或降级 mock 任务 ID）。

        Returns:
            dict: 包含 status（queued/running/done/failed）与 url（done 时）的字典；
                降级时额外附带 provider="mock(降级)" 与 degraded=True 字段。

        Raises:
            RuntimeError: 仅当降级 mock 也失败时向外抛出。
        """
        # 降级登记的 mock 任务：直接返回 mock 结果并打降级标记
        if task_id in self._degraded_tasks:
            return await self._degrade_poll(task_id)

        try:
            # 关键逻辑：委托真实 API 查询任务状态
            return await self._poll_via_api(task_id)
        except AgnesVideoRetryableError:
            # 可重试错误：透传给上层任务循环重试，避免把真实任务误判为 mock 结果
            raise
        except Exception as exc:  # noqa: BLE001
            # 降级约定：查询失败时返回 mock 结果（带降级标记），避免上层流程中断
            logger.error(f"[agnes-video] 真实查询失败 task_id={task_id}，降级 mock: {exc}")
            return await self._degrade_poll(task_id)

    async def _submit_via_api(
        self,
        prompt: str,
        image_url: str,
        params: dict | None,
    ) -> str:
        """调用 Agnes APIHub POST /videos 创建视频生成任务。

        Args:
            prompt: 视频生成提示词。
            image_url: 首帧图 URL（决定 text/keyframe 模式）。
            params: 额外参数（mode/seconds/aspect_ratio/size/seed/last_frame/images）。

        Returns:
            str: 厂商侧 video_id。

        Raises:
            RuntimeError: 非 200 响应或响应缺少任务标识时抛出。
            httpx.HTTPError: 网络层异常向上透传。
        """
        p = params or {}

        # 关键逻辑：按是否有首帧图选择生成模式（keyframe=图生视频，text=文生视频）
        mode = p.get("mode") or ("keyframe" if image_url else "text")
        # 核心参数以官方文档为准：model/prompt/mode/seconds/aspect_ratio
        body: dict = {
            "model": self._model,
            "prompt": prompt,
            "mode": mode,
            # 官方要求 seconds 为字符串（"4"–"12"，默认 "5"）
            "seconds": str(p.get("seconds", "5")),
            "aspect_ratio": p.get("aspect_ratio", "16:9"),
        }
        # 可选参数仅在显式提供时附加，避免未知参数被严格校验拒绝
        if p.get("size"):
            body["size"] = p["size"]
        if "seed" in p:
            body["seed"] = int(p["seed"])

        # 按模式附加媒体字段（互斥，遵循官方 Generation Mode Rules）
        if mode == "keyframe":
            if image_url:
                body["first_frame"] = image_url
            if p.get("last_frame"):
                body["last_frame"] = p["last_frame"]
        elif mode == "reference":
            images = p.get("images") or ([image_url] if image_url else [])
            if images:
                body["images"] = images[:5]  # flash 最多 5 张参考图
            if p.get("audios"):
                body["audios"] = p["audios"][:3]  # flash 最多 3 条参考音频

        # 创建任务（网络超时/连接错误按可重试处理，交由任务队列退避重试）
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._api_base}/videos",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise AgnesVideoRetryableError(f"Agnes 视频 API 请求超时: {exc}")
        except httpx.HTTPError as exc:
            raise AgnesVideoRetryableError(f"Agnes 视频 API 网络错误: {exc}")

        if resp.status_code != 200:
            # 429/5xx（含 503 队列满 video_queue_full）为临时性错误，标记可重试
            if resp.status_code == 429 or resp.status_code >= 500:
                raise AgnesVideoRetryableError(
                    f"Agnes 视频 API 返回 {resp.status_code}: {resp.text[:300]}"
                )
            raise RuntimeError(f"Agnes 视频 API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        # 官方约定：video_id 用于查询；id/task_id 仅标识异步任务
        video_id = str(data.get("video_id") or data.get("id") or data.get("task_id") or "").strip()
        if not video_id:
            raise RuntimeError(f"Agnes 视频 API 响应缺少 video_id: {str(data)[:300]}")

        logger.info(f"[agnes-video] 任务已创建 video_id={video_id}, mode={mode}")
        return video_id

    async def _poll_via_api(self, task_id: str) -> dict:
        """调用 GET /agnesapi 查询视频任务状态（单次）。

        Args:
            task_id: 创建任务时返回的 video_id。

        Returns:
            dict: {"status": queued/running/done/failed, "url": ..., ...}；
                done 时 url 为视频地址；failed 时附带 error 字段。

        Raises:
            RuntimeError: 非 200 响应时抛出。
            httpx.HTTPError: 网络层异常向上透传。
        """
        # 注意：/agnesapi 在域名根路径而非 /v1 下，必须携带 model_name
        # （网络超时/连接错误/5xx 按可重试处理，透传给上层任务循环）
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._domain_root}/agnesapi",
                    params={"video_id": task_id, "model_name": self._model},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise AgnesVideoRetryableError(f"Agnes 视频查询超时: {exc}")
        except httpx.HTTPError as exc:
            raise AgnesVideoRetryableError(f"Agnes 视频查询网络错误: {exc}")

        if resp.status_code != 200:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise AgnesVideoRetryableError(
                    f"Agnes 视频查询 API 返回 {resp.status_code}: {resp.text[:300]}"
                )
            raise RuntimeError(f"Agnes 视频查询 API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        raw_status = str(data.get("status") or data.get("state") or "").lower()

        # 关键逻辑：厂商状态 → 平台统一状态（queued/running/done/failed）映射
        if raw_status in ("completed", "succeeded", "done", "success"):
            result = {"status": "done", "url": data.get("url") or ""}
            if data.get("progress") is not None:
                result["progress"] = data.get("progress")
            return result
        if raw_status in ("failed", "error", "cancelled", "canceled"):
            return {"status": "failed", "url": "", "error": str(data.get("error") or raw_status)}
        if raw_status in ("queued", "pending", "submitted", "waiting"):
            return {"status": "queued", "url": ""}
        # 其余（running/processing 等）与未知状态一律视为进行中
        return {"status": "running", "url": ""}

    async def _degrade_submit(self, prompt: str, image_url: str, params: dict | None) -> str:
        """降级提交：调用 mock 完成提交并登记任务 ID。

        Args:
            prompt: 视频提示词。
            image_url: 首帧图 URL（mock 忽略）。
            params: 额外参数（mock 忽略）。

        Returns:
            str: mock 任务 ID。

        Raises:
            RuntimeError: mock 提交也失败时抛出。
        """
        self.last_degraded = True
        task_id = await self._mock.submit(prompt, image_url, params)
        # 登记降级任务，poll 时据此返回带标记的 mock 结果
        self._degraded_tasks.add(task_id)
        return task_id

    async def _degrade_poll(self, task_id: str) -> dict:
        """降级查询：调用 mock 完成查询并附加降级标记字段。

        Args:
            task_id: mock 任务 ID。

        Returns:
            dict: mock 查询结果，附加 provider="mock(降级)" 与 degraded=True。

        Raises:
            RuntimeError: mock 查询也失败时抛出。
        """
        self.last_degraded = True
        result = await self._mock.poll(task_id)
        # base 接口本就返回 dict，附加字段不影响既有 status/url 读取方
        result["provider"] = self.DEGRADED_PROVIDER_TAG
        result["degraded"] = True
        result["task_id"] = task_id or f"agnes-degraded-{uuid.uuid4().hex[:8]}"
        return result
