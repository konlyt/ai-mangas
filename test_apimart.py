import httpx
try:
    # 测试1：不用代理
    r = httpx.get("https://api.apimart.ai/v1", timeout=10, trust_env=False)
    print("No proxy - Status:", r.status_code)
except Exception as e:
    print("No proxy - Error:", type(e).__name__, str(e))

try:
    # 测试2：用系统代理
    r = httpx.get("https://api.apimart.ai/v1", timeout=10, proxy="http://127.0.0.1:7897")
    print("With proxy - Status:", r.status_code)
except Exception as e:
    print("With proxy - Error:", type(e).__name__, str(e))
