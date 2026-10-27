"""查项目29的剧本原文 + 每个分镜的完整 visual_description/dialogue/prompt。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Storyboard, Script
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as s:
        # 剧本原文
        scr = await s.execute(select(Script).where(Script.project_id==29))
        sc = scr.scalars().first()
        print("===== SCRIPT =====")
        print(f"content:")
        print(sc.content)
        print()
        # 分镜
        rows = await s.execute(select(Storyboard).where(Storyboard.project_id==29).order_by(Storyboard.sequence))
        for sb in rows.scalars():
            print(f"===== storyboard id={sb.id} seq={sb.sequence} dur={sb.duration} =====")
            print(f"dialogue: {sb.dialogue!r}")
            print(f"visual_description:")
            print(sb.visual_description)
            print()

asyncio.run(main())
