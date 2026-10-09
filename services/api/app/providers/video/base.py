"""
视频生成 Provider 抽象基类。

定义所有视频生成厂商必须实现的统一接口，包含 submit（提交任务）
与 poll（轮询结果）两个阶段。
"""

from abc import ABC, abstractmethod
from typing import Optional


class VideoProvider(ABC):
    """视频生成 Provider 抽象基类。

    所有具体视频生成厂商均需继承本类并实现 submit 与 poll 方法。
    """

    @abstractmethod
    async def submit(
        self,
        prompt: str,
        image_url: str,
        params: Optional[dict] = None,
    ) -> str:
        """提交视频生成任务并返回厂商侧任务 ID。

        Args:
            prompt: 视频生成提示词。
            image_url: 首帧图 URL。
            params: 额外参数（如时长、分辨率、运镜等）。

        Returns:
            str: 厂商侧任务 ID，用于后续轮询。

        Raises:
            NotImplementedError: 子类未实现时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    async def poll(self, task_id: str) -> dict:
        """轮询视频生成任务的状态与结果。

        Args:
            task_id: 厂商侧任务 ID。

        Returns:
            dict: 包含 status（queued/running/done/failed）与 url（视频地址，done 时）的字典。

        Raises:
            NotImplementedError: 子类未实现时抛出。
        """
        raise NotImplementedError
