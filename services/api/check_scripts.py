import asyncio
from sqlalchemy import select, desc
from app.core.database import AsyncSessionLocal
from app.models import Script

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Script).where(Script.project_id == 23).order_by(desc(Script.id)).limit(5))
        scripts = result.scalars().all()
        for s in scripts:
            print(f"id={s.id}, version={s.version}, title={s.content.get('title', '无')}")

asyncio.run(main())
