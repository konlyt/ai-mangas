"""
通义千问（Qwen-TTS / DashScope）语音合成 Provider。

调用阿里云百炼 qwen3-tts-flash 非实时语音合成接口：
    POST {base}/api/v1/services/aigc/multimodal-generation/generation
请求体：{"model": "qwen3-tts-flash", "input": {"text": ..., "voice": ..., "language_type": "Chinese"}}
响应：output.audio.url（OSS wav 链接）或 output.audio.data（base64）。
"""

import base64

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.storage import save_artifact
from app.providers.tts.base import TTSProvider
from app.providers.tts.mock import MockTTSProvider

logger = get_logger()

# qwen3-tts-flash 默认音色（实测可用，女声）
DEFAULT_QIANWEN_VOICE = "Cherry"


class QianwenTTSProvider(TTSProvider):
    """通义千问 qwen3-tts-flash 语音合成 Provider。

    Attributes:
        _api_base: DashScope 基础地址（不含 path）。
        _api_key: DashScope API Key。
        _model: 模型名。
        _api_path: 接口路径。
        _timeout_ms: 请求超时（毫秒）。
        _allow_demo_fallback: 失败时是否允许降级 mock。
        _mock: 内部持有的 Mock Provider，用于降级。
        last_degraded: 最近一次 synthesize 是否发生了降级。
    """

    def __init__(self) -> None:
        """初始化通义千问 TTS Provider，从全局配置读取凭证。"""
        self._api_base = (settings.QIANWEN_TTS_API_BASE_URL or "https://dashscope.aliyuncs.com").rstrip("/")
        self._api_key = settings.QIANWEN_TTS_API_KEY or ""
        self._model = settings.QIANWEN_TTS_MODEL or "qwen3-tts-flash"
        self._api_path = settings.QIANWEN_TTS_API_PATH or "/api/v1/services/aigc/multimodal-generation/generation"
        self._timeout_ms = (settings.QIANWEN_TTS_TIMEOUT_MS or 120000) / 1000
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
            text: 待合成文本。
            voice_id: 音色 ID（如 Cherry / Ethan / Mia）。
            params: 额外参数（speed 等，预留）。

        Returns:
            str: 合成音频的 /static/audio/... 访问 URL。

        Raises:
            RuntimeError: 真实合成失败且不允许降级时抛出。
        """
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
        """调用 DashScope qwen3-tts-flash 接口完成 TTS 合成。

        Args:
            text: 待合成文本。
            voice_id: 音色 ID。
            params: 额外参数（预留）。

        Returns:
            str: 音频落盘后的 /static/audio/... 访问 URL。

        Raises:
            RuntimeError: API 返回非 200 或解析响应失败时抛出。
        """
        speed = (params or {}).get("speed", 1.0)
        body = {
            "model": self._model,
            "input": {
                "text": text,
                "voice": voice_id or DEFAULT_QIANWEN_VOICE,
                "language_type": "Chinese",
                "speed": speed,
            },
        }

        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.post(
                f"{self._api_base}{self._api_path}",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"通义千问 TTS API 返回 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        audio = (data.get("output") or {}).get("audio") or {}
        audio_url = audio.get("url")
        audio_b64 = audio.get("data")

        if audio_b64:
            audio_bytes = base64.b64decode(audio_b64)
            return save_artifact(audio_bytes, "audio", "wav")

        if audio_url:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                audio_resp = await client.get(audio_url)
            if audio_resp.status_code == 200 and audio_resp.content:
                return save_artifact(audio_resp.content, "audio", "wav")
            raise RuntimeError(f"下载通义千问音频失败: {audio_resp.status_code}")

        raise RuntimeError("通义千问 TTS 响应中未找到音频数据")
