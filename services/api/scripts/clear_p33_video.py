import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task
from sqlalchemy import update, delete

async def m():
    async with AsyncSessionLocal() as s:
        # 清空所有分镜的 video_url
        await s.execute(update(Storyboard).where(Storyboard.project_id==33).values(video_url=None))
        # 删除所有 video 类型任务
        await s.execute(delete(Task).where(Task.project_id==33, Task.type=='video'))
        await s.commit()
        print("cleared project 33 video data")

asyncio.run(m())
