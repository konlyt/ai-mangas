import base64, os, sys
from pathlib import Path
import requests
from dotenv import load_dotenv
load_dotenv(Path(r"E:\Class Project\ai漫剧\.env"))
api_key = os.getenv("QIANWEN_TTS_API_KEY")
wav = Path(r"E:\Class Project\ai漫剧\services\api\static\outputs\29\seg0.wav")
b64 = base64.b64encode(wav.read_bytes()).decode()
url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
body = {
    "model": "qwen-audio-turbo-latest",
    "input": {"messages": [{"role": "user", "content": [
        {"audio": f"data:audio/wav;base64,{b64}"},
        {"text": "请逐字转写音频里的中文，只输出转写文字。"},
    ]}]},
}
r = requests.post(url, headers=headers, json=body, timeout=90)
print("status:", r.status_code)
print(r.text[:1500])
