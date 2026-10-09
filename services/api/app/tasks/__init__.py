"""
任务函数包。

聚合 image / video / tts / compose 四类任务函数，
供 ARQ Worker 注册使用。
"""

from app.tasks.compose_tasks import compose_video
from app.tasks.image_tasks import generate_image
from app.tasks.tts_tasks import generate_tts
from app.tasks.video_tasks import generate_video

__all__ = [
    "generate_image",
    "generate_video",
    "generate_tts",
    "compose_video",
]
