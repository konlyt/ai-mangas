"""
语音合成 Mock Provider。

用于开发与测试环境，返回一个自托管的占位音频 URL，不产生真实调用费用。
"""

from app.providers.tts.base import TTSProvider


class MockTTSProvider(TTSProvider):
    """Mock 语音合成 Provider。

    直接返回一个公开可访问的占位音频 URL，模拟 TTS 合成结果。
    """

    # 占位音频：自托管于后端静态目录（/static 挂载，见 main.py 与 providers/storage.py），
    # 由项目 tools/ffmpeg.exe 的 anullsrc 源生成的 1 秒静音；改用外链会被对端 403 拒绝。
    # 注意：返回值不可追加 query 参数（如 mock_id），/static 前缀 URL 会被
    # fetch_url_to_file 按本地路径映射，追加 query 将导致文件定位失败
    PLACEHOLDER_AUDIO_URL = "/static/placeholders/placeholder_audio.mp3"

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        params: dict | None = None,
    ) -> str:
        """合成 mock 音频并返回 URL。

        Args:
            text: 待合成文本（mock 模式下仅作日志用途）。
            voice_id: 音色 ID（mock 模式下忽略）。
            params: 额外参数（mock 模式下忽略）。

        Returns:
            str: 占位音频 URL。
        """
        # /static 前缀 URL 会被 fetch_url_to_file 映射为本地静态文件复制，
        # 因此直接返回固定 URL，不追加 query 参数（会破坏本地路径映射）
        return self.PLACEHOLDER_AUDIO_URL
