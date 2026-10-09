"""
应用配置模块。

通过 pydantic-settings 从项目根目录的 .env 文件加载环境变量，
提供全局 settings 单例以及数据库、Redis 连接串构造函数。
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


# .env 位于项目根目录，相对本文件（services/api/app/core/config.py）向上四级
ENV_FILE_PATH: Path = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    """全局应用配置。

    从项目根目录 .env 文件读取环境变量，支持类型转换与默认值。
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ---- MySQL ----
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "123456"
    MYSQL_DATABASE: str = "AnimeWorld"

    # ---- Redis ----
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0

    # ---- JWT ----
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ---- AES ----
    AES_SECRET_KEY: str = "0123456789abcdef0123456789abcdef"

    # ---- DeepSeek ----
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-flash"

    # ---- LLM 调用策略 ----
    # 真实模型调用失败时是否允许降级返回 mock 占位文案。
    # 默认 False：宁可向上抛出明确的错误，也不返回与用户输入无关的假内容。
    LLM_ALLOW_MOCK_FALLBACK: bool = False
    # litellm 调用失败时，是否改用直连 OpenAI 兼容 /v1/chat/completions 重试一次。
    # DeepSeek / Agnes 等网关均为 OpenAI 兼容协议，该兜底可规避 litellm 侧的
    # 厂商识别（Provider 前缀）与参数兼容问题。
    LLM_ENABLE_HTTP_FALLBACK: bool = True

    # ---- Agnes AI（OpenAI 兼容网关：文本/图像/视频/TTS）----
    AGNES_BASE_URL: str = ""
    AGNES_LLM_API_KEY: str = ""
    AGNES_LLM_MODEL: str = ""
    AGNES_IMAGE_API_KEY: str = ""
    AGNES_IMAGE_MODEL: str = ""
    AGNES_VIDEO_API_KEY: str = ""
    AGNES_VIDEO_MODEL: str = ""
    # 视频服务独立域名（创建/查询走 api.agnes-ai.cn，与文本/图像的 apihub 不同）
    AGNES_VIDEO_BASE_URL: str = ""

    # ---- 通义千问 TTS（DashScope）----
    QIANWEN_TTS_API_BASE_URL: str = "https://dashscope.aliyuncs.com"
    QIANWEN_TTS_API_KEY: str = ""
    QIANWEN_TTS_MODEL: str = "qwen3-tts-instruct-flash"
    QIANWEN_TTS_API_PATH: str = "/api/v1/services/aigc/multimodal-generation/generation"
    QIANWEN_TTS_TIMEOUT_MS: int = 120000
    QIANWEN_TTS_MAX_RETRIES: int = 0
    QIANWEN_TTS_ALLOW_DEMO_FALLBACK: bool = False

    # ---- API ----
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # ---- 运行环境 ----
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    def get_database_url(self) -> str:
        """构造 asyncmy 异步 MySQL 连接串。

        Returns:
            str: 形如 mysql+asyncmy://user:pwd@host:port/db?charset=utf8mb4
        """
        return (
            f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    def get_redis_url(self) -> str:
        """构造 Redis 连接串。

        Returns:
            str: 形如 redis://[:password@]host:port/db
        """
        if self.REDIS_PASSWORD:
            return (
                f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            )
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


# 全局单例
settings = Settings()
