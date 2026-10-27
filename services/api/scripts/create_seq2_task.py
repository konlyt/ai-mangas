import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task, TaskStatus
from sqlalchemy import select

async def m():
    async with AsyncSessionLocal() as s:
        # 找 seq=2 的分镜
        sb = await s.execute(select(Storyboard).where(Storyboard.project_id==33, Storyboard.sequence==2))
        sb = sb.scalars().first()
        print(f"seq=2 sb_id={sb.id} keyframe={sb.keyframe_url}")
        # 创建 PENDING task
        t = Task(
            project_id=33,
            storyboard_id=sb.id,
            type='video',
            status=TaskStatus.PENDING,
            cost_points=0,
            idempotency_key=f"manual-s33-seq2-retry",
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        print(f"created task id={t.id} for seq=2")

asyncio.run(m())
