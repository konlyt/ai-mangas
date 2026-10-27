import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Project, Script, Task
from sqlalchemy import select, desc

async def main():
    async with AsyncSessionLocal() as s:
        # 最近创建的项目
        rows = await s.execute(select(Project).order_by(desc(Project.id)).limit(5))
        for p in rows.scalars():
            print(f"project id={p.id} title={p.title!r} style={p.style} status={p.status} created={p.created_at}")
        print()
        # 最新项目的 script
        pid = 30
        scr = await s.execute(select(Script).where(Script.project_id==pid).order_by(desc(Script.id)))
        for sc in scr.scalars():
            print(f"script id={sc.id} project={sc.project_id} version={sc.version} content_len={len(sc.content or '')}")
        print()
        # 最新项目的 task
        tasks = await s.execute(select(Task).where(Task.project_id==pid).order_by(desc(Task.id)).limit(10))
        for t in tasks.scalars():
            print(f"task id={t.id} type={t.type} status={t.status} retry={t.retry_count} err={(t.error_message or '')[:120]}")

asyncio.run(main())
