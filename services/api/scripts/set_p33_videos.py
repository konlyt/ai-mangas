import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Task, TaskStatus
from sqlalchemy import update

async def m():
    async with AsyncSessionLocal() as s:
        mapping = {
            1: "/static/videos/33/shot1.mp4",
            4: "/static/videos/33/shot4.mp4",
            5: "/static/videos/33/shot5.mp4",
            6: "/static/videos/33/shot6.mp4",
        }
        for seq, url in mapping.items():
            await s.execute(
                update(Storyboard)
                .where(Storyboard.project_id==33, Storyboard.sequence==seq)
                .values(video_url=url)
            )
        await s.commit()
        print("updated seq 1,4,5,6 video_url")

asyncio.run(m())
