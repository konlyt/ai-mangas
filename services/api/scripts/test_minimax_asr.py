"""试 minimax 语音转写接口。"""
import os
from pathlib import Path
import requests
from dotenv import load_dotenv
load_dotenv(Path(r"E:\Class Project\ai漫剧\.env"))

api_key = os.getenv("MINIMAX_VIDEO_API_KEY")
base = os.getenv("MINIMAX_VIDEO_BASE_URL", "https://api.minimax.chat/v1").rstrip("/")
print("base:", base, "key:", api_key[:10])

wav = Path(r"E:\Class Project\ai漫剧\services\api\static\outputs\29\seg0.wav")
# minimax audio_transcription 接受 file 上传
url = base + "/audio_transcription"
headers = {"Authorization": f"Bearer {api_key}"}
files = {"file": ("seg0.wav", wav.read_bytes(), "audio/wav")}
try:
    r = requests.post(url, headers=headers, files=files, timeout=60)
    print("status:", r.status_code)
    print(r.text[:1500])
except Exception as e:
    print("exc:", e)
