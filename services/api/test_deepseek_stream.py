import httpx
import json
import os

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    raise SystemExit("请先设置环境变量 DEEPSEEK_API_KEY（不要把 Key 写进代码或提交到仓库）")

url = 'https://api.deepseek.com/v1/chat/completions'
headers = {
    'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
    'Content-Type': 'application/json',
}
data = {
    'model': 'deepseek-flash',
    'messages': [{'role': 'user', 'content': '写一个末日求生的短剧本，30字以内'}],
    'stream': True,
}

print("开始流式调用...")
with httpx.stream("POST", url, headers=headers, json=data, timeout=60.0) as response:
    print(f"Status: {response.status_code}")
    full_text = ""
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
