import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(Storyboard).where(Storyboard.project_id==29).order_by(Storyboard.sequence))
        for sb in rows.scalars():
            print(f"===== id={sb.id} seq={sb.sequence} dur={sb.duration} =====")
            print(f"dialogue: {sb.dialogue!r}")
            print(f"audio_url: {sb.audio_url}")
            print(f"video_url: {sb.video_url}")
            print()

asyncio.run(main())
