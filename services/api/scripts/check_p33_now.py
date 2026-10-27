import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task
from sqlalchemy import select

async def m():
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(Storyboard).where(Storyboard.project_id==33).order_by(Storyboard.sequence))
        for sb in rows.scalars():
            print(f"sb seq={sb.sequence} video_url={sb.video_url!r}")
        print()
        tasks = await s.execute(select(Task).where(Task.project_id==33).order_by(Task.id))
        for t in tasks.scalars():
            print(f"task id={t.id} sb={t.storyboard_id} type={t.type} status={t.status} provider_task={t.provider_task_id!r} result={t.result_url!r}")

asyncio.run(m())
