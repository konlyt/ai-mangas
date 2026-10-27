import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task
from sqlalchemy import update, delete

async def m():
    async with AsyncSessionLocal() as s:
        # 保留 sequence=3，清空其他分镜的 video_url
        await s.execute(
            update(Storyboard)
            .where(Storyboard.project_id==33, Storyboard.sequence != 3)
            .values(video_url=None)
        )
        # 删除除 sb=66(seq=3) 外的 video 任务
        await s.execute(
            delete(Task)
            .where(Task.project_id==33, Task.type=='video', Task.storyboard_id != 66)
        )
        await s.commit()
        print("cleared all except seq=3")

asyncio.run(m())
