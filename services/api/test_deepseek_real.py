import httpx
import json
from app.domains.prompts import build_script_messages

raw_input = "请生成一个动漫剧本"
meta = {"genre": "科幻", "style": "二次元", "episode_count": 1, "episode_duration": 1}

messages = build_script_messages(raw_input, meta)

print("开始调用 DeepSeek...")
url = 'https://api.deepseek.com/v1/chat/completions'
headers = {
    'Authorization': 'Bearer sk-2f3f768969f2485694dd1a3072163315',
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
