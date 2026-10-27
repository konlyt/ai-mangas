import asyncio, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Script
from sqlalchemy import select, desc

async def m():
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(Script).where(Script.project_id==31).order_by(desc(Script.id)))
        sc = rows.scalars().first()
        c = sc.content
        print("TYPE:", type(c).__name__)
        if isinstance(c, str):
            print("STR:", c[:3000])
        else:
            print("KEYS:", list(c.keys()))
            print(json.dumps(c, ensure_ascii=False, indent=2)[:3000])

asyncio.run(m())
