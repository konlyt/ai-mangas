import asyncio, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.core.config import settings

# 09:36 提交的 minimax task_id → 分镜序号映射
# 从日志里提取的：
# task 174 (sb=64, seq=1): provider_task=2113441612608667648 (旧的, 09:15那批)
# task 175 (sb=65, seq=2): provider_task=2113441612387549184 (旧的)
# task 179 (sb=69, seq=6): provider_task=2113441628802613248 (旧的)
# 09:36 新提交的:
# 2113444714832302080, 2113444716828262400, 2113444716873351168, 2113444716788940801

# 先查旧的 provider_task_id 对应哪个分镜
# sb=64 seq=1 -> 2113441612608667648
# sb=65 seq=2 -> 2113441612387549184
# sb=69 seq=6 -> 2113441628802613248

async def query_task(api_base, api_key, task_id):
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        r = await c.get(
            f"{api_base}/query/video_generation",
            params={"task_id": task_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return r.json()

async def main():
    base = (settings.MINIMAX_VIDEO_BASE_URL or "https://metaso.cn/api/minimax/v2").rstrip("/")
    key = settings.MINIMAX_VIDEO_API_KEY
    task_ids = [
        ("seq1", "2113441612608667648"),
        ("seq2", "2113441612387549184"),
        ("seq6", "2113441628802613248"),
    ]
    for label, tid in task_ids:
        try:
            data = await query_task(base, key, tid)
            items = data.get("items", [])
            for it in items:
                print(f"{label} query {tid}: id={it.get('id')} status={it.get('status')} url={it.get('content',{}).get('url','')[:100]}")
        except Exception as e:
            print(f"{label} query {tid} ERROR: {e}")

asyncio.run(main())
