import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task, TaskStatus
from sqlalchemy import select

async def m():
    async with AsyncSessionLocal() as s:
        # 每个分镜的 video_url
        sbs = await s.execute(select(Storyboard).where(Storyboard.project_id==33).order_by(Storyboard.sequence))
        for sb in sbs.scalars():
            if not sb.video_url:
                continue
            # 查有没有 video task
            existing = await s.execute(select(Task).where(Task.storyboard_id==sb.id, Task.type=='video'))
            if existing.scalars().first():
                continue
            # 创建 DONE task
            t = Task(
                project_id=33,
                storyboard_id=sb.id,
                type='video',
                status=TaskStatus.DONE,
                result_url=sb.video_url,
                cost_points=0,
                idempotency_key=f"manual-s33-seq{sb.sequence}",
            )
            s.add(t)
            print(f"created DONE task for seq={sb.sequence} url={sb.video_url}")
        await s.commit()

asyncio.run(m())
