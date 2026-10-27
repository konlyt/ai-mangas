import asyncio, sys, re, json
sys.path.insert(0, '.')
from app.core.database import AsyncSessionLocal
from app.models import Script, Storyboard
from sqlalchemy import select, update

async def m():
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(Script).where(Script.project_id==33))
        sc = r.scalars().first()
        content = sc.content
        if isinstance(content, str):
            content = json.loads(content)
        scenes = content.get('scenes', [])
        print(f"scenes count: {len(scenes)}")
        for sc in scenes:
            seq = sc.get('seq')
            desc = sc.get('description', '')
            # 提取台词行：角色：...
            lines = re.findall(r'([^\s△△][^：\n]{1,10})：([^\n]+)', desc)
            print(f"\n=== scene {seq} ===")
            for name, line in lines:
                name = name.strip()
                line = line.strip()
                if name in ('△',): continue
                # 写入 storyboard.dialogue（多行，按角色：台词）
                print(f"  {name}: {line[:60]}")

asyncio.run(m())
