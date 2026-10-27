import asyncio, sys
sys.path.insert(0, '.')
from app.core.database import AsyncSessionLocal
from app.models import Script, Storyboard
from sqlalchemy import select

async def m():
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(Script).where(Script.project_id==33))
        sc = r.scalars().first()
        if sc:
            cols = {c.name: getattr(sc, c.name, None) for c in sc.__table__.columns}
            for k,v in cols.items():
                if k in ('id','project_id','content'):
                    print(f"{k}: {str(v)[:800]}")

asyncio.run(m())
