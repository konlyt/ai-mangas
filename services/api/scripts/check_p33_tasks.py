import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task, TaskStatus
from sqlalchemy import select, update

async def m():
    async with AsyncSessionLocal() as s:
        # 查每个分镜
        sbs = await s.execute(select(Storyboard).where(Storyboard.project_id==33).order_by(Storyboard.sequence))
        for sb in sbs.scalars():
            print(f"seq={sb.sequence} sb_id={sb.id} video_url={sb.video_url!r}")
            # 查这个分镜的 video task
            tasks = await s.execute(select(Task).where(Task.storyboard_id==sb.id, Task.type=='video').order_by(Task.id.desc()))
            for t in tasks.scalars():
                print(f"  task id={t.id} status={t.status} result={t.result_url!r}")

asyncio.run(m())
