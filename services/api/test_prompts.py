import asyncio
from app.domains.prompts import build_script_messages

raw_input = "末日求生，一个普通人在丧尸爆发后的城市里挣扎求生的故事"
meta = {"genre": "科幻", "style": "二次元", "episode_count": 1, "episode_duration": 1}

messages = build_script_messages(raw_input, meta)

print("系统提示词长度:", len(messages[0]["content"]))
print("用户提示词长度:", len(messages[1]["content"]))
print("\n系统提示词前500字:")
print(messages[0]["content"][:500])
print("\n用户提示词前500字:")
print(messages[1]["content"][:500])
