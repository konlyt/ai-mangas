"""用 dashscope qwen-audio-asr 转写本地 wav，验证 ASR 可行性。"""
import base64
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(r"E:\Class Project\ai漫jù\.env"))
# 上面路径有误，用真实路径
load_dotenv(Path(r"E:\Class Project\ai漫剧\.env"))

api_key = os.getenv("QIANWEN_TTS_API_KEY")
wav = Path(r"E:\Class Project\ai漫剧\services\api\static\outputs\29\seg0.wav")
audio_b64 = base64.b64encode(wav.read_bytes()).decode()

url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}
body = {
    "model": "qwen-audio-asr-latest",
    "input": {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"audio": f"data:audio/wav;base64,{audio_b64}"},
                    {"text": "请把这段音频里说的中文逐字转写出来，只输出转写文字。"},
                ],
            }
        ]
    },
}
r = requests.post(url, headers=headers, json=body, timeout=60)
print("status:", r.status_code)
print(r.text[:2000])
