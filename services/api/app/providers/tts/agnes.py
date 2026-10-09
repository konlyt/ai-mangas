"""
Agnes AI 语音合成（TTS）Provider。

按 OpenAI TTS 惯例调用 Agnes APIHub 的 /audio/speech 端点
（model/voice/input/response_format，使用 AGNES_LLM_API_KEY 鉴权）。

实测结论（2026-10-08）：该网关当前对 /audio/speech 返回 404 Not Found，
即 TTS 能力暂不支持。本模块保持完整实现（网关未来开放即可直接生效），
404 时内部抛出"不支持"异常并由 synthesize 捕获后降级为 Mock 实现，
调用方（voice_agent / tts_tasks）无需感知即可拿到可用的占位音频 URL。
"""

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.storage import save_artifact
from app.providers.tts.base import TTSProvider
from app.providers.tts.mock import MockTTSProvider

logger = get_logger()


class AgnesTTSProvider(TTSProvider):
    """Agnes AI 语音合成 Provider。

    调用 Agnes APIHub 的 OpenAI 兼容 TTS 接口；当前网关返回 404 不支持，
    因此实际运行时总是降级为 MockTTSProvider（占位音频），保证流程可演示。

    Attributes:
        _api_base: Agnes APIHub 基础地址。
        _api_key: API Key（TTS 无独立 Key，复用 LLM Key）。
        _model: TTS 模型名（网关开放前仅作占位）。
        _mock: 内部持有的 Mock Provider，用于降级。
        last_degraded: 最近一次 synthesize 是否发生了降级（仅供诊断参考）。
    """

    # 音频为小体积二进制，超时 60s 足够
    REQUEST_TIMEOUT = 60.0

    def __init__(self) -> None:
        """初始化 Agnes TTS Provider，从全局配置读取凭证。

        Returns:
            None
        """
        self._api_base = (settings.AGNES_BASE_URL or "").rstrip("/")
        # TTS 无独立 Key，按约定复用 AGNES_LLM_API_KEY
        self._api_key = settings.AGNES_LLM_API_KEY or ""
        self._model = settings.AGNES_LLM_MODEL or "agnes-3.0-flash"
        self._mock = MockTTSProvider()
        self.last_degraded: bool = False

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        params: dict | None = None,
    ) -> str:
        """将文本合成为语音并返回音频 URL（失败自动降级 mock）。

        Args:
            text: 待合成的文本内容。
            voice_id: 音色 ID（OpenAI TTS 的 voice 参数）。
            params: 额外参数，支持 response_format（默认 mp3）、speed、model。

        Returns:
            str: 合成音频的访问 URL（真实落盘 /static/... URL 或 mock 占位 URL）。

        Raises:
            RuntimeError: 仅当降级 mock 也失败时向外抛出，交由上层任务重试。
        """
        # 未配置 API Key 时直接走 mock
        if not self._api_base or not self._api_key:
            logger.warning("[agnes-tts] 未配置 AGNES_BASE_URL/AGNES_LLM_API_KEY，降级 mock。")
            self.last_degraded = True
            return await self._mock.synthesize(text, voice_id, params)

        try:
            # 关键逻辑：委托真实 TTS 调用；404（网关暂不支持）也会在此被捕获降级
            return await self._synthesize_via_api(text, voice_id, params)
        except Exception as exc:  # noqa: BLE001
            # 降级约定：记录 error 日志后调用 mock 完成本次请求。
            # base 接口约定返回 str URL，降级结果无法内嵌 dict 标记，
            # 通过日志与 last_degraded 属性标识降级状态。
            logger.error(f"[agnes-tts] 真实合成失败（网关 404 = 暂不支持 TTS），降级 mock: {exc}")
            self.last_degraded = True
            return await self._mock.synthesize(text, voice_id, params)

    async def _synthesize_via_api(
        self,
        text: str,
        voice_id: str,
        params: dict | None,
    ) -> str:
        """调用 Agnes APIHub /audio/speech 完成真实合成。

        Args:
            text: 待合成文本。
            voice_id: 音色 ID。
            params: 额外参数（response_format/speed/model）。

        Returns:
            str: 音频落盘后的 /static/audio/... 访问 URL。

        Raises:
            RuntimeError: 404（端点不支持）或其他非 200 响应、空音频时抛出。
            httpx.HTTPError: 网络层异常向上透传。
        """
        p = params or {}
        # 组装 OpenAI TTS 请求体；model 默认复用 LLM 模型名（网关未提供独立 TTS 模型）
        body: dict = {
            "model": p.get("model", self._model),
            "voice": voice_id or "alloy",
            "input": text,
            "response_format": p.get("response_format", "mp3"),
        }
        if "speed" in p:
            body["speed"] = p["speed"]

        # 发起真实请求
        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{self._api_base}/audio/speech",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )

        # 404：网关暂不支持 TTS 端点——抛出"不支持"异常，由 synthesize 统一降级 mock
        if resp.status_code == 404:
            raise RuntimeError("Agnes TTS 端点不支持（/audio/speech 返回 404）")

        # 其他非 200 同样视为失败
        if resp.status_code != 200:
            raise RuntimeError(f"Agnes TTS API 返回 {resp.status_code}: {resp.text[:300]}")

        # 200 时应返回音频二进制；空内容视为异常
        audio_bytes = resp.content
        if not audio_bytes:
            raise RuntimeError("Agnes TTS API 返回空音频内容")

        # 保存到静态目录并返回访问 URL（与 mock 的 URL 落库格式一致）
        return save_artifact(audio_bytes, "audio", "mp3")
