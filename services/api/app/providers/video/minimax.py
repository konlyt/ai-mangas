"""
MiniMax H3 视频生成 Provider（通过 Metaso 中转 API）。

对接 Metaso 平台的 MiniMax 视频生成异步 API：
1. 创建任务：POST {MINIMAX_VIDEO_BASE_URL}/video_generation
2. 查询结果：GET {MINIMAX_VIDEO_BASE_URL}/query/video_generation?task_id=xxx

支持图生视频（i2va），模型默认 MiniMax-H3。
"""

import base64
import os
import uuid

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.video.base import VideoProvider, VideoRetryableError
from app.providers.video.mock import MockVideoProvider

logger = get_logger()


class MinimaxVideoRetryableError(VideoRetryableError):
    """MiniMax 视频可重试错误（限流/超时/5xx）。"""


class MinimaxVideoProvider(VideoProvider):
    """MiniMax H3 视频生成 Provider（Metaso 中转）。

    实现两阶段异步流程：submit 创建任务返回 task_id，
    poll 单次查询任务状态与结果。失败时自动降级为 MockVideoProvider。

    Attributes:
        _api_base: Metaso MiniMax API 基础地址。
        _api_key: Metaso API Key（Bearer 认证）。
        _model: 视频生成模型名（默认 MiniMax-H3）。
        _mock: 内部持有的 Mock Provider，用于降级。
        _degraded_tasks: 已降级的 mock 任务 ID 集合。
        last_degraded: 最近一次是否发生了降级。
    """

    REQUEST_TIMEOUT = 120.0
    POLL_INTERVAL = 5.0
    POLL_TIMEOUT = 600.0

    DEGRADED_PROVIDER_TAG = "mock(降级)"

    def __init__(self) -> None:
        """初始化 MiniMax 视频 Provider，从全局配置读取凭证。"""
        self._api_base = (settings.MINIMAX_VIDEO_BASE_URL or "https://metaso.cn/api/minimax/v2").rstrip("/")
        self._api_key = settings.MINIMAX_VIDEO_API_KEY or ""
        self._model = settings.MINIMAX_VIDEO_MODEL or "MiniMax-H3"
        self._proxy = (settings.HTTPS_PROXY or settings.HTTP_PROXY or "").strip() or None
        self._mock = MockVideoProvider()
        self._degraded_tasks: set[str] = set()
        self.last_degraded: bool = False

    async def submit(
        self,
        prompt: str,
        image_url: str,
        params: dict | None = None,
    ) -> str:
        """提交视频生成任务并返回厂商侧任务 ID。

        Args:
            prompt: 视频生成提示词。
            image_url: 首帧图 URL；非空时走图生视频（i2va）。
            params: 额外参数，支持 resolution/duration/ratio/fast_mode。

        Returns:
            str: 厂商侧 task_id（降级时为 mock 任务 ID）。
        """
        if not self._api_key:
            logger.warning("[minimax-video] 未配置 MINIMAX_VIDEO_API_KEY，降级 mock。")
            return await self._degrade_submit(prompt, image_url, params)

        try:
            return await self._submit_via_api(prompt, image_url, params)
        except MinimaxVideoRetryableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[minimax-video] 真实提交失败，降级 mock: {exc}")
            return await self._degrade_submit(prompt, image_url, params)

    async def poll(self, task_id: str) -> dict:
        """查询视频生成任务的状态与结果（单次查询）。

        Args:
            task_id: submit 返回的任务 ID。

        Returns:
            dict: 包含 status（queued/running/done/failed）与 url 的字典。
        """
        if task_id in self._degraded_tasks:
            return await self._degrade_poll(task_id)

        try:
            return await self._poll_via_api(task_id)
        except MinimaxVideoRetryableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[minimax-video] 真实查询失败 task_id={task_id}，降级 mock: {exc}")
            return await self._degrade_poll(task_id)

    async def _submit_via_api(
        self,
        prompt: str,
        image_url: str,
        params: dict | None,
    ) -> str:
        """调用 MiniMax API 创建视频生成任务。

        Args:
            prompt: 视频生成提示词。
            image_url: 首帧图 URL（图生视频）。
            params: 额外参数（resolution/duration/ratio/fast_mode）。

        Returns:
            str: 厂商侧 task_id。

        Raises:
            RuntimeError: 非 200 响应或响应缺少任务标识时抛出。
            MinimaxVideoRetryableError: 限流/超时/5xx 时抛出。
        """
        p = params or {}

        # 构建 content 数组：文本 + 首帧图
        content = []
        if prompt:
            content.append({"type": "text", "text": prompt})
        if image_url:
            # 如果是本地相对路径（/static/...），转成 base64 data URI
            # 因为 MiniMax 外部 API 无法访问我们本地的图片
            if image_url.startswith("/static/"):
                # 静态文件根目录：services/api/static/
                static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "static")
                file_path = os.path.join(static_dir, image_url[len("/static/"):])
                try:
                    with open(file_path, "rb") as f:
                        img_data = base64.b64encode(f.read()).decode("utf-8")
                    # 判断图片格式
                    ext = os.path.splitext(file_path)[1].lower()
                    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"
                    image_url = f"data:{mime};base64,{img_data}"
                    logger.info(f"[minimax-video] 本地图片已转 base64: {file_path}")
                except Exception as e:
                    logger.error(f"[minimax-video] 读取本地图片失败: {file_path}, error: {e}")
                    # 读取失败就降级到 mock
                    raise RuntimeError(f"读取首帧图失败: {e}")

            content.append({
                "type": "image_url",
                "image_url": {"url": image_url},
                "role": "first_frame",
            })

        body: dict = {
            "model": self._model,
            "content": content,
            "resolution": p.get("resolution", "480p"),
            "duration": int(p.get("duration", 5)),
            "ratio": p.get("ratio", "adaptive"),
            "fast_mode": bool(p.get("fast_mode", False)),
        }

        logger.info(f"[minimax-video] 提交参数: {body}")

        # 创建任务
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT, proxy=self._proxy) as client:
                resp = await client.post(
                    f"{self._api_base}/video_generation",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise MinimaxVideoRetryableError(f"MiniMax 视频 API 请求超时: {exc}")
        except httpx.HTTPError as exc:
            raise MinimaxVideoRetryableError(f"MiniMax 视频 API 网络错误: {exc}")

        if resp.status_code != 200:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise MinimaxVideoRetryableError(
                    f"MiniMax 视频 API 返回 {resp.status_code}: {resp.text[:300]}"
                )
            raise RuntimeError(f"MiniMax 视频 API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        # MiniMax 返回格式：通常 task_id 在 data 或顶层
        task_id = str(data.get("task_id") or data.get("data", {}).get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"MiniMax 视频 API 响应缺少 task_id: {str(data)[:300]}")

        logger.info(f"[minimax-video] 任务已创建 task_id={task_id}, image_url={'yes' if image_url else 'no'}")
        return task_id

    async def _poll_via_api(self, task_id: str) -> dict:
        """调用 MiniMax API 查询视频任务状态（单次）。

        Args:
            task_id: 创建任务时返回的 task_id。

        Returns:
            dict: {"status": queued/running/done/failed, "url": ..., ...}

        Raises:
            MinimaxVideoRetryableError: 限流/超时/5xx 时抛出。
        """
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT, proxy=self._proxy) as client:
                resp = await client.get(
                    f"{self._api_base}/query/video_generation",
                    params={"task_id": task_id},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise MinimaxVideoRetryableError(f"MiniMax 视频查询超时: {exc}")
        except httpx.HTTPError as exc:
            raise MinimaxVideoRetryableError(f"MiniMax 视频查询网络错误: {exc}")

        if resp.status_code != 200:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise MinimaxVideoRetryableError(
                    f"MiniMax 视频查询 API 返回 {resp.status_code}: {resp.text[:300]}"
                )
            raise RuntimeError(f"MiniMax 视频查询 API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        logger.info(f"[minimax-video] 查询返回 task_id={task_id}: {str(data)[:500]}")
        # MiniMax 返回格式：items 数组。必须按 task_id 精确匹配，
        # 否则中转网关可能返回最新任务列表，导致所有任务拿到同一个视频。
        items = data.get("items", [])
        if not items:
            return {"status": "running", "url": ""}
        inner = None
        for it in items:
            tid = str(it.get("task_id") or it.get("id") or "")
            if tid == task_id:
                inner = it
                break
        if inner is None:
            # 没匹配到 task_id，兜底用 items[0] 但记日志
            inner = items[0]
            logger.warning(f"[minimax-video] items 中未找到 task_id={task_id}，兜底用 items[0]")
        raw_status = str(inner.get("status") or inner.get("state") or "").lower()

        # 状态映射
        if raw_status in ("succeeded", "success", "completed", "done", "finished"):
            video_url = inner.get("content", {}).get("url") or inner.get("file_url") or inner.get("video_url") or ""
            result = {"status": "done", "url": video_url}
            if inner.get("progress") is not None:
                result["progress"] = inner.get("progress")
            return result
        if raw_status in ("fail", "failed", "error", "cancelled", "canceled"):
            return {"status": "failed", "url": "", "error": str(inner.get("error") or raw_status)}
        if raw_status in ("queueing", "queued", "pending", "submitted", "waiting"):
            return {"status": "queued", "url": ""}
        # 其余（running/processing 等）视为进行中
        return {"status": "running", "url": ""}

    async def _degrade_submit(self, prompt: str, image_url: str, params: dict | None) -> str:
        """降级提交：调用 mock 完成提交并登记任务 ID。"""
        self.last_degraded = True
        task_id = await self._mock.submit(prompt, image_url, params)
        self._degraded_tasks.add(task_id)
        return task_id

    async def _degrade_poll(self, task_id: str) -> dict:
        """降级查询：调用 mock 完成查询并附加降级标记字段。"""
        self.last_degraded = True
        result = await self._mock.poll(task_id)
        result["provider"] = self.DEGRADED_PROVIDER_TAG
        result["degraded"] = True
        result["task_id"] = task_id or f"minimax-degraded-{uuid.uuid4().hex[:8]}"
        return result
