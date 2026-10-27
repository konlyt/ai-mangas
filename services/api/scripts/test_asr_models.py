"""试多个 dashscope 音频模型名，找到能做 ASR 转写的那个。"""
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(r"E:\Class Project\ai漫剧\.env"))
api_key = os.getenv("QIANWEN_TTS_API_KEY")
wav = Path(r"E:\Class Project\ai漫剧\services\api\static\outputs\29\seg0.wav")
audio_b64 = base64.b64encode(wav.read_bytes()).decode()

url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

for model in ["qwen-audio-turbo-latest", "qwen2-audio-instruct", "qwen-audio-asr", "paraformer-v2"]:
    body = {
        "model": model,
        "input": {
            "messages": [
                {"role": "user", "content": [
                    {"audio": f"data:audio/wav;base64,{audio_b64}"},
                    {"text": "请逐字转写音频里的中文，只输出转写文字。"},
                ]}
            ]
        },
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60)
        print(f"=== {model} => {r.status_code} ===")
        print(r.text[:600])
        print()
    except Exception as e:
        print(f"=== {model} => EXC {e} ===")
