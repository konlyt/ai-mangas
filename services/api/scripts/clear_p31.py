import asyncio, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Script, Project, ProjectStatus
from sqlalchemy import select, desc, delete

async def m():
    async with AsyncSessionLocal() as s:
        # 删掉错误剧本
        await s.execute(delete(Script).where(Script.project_id==31))
        # 项目状态回 DRAFT
        p = await s.get(Project, 31)
        p.status = ProjectStatus.DRAFT
        await s.commit()
        print("cleared project 31")

asyncio.run(m())
