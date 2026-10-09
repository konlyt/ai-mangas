"""
视频生成 Mock Provider。

用于开发与测试环境，submit 后立即返回一个占位视频 URL，
poll 始终返回 done 状态，无需真实调用。
"""

import uuid

from app.providers.video.base import VideoProvider


class MockVideoProvider(VideoProvider):
    """Mock 视频生成 Provider。

    模拟两阶段视频生成流程：submit 返回任务 ID，poll 返回 done + 占位视频 URL。
    """

    # 占位视频：自托管于后端静态目录（/static 挂载，见 main.py 与 providers/storage.py），
    # 由项目 tools/ffmpeg.exe 的 testsrc 源生成；改用外链会被对端 403 拒绝
    PLACEHOLDER_VIDEO_URL = "/static/placeholders/placeholder_video.mp4"

    async def submit(
        self,
        prompt: str,
        image_url: str,
        params: dict | None = None,
    ) -> str:
        """提交 mock 视频任务并返回任务 ID。

        Args:
            prompt: 视频提示词（mock 模式下仅作日志用途）。
            image_url: 首帧图 URL（mock 模式下忽略）。
            params: 额外参数（mock 模式下忽略）。

        Returns:
            str: 模拟的厂商任务 ID。
        """
        return f"mock-video-{uuid.uuid4().hex[:12]}"

    async def poll(self, task_id: str) -> dict:
        """轮询 mock 视频任务状态。

        Args:
            task_id: 任务 ID。

        Returns:
            dict: 固定返回 {"status": "done", "url": 占位视频地址}。
        """
        return {"status": "done", "url": self.PLACEHOLDER_VIDEO_URL}
