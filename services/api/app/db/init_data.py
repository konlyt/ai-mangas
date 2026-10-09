"""
数据库初始化数据模块。

提供 init_default_data 函数，在应用启动时幂等地创建默认管理员用户
与全局模型配置（DeepSeek LLM）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import aes_encrypt, hash_password
from app.models import ModelConfig, ModelCapability, User


async def init_default_data(db_session: AsyncSession) -> None:
    """初始化默认数据（幂等）。

    - 创建管理员用户（username=admin，密码 123456，点数 10000）
    - 创建全局 LLM 模型配置（DeepSeek）

    Args:
        db_session: 异步数据库会话。

    Returns:
        None
    """
    # ---- 默认管理员用户 ----
    result = await db_session.execute(select(User).where(User.username == "admin"))
    admin_user = result.scalar_one_or_none()
    if admin_user is None:
        admin_user = User(
            username="admin",
            password_hash=hash_password("123456"),
            quota=10000,
            status=1,
        )
        db_session.add(admin_user)

    # ---- 全局默认 LLM 配置 ----
    result = await db_session.execute(
        select(ModelConfig).where(
            ModelConfig.user_id.is_(None),
            ModelConfig.project_id.is_(None),
            ModelConfig.capability == ModelCapability.LLM,
        )
    )
    global_llm = result.scalar_one_or_none()
    if global_llm is None:
        global_llm = ModelConfig(
            user_id=None,
            project_id=None,
            capability=ModelCapability.LLM,
            provider="deepseek",
            model_name=settings.DEEPSEEK_MODEL,
            api_key_encrypted=aes_encrypt(settings.DEEPSEEK_API_KEY) if settings.DEEPSEEK_API_KEY else None,
            api_base=settings.DEEPSEEK_BASE_URL,
        )
        db_session.add(global_llm)

    await db_session.commit()
