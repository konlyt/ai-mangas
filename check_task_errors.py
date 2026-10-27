"""查看视频任务的错误信息"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "api"))

from app.core.database import AsyncSessionLocal
from app.models import Task, TaskStatus
from sqlalchemy import select


async def check():
    async with AsyncSessionLocal() as db:
        # 查询项目 24 的所有视频任务
        result = await db.execute(
            select(Task)
            .where(Task.project_id == 24, Task.type == "video")
            .order_by(Task.id.desc())
            .limit(10)
        )
        tasks = result.scalars().all()

        print("=== 视频任务列表 ===")
        for t in tasks:
            print(f"任务 ID: {t.id}")
            print(f"  状态: {t.status}")
            print(f"  Provider Task ID: {t.provider_task_id}")
            print(f"  结果 URL: {t.result_url}")
            print(f"  错误信息: {t.error_message}")
            print(f"  重试次数: {t.retry_count}/{t.max_retry}")
            print()


if __name__ == "__main__":
    asyncio.run(check())
