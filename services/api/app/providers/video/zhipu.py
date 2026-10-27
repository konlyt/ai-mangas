"""
智谱 CogVideoX 视频生成 Provider。

对接智谱 BigModel 异步视频生成 API：
1. 创建任务：POST https://open.bigmodel.cn/api/paas/v4/videos/generations
2. 查询结果：GET https://open.bigmodel.cn/api/paas/v4/async-result/{task_id}

支持文生视频（text-to-video），模型默认 cogvideox-3。
"""

import uuid

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.video.base import VideoProvider, VideoRetryableError
from app.providers.video.mock import MockVideoProvider

logger = get_logger()


class ZhipuVideoRetryableError(VideoRetryableError):
    """智谱视频可重试错误（限流/超时/5xx），继承跨厂商统一基类。"""


class ZhipuVideoProvider(VideoProvider):
    """智谱 CogVideoX 视频生成 Provider。

    实现两阶段异步流程：submit 创建任务返回 task_id，
    poll 单次查询任务状态与结果。失败时自动降级为 MockVideoProvider。

    Attributes:
        _api_base: 智谱 BigModel API 基础地址。
        _api_key: 智谱 API Key。
        _model: 视频生成模型名（默认 cogvideox-3）。
        _mock: 内部持有的 Mock Provider，用于降级。
        _degraded_tasks: 已降级的 mock 任务 ID 集合。
        last_degraded: 最近一次是否发生了降级。
    """

    REQUEST_TIMEOUT = 120.0
    POLL_INTERVAL = 5.0
    POLL_TIMEOUT = 600.0

    DEGRADED_PROVIDER_TAG = "mock(降级)"

    def __init__(self) -> None:
        """初始化智谱视频 Provider，从全局配置读取凭证。"""
        self._api_base = (settings.ZHIPU_VIDEO_BASE_URL or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        self._api_key = settings.ZHIPU_VIDEO_API_KEY or ""
        self._model = settings.ZHIPU_VIDEO_MODEL or "cogvideox-flash"
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
            image_url: 首帧图 URL（智谱文生视频模式下暂不支持图生，仅文生）。
            params: 额外参数，支持 quality/size/with_audio。

        Returns:
            str: 厂商侧 task_id（降级时为 mock 任务 ID）。
        """
        if not self._api_key:
            logger.warning("[zhipu-video] 未配置 ZHIPU_VIDEO_API_KEY，降级 mock。")
            return await self._degrade_submit(prompt, image_url, params)

        try:
            return await self._submit_via_api(prompt, image_url, params)
        except ZhipuVideoRetryableError:
            raise
        except Exception as exc:
            logger.error(f"[zhipu-video] 真实提交失败，降级 mock: {exc}")
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
        except ZhipuVideoRetryableError:
            raise
        except Exception as exc:
            logger.error(f"[zhipu-video] 真实查询失败 task_id={task_id}，降级 mock: {exc}")
            return await self._degrade_poll(task_id)

    async def _submit_via_api(
        self,
        prompt: str,
        image_url: str,
        params: dict | None,
    ) -> str:
        """调用智谱 API 创建视频生成任务。

        Args:
            prompt: 视频生成提示词。
            image_url: 首帧图 URL（当前 cogvideox-3 仅支持文生，忽略此参数）。
            params: 额外参数（quality/size/with_audio）。

        Returns:
            str: 厂商侧 task_id。
        """
        p = params or {}

        body: dict = {
            "model": self._model,
            "prompt": prompt,
            "quality": p.get("quality", "quality"),
            "with_audio": p.get("with_audio", False),
            "size": p.get("size", "1280x720"),
        }

        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._api_base}/videos/generations",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ZhipuVideoRetryableError(f"智谱视频 API 请求超时: {exc}")
        except httpx.HTTPError as exc:
            raise ZhipuVideoRetryableError(f"智谱视频 API 网络错误: {exc}")

        if resp.status_code != 200:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ZhipuVideoRetryableError(
                    f"智谱视频 API 返回 {resp.status_code}: {resp.text[:300]}"
                )
            raise RuntimeError(f"智谱视频 API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        task_id = str(data.get("id") or data.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"智谱视频 API 响应缺少 task id: {str(data)[:300]}")

        logger.info(f"[zhipu-video] 任务已创建 task_id={task_id}, model={self._model}")
        return task_id

    async def _poll_via_api(self, task_id: str) -> dict:
        """调用智谱 API 查询视频任务状态。

        Args:
            task_id: 创建任务时返回的 task_id。

        Returns:
            dict: {"status": queued/running/done/failed, "url": ...}
        """
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._api_base}/async-result/{task_id}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise ZhipuVideoRetryableError(f"智谱视频查询超时: {exc}")
        except httpx.HTTPError as exc:
            raise ZhipuVideoRetryableError(f"智谱视频查询网络错误: {exc}")

        if resp.status_code != 200:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ZhipuVideoRetryableError(
                    f"智谱视频查询 API 返回 {resp.status_code}: {resp.text[:300]}"
                )
            raise RuntimeError(f"智谱视频查询 API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        raw_status = str(data.get("task_status") or "").upper()

        # 状态映射：智谱 PROCESSING / SUCCESS / FAIL
        if raw_status == "SUCCESS":
            video_result = data.get("video_result") or []
            url = ""
            if video_result and len(video_result) > 0:
                url = video_result[0].get("url", "")
            return {"status": "done", "url": url, "progress": 100}
        if raw_status == "FAIL":
            error = data.get("error", {})
            error_msg = error.get("message", "生成失败") if isinstance(error, dict) else str(error)
            return {"status": "failed", "url": "", "error": error_msg}
        if raw_status == "PROCESSING":
            return {"status": "running", "url": "", "progress": 0}
        # 未知状态视为进行中
        return {"status": "queued", "url": ""}

    async def _degrade_submit(self, prompt: str, image_url: str, params: dict | None) -> str:
        """降级提交到 mock。"""
        self.last_degraded = True
        task_id = await self._mock.submit(prompt, image_url, params)
        self._degraded_tasks.add(task_id)
        return task_id

    async def _degrade_poll(self, task_id: str) -> dict:
        """降级查询 mock 结果并附加标记。"""
        self.last_degraded = True
        result = await self._mock.poll(task_id)
        result["provider"] = self.DEGRADED_PROVIDER_TAG
        result["degraded"] = True
        result["task_id"] = task_id or f"zhipu-degraded-{uuid.uuid4().hex[:8]}"
        return result
