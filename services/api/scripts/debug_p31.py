import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import AsyncSessionLocal
from app.models import Project, Script, Task
from sqlalchemy import select, desc

async def main():
    async with AsyncSessionLocal() as s:
        for pid in (30, 31):
            p = await s.get(Project, pid)
            if p is None:
                print(f"project {pid} not found")
                continue
            print(f"===== project {pid}: {p.title!r} style={p.style} status={p.status} =====")
            scr = await s.execute(select(Script).where(Script.project_id==pid).order_by(desc(Script.id)))
            for sc in scr.scalars():
                print(f"  script id={sc.id} version={sc.version} content_len={len(sc.content or '')} content_head={(sc.content or '')[:200]!r}")
            tasks = await s.execute(select(Task).where(Task.project_id==pid).order_by(desc(Task.id)).limit(8))
            for t in tasks.scalars():
                print(f"  task id={t.id} type={t.type} status={t.status} err={(t.error_message or '')[:200]}")
            print()

asyncio.run(main())
