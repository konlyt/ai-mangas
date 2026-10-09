"""
通义千问（Qianwen / DashScope）TTS Provider。

调用阿里云 DashScope 的多模态生成接口实现语音合成，
模型为 qwen3-tts-instruct-flash。
"""

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.storage import save_artifact
from app.providers.tts.base import TTSProvider
from app.providers.tts.mock import MockTTSProvider

logger = get_logger()


class QianwenTTSProvider(TTSProvider):
    """通义千问 TTS Provider。

    通过 DashScope 多模态生成接口调用 qwen3-tts-instruct-flash 模型，
    将文本合成为语音并返回音频文件 URL。

    Attributes:
        _api_base: DashScope 基础地址。
        _api_key: DashScope API Key。
        _model: TTS 模型名。
        _api_path: 接口路径。
        _timeout_ms: 请求超时（毫秒）。
        _max_retries: 最大重试次数。
        _mock: 内部持有的 Mock Provider，用于降级。
        last_degraded: 最近一次 synthesize 是否发生了降级。
    """

    def __init__(self) -> None:
        """初始化通义千问 TTS Provider，从全局配置读取凭证。"""
        self._api_base = (settings.QIANWEN_TTS_API_BASE_URL or "https://dashscope.aliyuncs.com").rstrip("/")
        self._api_key = settings.QIANWEN_TTS_API_KEY or ""
        self._model = settings.QIANWEN_TTS_MODEL or "qwen3-tts-instruct-flash"
        self._api_path = settings.QIANWEN_TTS_API_PATH or "/api/v1/services/aigc/multimodal-generation/generation"
        self._timeout_ms = settings.QIANWEN_TTS_TIMEOUT_MS or 120000
        self._max_retries = settings.QIANWEN_TTS_MAX_RETRIES or 0
        self._allow_demo_fallback = settings.QIANWEN_TTS_ALLOW_DEMO_FALLBACK
        self._mock = MockTTSProvider()
        self.last_degraded: bool = False

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        params: dict | None = None,
    ) -> str:
        """将文本合成为语音并返回音频 URL。

        Args:
            text: 待合成的文本内容。
            voice_id: 音色 ID（通义千问默认使用 longxiaochun 等音色名）。
            params: 额外参数（speed/volume 等）。

        Returns:
            str: 合成音频的访问 URL。

        Raises:
            RuntimeError: 真实合成失败且不允许降级时抛出。
        """
        # 未配置 API Key 时直接走 mock
        if not self._api_base or not self._api_key:
            logger.warning("[qianwen-tts] 未配置 QIANWEN_TTS_API_KEY，降级 mock。")
            self.last_degraded = True
            return await self._mock.synthesize(text, voice_id, params)

        try:
            return await self._synthesize_via_api(text, voice_id, params)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[qianwen-tts] 真实合成失败，降级 mock: {exc}")
            self.last_degraded = True
            if self._allow_demo_fallback:
                return await self._mock.synthesize(text, voice_id, params)
            raise RuntimeError(f"通义千问 TTS 合成失败: {exc}") from exc

    async def _synthesize_via_api(
        self,
        text: str,
        voice_id: str,
        params: dict | None,
    ) -> str:
        """调用 DashScope 多模态生成接口完成 TTS 合成。

        Args:
            text: 待合成文本。
            voice_id: 音色 ID。
            params: 额外参数。

        Returns:
            str: 音频落盘后的 /static/audio/... 访问 URL。

        Raises:
            RuntimeError: API 返回非 200 或解析响应失败时抛出。
        """
        p = params or {}
        url = f"{self._api_base}{self._api_path}"

        # 通义千问 qwen3-tts 请求体格式
        voice = voice_id or "longxiaochun"
        body = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"text": text},
                            {"type": "voice", "voice": voice},
                        ],
                    }
                ]
            },
            "parameters": {
                "result_format": "mp3",
            },
        }

        # 可选参数：语速
        if "speed" in p:
            body["parameters"]["speed"] = p["speed"]

        async with httpx.AsyncClient(timeout=self._timeout_ms / 1000) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"通义千问 TTS API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()

        # 解析响应：从 output 中提取音频 URL 或 base64
        output = data.get("output", {})
        choices = output.get("choices", [])

        if not choices:
            raise RuntimeError("通义千问 TTS 返回空 choices")

        message = choices[0].get("message", {})
        content = message.get("content", [])

        # 查找音频类型的内容
        audio_url = None
        audio_base64 = None
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "audio_url" and item.get("audio_url", {}).get("url"):
                    audio_url = item["audio_url"]["url"]
                elif item.get("type") == "audio" and item.get("audio"):
                    audio_base64 = item["audio"]

        if audio_base64:
            # base64 音频：解码后落盘
            import base64
            audio_bytes = base64.b64decode(audio_base64)
            return save_artifact(audio_bytes, "audio", "mp3")

        if audio_url:
            # 远端音频 URL：下载后落盘
            async with httpx.AsyncClient(timeout=30.0) as client:
                audio_resp = await client.get(audio_url)
            if audio_resp.status_code == 200 and audio_resp.content:
                return save_artifact(audio_resp.content, "audio", "mp3")
            raise RuntimeError(f"下载通义千问音频失败: {audio_resp.status_code}")

        raise RuntimeError("通义千问 TTS 响应中未找到音频数据")
