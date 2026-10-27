"""端到端验证：项目29 用 keep_original 模式合成，验证成片带原视频音轨。"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal
from app.models import Project, Storyboard, Task, TaskStatus, TaskType, QueueName
from app.tasks.compose_tasks import compose_video


async def main():
    pid = 29
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, pid)
        cfg = dict(project.config or {})
        cfg["audio_mode"] = "keep_original"
        project.config = cfg
        task = Task(
            project_id=pid,
            type=TaskType.COMPOSE,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=f"{pid}-compose-verify-{int(__import__('time').time())}",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        print(f"created verify task id={task.id} audio_mode=keep_original")

    result = await compose_video({}, task.id, storyboard_ids=None)
    print("compose result:", json.dumps(result, ensure_ascii=False))


asyncio.run(main())
