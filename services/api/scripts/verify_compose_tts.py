"""验证 TTS 模式：给项目29第一个有台词的分镜配真实 TTS，再跑 auto 合成。"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal
from app.models import Project, Storyboard, Task, TaskStatus, TaskType, QueueName
from app.providers.tts.registry import get_tts_registry
from app.tasks.compose_tasks import compose_video


async def main():
    pid = 29
    async with AsyncSessionLocal() as session:
        # 找有 dialogue 的分镜
        from sqlalchemy import select
        rows = await session.execute(
            select(Storyboard).where(
                Storyboard.project_id == pid,
                Storyboard.video_url.isnot(None),
                Storyboard.dialogue.isnot(None),
            ).order_by(Storyboard.sequence)
        )
        sb = rows.scalars().first()
        if sb is None:
            print("no storyboard with dialogue+video")
            return
        print(f"using storyboard id={sb.id} seq={sb.sequence} dur={sb.duration}")
        print(f"dialogue: {(sb.dialogue or '')[:80]}")

        provider = get_tts_registry().get_provider("qianwen")
        audio_url = await provider.synthesize(sb.dialogue, "Cherry")
        print(f"tts url = {audio_url}, degraded={getattr(provider, 'last_degraded', False)}")
        sb.audio_url = audio_url

        project = await session.get(Project, pid)
        cfg = dict(project.config or {})
        cfg["audio_mode"] = "auto"
        project.config = cfg

        task = Task(
            project_id=pid,
            type=TaskType.COMPOSE,
            status=TaskStatus.QUEUED,
            queue_name=QueueName.NORMAL,
            priority=5,
            idempotency_key=f"{pid}-compose-verify2-{int(time.time())}",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        print(f"task id={task.id}")

    result = await compose_video({}, task.id, storyboard_ids=None)
    print("compose result:", result)


asyncio.run(main())
