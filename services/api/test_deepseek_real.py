import httpx
import json
import os
from app.domains.prompts import build_script_messages

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    raise SystemExit("请先设置环境变量 DEEPSEEK_API_KEY（不要把 Key 写进代码或提交到仓库）")

raw_input = "请生成一个动漫剧本"
meta = {"genre": "科幻", "style": "二次元", "episode_count": 1, "episode_duration": 1}

messages = build_script_messages(raw_input, meta)

print("开始调用 DeepSeek...")
url = 'https://api.deepseek.com/v1/chat/completions'
headers = {
    'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
    'Content-Type': 'application/json',
}
data = {
    'model': 'deepseek-flash',
    'messages': messages,
    'stream': True,
    'temperature': 0.7,
}

full_text = ""
with httpx.stream("POST", url, headers=headers, json=data, timeout=120.0) as response:
    print(f"Status: {response.status_code}")
    for line in response.iter_lines():
        if not line or not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            d = json.loads(data_str)
            delta = d["choices"][0]["delta"].get("content", "")
            if delta:
                full_text += delta
                print(delta, end="", flush=True)
        except Exception as e:
            print(f"解析错误: {e}")

print(f"\n\n总长度: {len(full_text)}")
print("\n前500字:")
print(full_text[:500])
