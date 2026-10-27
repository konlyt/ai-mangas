import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Character, AssetVariant
from sqlalchemy import select

async def m():
    async with AsyncSessionLocal() as s:
        rows = await s.execute(select(Character).where(Character.project_id==33))
        chars = rows.scalars().all()
        print(f"project 33 characters: {len(chars)}")
        for c in chars:
            print(f"  char id={c.id} name={c.name!r} main_url={c.main_asset_url!r}")
            vs = await s.execute(select(AssetVariant).where(AssetVariant.owner_id==c.id))
            for v in vs.scalars():
                print(f"    variant id={v.id} type={v.variant_type} status={v.status} url={v.image_url!r}")

asyncio.run(m())
