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
            if sb.id > 49: continue
            print(f"===== id={sb.id} seq={sb.sequence} =====")
            print(f"prompt: {sb.prompt!r}")
            print(f"visual_description (first 200): {(sb.visual_description or '')[:200]!r}")
            print()

asyncio.run(main())
