"""临时脚本：实测 qwen3-tts-flash 接口。"""
import asyncio
import base64
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[3] / ".env"
cfg = {}
for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        cfg[k.strip()] = v.strip()

BASE = "https://dashscope.aliyuncs.com/api/v1"
KEY = cfg.get("QIANWEN_TTS_API_KEY", "")
PATH = "/services/aigc/multimodal-generation/generation"

body = {
    "model": "qwen3-tts-flash",
    "input": {
        "text": "你好，这是一段通义千问语音合成测试。",
        "voice": "Cherry",
        "language_type": "Chinese",
    },
}


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{BASE}{PATH}",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json=body,
        )
        print("status:", r.status_code)
        print("body head:", r.text[:1000])
        if r.status_code == 200:
            data = r.json()
            audio = data.get("output", {}).get("audio", {})
            url = audio.get("url")
            b64 = audio.get("data")
            print("audio.url:", url)
            print("audio.data len:", len(b64 or ""))
            outp = Path(__file__).parent / "qianwen_test.mp3"
            if b64:
                outp.write_bytes(base64.b64decode(b64))
            elif url:
                rr = await client.get(url)
                outp.write_bytes(rr.content)
            print("saved ->", outp, outp.stat().st_size, "bytes")


asyncio.run(main())
