"""
模型中心领域服务。

提供模型列表查询、项目级模型配置、Key 连通性测试、
用户自有 Key 列表等业务逻辑。
"""

import time
from typing import Optional

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.response import BizException, ErrorCode
from app.core.security import aes_decrypt, aes_encrypt
from app.models import ModelCapability, ModelConfig, Project
from app.schemas.model import (
    ModelConfigCreate,
    ModelOut,
    VerifyKeyOut,
    VerifyKeyRequest,
)

def _get_default_api_base(provider: str) -> str:
    """根据 provider 返回默认 API 基础地址（从 .env settings 读取）。

    Args:
        provider: 厂商标识（小写）。

    Returns:
        str: 默认 API 地址，未配置时返回空字符串。
    """
    defaults = {
        "deepseek": settings.DEEPSEEK_BASE_URL,
        "openai": "https://api.openai.com/v1",
        "siliconflow": "https://api.siliconflow.cn",
        "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
        "agnes": settings.AGNES_BASE_URL,
        "zhipu": settings.ZHIPU_VIDEO_BASE_URL,
        "qianwen": settings.QIANWEN_TTS_API_BASE_URL,
    }
    return defaults.get(provider, "") or ""


# API 连通性测试超时时间（秒）
VERIFY_TIMEOUT = 10


async def list_models(
    db: AsyncSession, capability: Optional[ModelCapability] = None
) -> list:
    """查询可用模型列表。

    从 model_configs 表读取全局默认配置（user_id=NULL），
    与用户级配置合并返回（用户级覆盖全局）。

    Args:
        db: 异步数据库会话。
        capability: 能力类型过滤（可选）。

    Returns:
        list: 模型配置列表（ModelOut）。
    """
    conditions = [ModelConfig.project_id.is_(None)]
    if capability:
        conditions.append(ModelConfig.capability == capability)

    result = await db.execute(
        select(ModelConfig).where(and_(*conditions)).order_by(ModelConfig.capability)
    )
    configs = result.scalars().all()

    models = []
    for cfg in configs:
        # 判断作用域
        if cfg.user_id is None:
            scope = "global"
        else:
            scope = "user"
        models.append(
            ModelOut(
                id=cfg.id,
                capability=cfg.capability,
                provider=cfg.provider,
                model_name=cfg.model_name,
                api_base=cfg.api_base,
                price_meta=cfg.price_meta,
                scope=scope,
            )
        )
    return models


async def set_project_config(
    db: AsyncSession, project_id: int, user_id: int, req: ModelConfigCreate
) -> ModelOut:
    """设置项目级模型配置。

    若项目已存在相同 capability 的配置则更新，否则新建。
    api_key 若提供则加密存储。

    Args:
        db: 异步数据库会话。
        project_id: 项目ID。
        user_id: 用户ID（用于校验项目归属）。
        req: 模型配置请求体。

    Returns:
        ModelOut: 保存后的模型配置。

    Raises:
        BizException: 项目不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    # 校验项目归属
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 查找是否已存在该项目该能力的配置
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.project_id == project_id,
            ModelConfig.capability == req.capability,
        )
    )
    cfg = result.scalar_one_or_none()

    encrypted_key = None
    if req.api_key:
        encrypted_key = aes_encrypt(req.api_key)

    if cfg is None:
        # 新建
        cfg = ModelConfig(
            user_id=user_id,
            project_id=project_id,
            capability=req.capability,
            provider=req.provider,
            model_name=req.model_name,
            api_key_encrypted=encrypted_key,
            api_base=req.api_base,
            params=req.params,
            price_meta=req.price_meta,
        )
        db.add(cfg)
    else:
        # 更新
        cfg.provider = req.provider
        cfg.model_name = req.model_name
        cfg.api_base = req.api_base
        cfg.params = req.params
        cfg.price_meta = req.price_meta
        if encrypted_key is not None:
            cfg.api_key_encrypted = encrypted_key

    await db.commit()
    await db.refresh(cfg)

    return ModelOut(
        id=cfg.id,
        capability=cfg.capability,
        provider=cfg.provider,
        model_name=cfg.model_name,
        api_base=cfg.api_base,
        price_meta=cfg.price_meta,
        scope="project",
    )


async def verify_key(req: VerifyKeyRequest) -> VerifyKeyOut:
    """测试 API Key 连通性。

    根据 provider 选择对应测试端点，使用 httpx 发起请求，
    返回是否有效、耗时与可用模型列表。

    Args:
        req: Key 测试请求体。

    Returns:
        VerifyKeyOut: 测试结果。
    """
    provider = req.provider.lower()
    api_base = req.api_base or _get_default_api_base(provider)

    if not api_base:
        return VerifyKeyOut(valid=False, latency_ms=0, models=[])

    # 确保 api_base 不以 / 结尾
    api_base = api_base.rstrip("/")

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            if provider == "deepseek":
                # DeepSeek: 调用 chat/completions 最小请求
                url = f"{api_base}/chat/completions"
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {req.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": req.model_name,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                )
                latency_ms = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    models = []
                    model_id = data.get("model")
                    if model_id:
                        models.append(model_id)
                    return VerifyKeyOut(valid=True, latency_ms=latency_ms, models=models)
                else:
                    return VerifyKeyOut(valid=False, latency_ms=latency_ms, models=[])
            else:
                # 通用：尝试调用 /models 列表接口（OpenAI 兼容协议）
                if "/v1" in api_base:
                    url = f"{api_base}/models"
                else:
                    url = f"{api_base}/v1/models"

                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {req.api_key}"},
                )
                latency_ms = int((time.time() - start) * 1000)

                # 401/403 = Key 无效（网关先鉴权，Key 错会直接拒绝）
                if resp.status_code in (401, 403):
                    return VerifyKeyOut(valid=False, latency_ms=latency_ms, models=[])

                # 200 = 正常返回模型列表
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        model_list = data.get("data", [])
                        models = [m.get("id", "") for m in model_list if isinstance(m, dict)]
                    except Exception:
                        models = []
                    return VerifyKeyOut(valid=True, latency_ms=latency_ms, models=models)

                # 其他 4xx（400/404/422）：Key 被网关接受（否则会先返回 401），
                # 只是路径或参数不匹配，视为连通正常。
                # 5xx 服务器故障：无法确认，视为无效。
                if 400 <= resp.status_code < 500:
                    return VerifyKeyOut(valid=True, latency_ms=latency_ms, models=[])

                return VerifyKeyOut(valid=False, latency_ms=latency_ms, models=[])
    except Exception:
        latency_ms = int((time.time() - start) * 1000)
        return VerifyKeyOut(valid=False, latency_ms=latency_ms, models=[])


async def list_my_keys(db: AsyncSession, user_id: int) -> list:
    """查询用户自有 Key 列表（掩码显示）。

    返回用户级（project_id=NULL）的模型配置，api_key 做掩码处理。

    Args:
        db: 异步数据库会话。
        user_id: 用户ID。

    Returns:
        list: 用户 Key 配置列表（含掩码后的 key）。
    """
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.project_id.is_(None),
        )
    )
    configs = result.scalars().all()

    keys = []
    for cfg in configs:
        masked_key = None
        if cfg.api_key_encrypted:
            try:
                raw = aes_decrypt(cfg.api_key_encrypted)
                if len(raw) > 8:
                    masked_key = raw[:4] + "****" + raw[-4:]
                else:
                    masked_key = "****"
            except Exception:
                masked_key = "****"

        keys.append(
            {
                "id": cfg.id,
                "capability": cfg.capability.value if hasattr(cfg.capability, "value") else str(cfg.capability),
                "provider": cfg.provider,
                "model_name": cfg.model_name,
                "api_base": cfg.api_base,
                "api_key_masked": masked_key,
                "params": cfg.params,
                "price_meta": cfg.price_meta,
            }
        )
    return keys


# ============================================================
# 用户 API Key 管理（复用 model_configs 表，user_id 级 + project_id 为空）
# ============================================================

# 前端中文能力名 -> ModelCapability 枚举值 映射
CAPABILITY_TO_ENUM = {
    "文本": ModelCapability.LLM,
    "图像": ModelCapability.IMAGE,
    "视频": ModelCapability.VIDEO,
    "语音": ModelCapability.TTS,
}


def _parse_capability(capability: str) -> ModelCapability:
    """将前端中文能力名转换为 ModelCapability 枚举。

    Args:
        capability: 能力类型（文本 / 图像 / 视频 / 语音）。

    Returns:
        ModelCapability: 对应的枚举值。

    Raises:
        BizException: 能力类型不合法时抛出 PARAM_ERROR。
    """
    enum_value = CAPABILITY_TO_ENUM.get(capability)
    if enum_value is None:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="能力类型不合法")
    return enum_value


def _mask_key(encrypted: str | None) -> str:
    """将 AES 加密的 Key 解密后做掩码处理。

    Args:
        encrypted: AES 加密后的 Key 密文。

    Returns:
        str: 掩码形式（前4位 + **** + 后4位），解密失败或过短时返回纯星号。
    """
    if not encrypted:
        return "****"
    try:
        raw = aes_decrypt(encrypted)
        if len(raw) > 8:
            return raw[:4] + "****" + raw[-4:]
        return "****"
    except Exception:
        return "****"


def _mask_key_from_raw(raw_key: str) -> str:
    """将明文 Key 做掩码处理（前4位 + **** + 后4位）。

    Args:
        raw_key: 明文 Key。

    Returns:
        str: 掩码后的 Key。
    """
    if not raw_key:
        return "****"
    if len(raw_key) > 8:
        return raw_key[:4] + "****" + raw_key[-4:]
    return "****"


def _get_builtin_keys() -> list[dict]:
    """从 .env 配置中读取系统内置 API Key 列表（掩码显示）。

    Returns:
        list[dict]: 内置 Key 列表，每项含 id/provider/capability/masked_key/verified/created_at/builtin。
    """
    keys = []
    next_id = -1000

    # DeepSeek 文本
    if settings.DEEPSEEK_API_KEY:
        keys.append({
            "id": next_id,
            "provider": "deepseek",
            "capability": "文本",
            "masked_key": _mask_key_from_raw(settings.DEEPSEEK_API_KEY),
            "verified": False,
            "created_at": "",
            "builtin": True,
        })
        next_id += 1

    # Agnes 文本
    if settings.AGNES_LLM_API_KEY:
        keys.append({
            "id": next_id,
            "provider": "agnes",
            "capability": "文本",
            "masked_key": _mask_key_from_raw(settings.AGNES_LLM_API_KEY),
            "verified": False,
            "created_at": "",
            "builtin": True,
        })
        next_id += 1

    # Agnes 图像
    if settings.AGNES_IMAGE_API_KEY:
        keys.append({
            "id": next_id,
            "provider": "agnes",
            "capability": "图像",
            "masked_key": _mask_key_from_raw(settings.AGNES_IMAGE_API_KEY),
            "verified": False,
            "created_at": "",
            "builtin": True,
        })
        next_id += 1

    # Agnes 视频
    if settings.AGNES_VIDEO_API_KEY:
        keys.append({
            "id": next_id,
            "provider": "agnes",
            "capability": "视频",
            "masked_key": _mask_key_from_raw(settings.AGNES_VIDEO_API_KEY),
            "verified": False,
            "created_at": "",
            "builtin": True,
        })
        next_id += 1

    # 智谱视频
    if settings.ZHIPU_VIDEO_API_KEY:
        keys.append({
            "id": next_id,
            "provider": "zhipu",
            "capability": "视频",
            "masked_key": _mask_key_from_raw(settings.ZHIPU_VIDEO_API_KEY),
            "verified": False,
            "created_at": "",
            "builtin": True,
        })
        next_id += 1

    # 通义千问语音
    if settings.QIANWEN_TTS_API_KEY:
        keys.append({
            "id": next_id,
            "provider": "qianwen",
            "capability": "语音",
            "masked_key": _mask_key_from_raw(settings.QIANWEN_TTS_API_KEY),
            "verified": False,
            "created_at": "",
            "builtin": True,
        })
        next_id += 1

    return keys


def _get_builtin_credential(provider: str, capability: str) -> tuple[str, str, str]:
    """从 .env settings 读取指定内置 Key 的明文凭证。

    Args:
        provider: 厂商标识（如 agnes / zhipu / qianwen）。
        capability: 能力中文名（文本 / 图像 / 视频 / 语音）。

    Returns:
        tuple: (api_key, api_base, model_name)，未配置时对应位置为空字符串。
    """
    p = provider.lower()
    if p == "deepseek" and capability == "文本":
        return settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_BASE_URL, settings.DEEPSEEK_MODEL or "deepseek-flash"
    if p == "agnes" and capability == "文本":
        return settings.AGNES_LLM_API_KEY, settings.AGNES_BASE_URL, settings.AGNES_LLM_MODEL or "agnes-3.0-flash"
    if p == "agnes" and capability == "图像":
        return settings.AGNES_IMAGE_API_KEY, settings.AGNES_BASE_URL, settings.AGNES_IMAGE_MODEL or "agnes-image-2.5-flash"
    if p == "agnes" and capability == "视频":
        return settings.AGNES_VIDEO_API_KEY, settings.AGNES_VIDEO_BASE_URL, settings.AGNES_VIDEO_MODEL or "agnes-video-2.5-flash"
    if p == "zhipu" and capability == "视频":
        return settings.ZHIPU_VIDEO_API_KEY, settings.ZHIPU_VIDEO_BASE_URL, settings.ZHIPU_VIDEO_MODEL or "cogvideox-3"
    if p == "qianwen" and capability == "语音":
        return settings.QIANWEN_TTS_API_KEY, settings.QIANWEN_TTS_API_BASE_URL, settings.QIANWEN_TTS_MODEL or "qwen3-tts-instruct-flash"
    return "", "", ""


async def list_user_keys(db: AsyncSession, user_id: int) -> list[dict]:
    """查询当前用户的 API Key 列表（掩码显示）。

    返回用户级（user_id 匹配且 project_id 为空）的 Key 配置，
    合并 .env 配置的系统内置 Key（标记为 builtin，不可删除）。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。

    Returns:
        list[dict]: Key 列表，每项含 id/provider/capability/masked_key/verified/created_at/builtin。
    """
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.project_id.is_(None),
        ).order_by(ModelConfig.id.desc())
    )
    configs = result.scalars().all()

    items = [
        {
            "id": cfg.id,
            "provider": cfg.provider,
            "capability": _capability_to_cn(cfg.capability),
            "masked_key": _mask_key(cfg.api_key_encrypted),
            "verified": bool((cfg.params or {}).get("verified", False)),
            "created_at": cfg.created_at.isoformat() if cfg.created_at else "",
            "builtin": False,
        }
        for cfg in configs
    ]

    # 合并 .env 配置的系统内置 Key（用户已配置的优先，不重复添加）
    builtin_keys = _get_builtin_keys()
    existing = {(k["provider"], k["capability"]) for k in items}
    for bk in builtin_keys:
        if (bk["provider"], bk["capability"]) not in existing:
            items.append(bk)

    return items


def _capability_to_cn(capability: ModelCapability) -> str:
    """将 ModelCapability 枚举转换为前端中文能力名。

    Args:
        capability: 能力枚举值。

    Returns:
        str: 中文能力名（文本 / 图像 / 视频 / 语音）。
    """
    reverse = {v: k for k, v in CAPABILITY_TO_ENUM.items()}
    return reverse.get(capability, str(capability.value))


async def create_user_key(
    db: AsyncSession, user_id: int, provider: str, capability: str, api_key: str
) -> dict:
    """为当前用户创建一条 API Key 记录。

    Key 明文经 AES-256 加密后存入 model_configs 表，
    同一用户同一厂商同一能力仅保留一条，重复添加时覆盖原 Key。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。
        provider: 厂商标识。
        capability: 能力类型（文本 / 图像 / 视频 / 语音）。
        api_key: API Key 明文。

    Returns:
        dict: 创建后的 Key 记录（掩码显示）。

    Raises:
        BizException: 能力类型不合法时抛出 PARAM_ERROR。
    """
    cap_enum = _parse_capability(capability)

    # 同厂商同能力已存在则覆盖，避免重复记录
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.project_id.is_(None),
            ModelConfig.provider == provider,
            ModelConfig.capability == cap_enum,
        )
    )
    cfg = result.scalars().first()
    if cfg is None:
        cfg = ModelConfig(
            user_id=user_id,
            project_id=None,
            capability=cap_enum,
            provider=provider,
            model_name="user-key",
            api_key_encrypted=aes_encrypt(api_key),
        )
        db.add(cfg)
    else:
        cfg.api_key_encrypted = aes_encrypt(api_key)
        cfg.params = None  # 重置验证状态

    await db.commit()
    await db.refresh(cfg)
    return {
        "id": cfg.id,
        "provider": cfg.provider,
        "capability": capability,
        "masked_key": _mask_key(cfg.api_key_encrypted),
        "verified": False,
        "created_at": cfg.created_at.isoformat() if cfg.created_at else "",
    }


async def update_user_key(
    db: AsyncSession,
    user_id: int,
    key_id: int,
    provider: str,
    capability: str,
    api_key: str | None = None,
) -> dict:
    """更新当前用户的指定 API Key。

    仅允许修改本人 Key；api_key 为空（None 或空白字符串）时保留原 Key。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。
        key_id: Key 记录 ID。
        provider: 厂商标识。
        capability: 能力类型（文本 / 图像 / 视频 / 语音）。
        api_key: 新的 API Key 明文，可选。

    Returns:
        dict: 更新后的 Key 记录（掩码显示）。

    Raises:
        BizException: Key 不存在、不属于当前用户或能力类型不合法时抛出。
    """
    cap_enum = _parse_capability(capability)

    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.id == key_id,
            ModelConfig.user_id == user_id,
            ModelConfig.project_id.is_(None),
        )
    )
    cfg = result.scalars().first()
    if cfg is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="API Key 不存在")

    cfg.provider = provider
    cfg.capability = cap_enum
    if api_key and api_key.strip():
        cfg.api_key_encrypted = aes_encrypt(api_key.strip())
        cfg.params = None  # Key 变更后重置验证状态

    await db.commit()
    await db.refresh(cfg)
    return {
        "id": cfg.id,
        "provider": cfg.provider,
        "capability": capability,
        "masked_key": _mask_key(cfg.api_key_encrypted),
        "verified": bool((cfg.params or {}).get("verified", False)),
        "created_at": cfg.created_at.isoformat() if cfg.created_at else "",
    }


async def delete_user_key(db: AsyncSession, user_id: int, key_id: int) -> None:
    """删除当前用户的指定 API Key。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。
        key_id: Key 记录 ID。

    Raises:
        BizException: Key 不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.id == key_id,
            ModelConfig.user_id == user_id,
            ModelConfig.project_id.is_(None),
        )
    )
    cfg = result.scalars().first()
    if cfg is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="API Key 不存在")

    await db.delete(cfg)
    await db.commit()


async def verify_user_key(db: AsyncSession, user_id: int, key_id: int) -> VerifyKeyOut:
    """测试当前用户存储的指定 API Key 连通性。

    后端解密存储的真实 Key 后复用 verify_key 逻辑发起测试，
    避免前端传递掩码 Key 导致测试必然失败，
    并将验证结果持久化到 params.verified 供列表展示。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。
        key_id: Key 记录 ID（负数表示系统内置 Key，从 .env 读取）。

    Returns:
        VerifyKeyOut: 测试结果（是否有效、耗时、可用模型）。

    Raises:
        BizException: Key 不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    # 系统内置 Key（负数 ID）：不查数据库，直接从 .env 读取凭证测试
    if key_id < 0:
        builtin_keys = _get_builtin_keys()
        match = next((k for k in builtin_keys if k["id"] == key_id), None)
        if match is None:
            raise BizException(code=ErrorCode.NOT_FOUND, message="API Key 不存在")
        provider = match["provider"]
        capability = match["capability"]
        api_key, api_base, model_name = _get_builtin_credential(provider, capability)
        if not api_key:
            return VerifyKeyOut(valid=False, latency_ms=0, models=[])
        req = VerifyKeyRequest(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
        )
        return await verify_key(req)

    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.id == key_id,
            ModelConfig.user_id == user_id,
            ModelConfig.project_id.is_(None),
        )
    )
    cfg = result.scalars().first()
    if cfg is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="API Key 不存在")

    # 解密明文 Key，解密失败视为 Key 数据损坏，直接返回无效
    try:
        raw_key = aes_decrypt(cfg.api_key_encrypted) if cfg.api_key_encrypted else ""
    except Exception:
        raw_key = ""
    if not raw_key:
        return VerifyKeyOut(valid=False, latency_ms=0, models=[])

    # 用户 Key 未绑定具体模型：DeepSeek 走 chat 校验需指定可用模型名，其余走通用 /models 校验
    model_name = cfg.model_name
    if not model_name or model_name == "user-key":
        model_name = settings.DEEPSEEK_MODEL or "deepseek-flash"

    req = VerifyKeyRequest(
        provider=cfg.provider,
        model_name=model_name,
        api_key=raw_key,
        api_base=cfg.api_base,
    )
    verify_result = await verify_key(req)

    # 将验证结果持久化，前端列表据此展示"已验证/未验证"
    params = dict(cfg.params or {})
    params["verified"] = verify_result.valid
    cfg.params = params
    await db.commit()

    return verify_result


# ============================================================
# 面向前端"模型配置抽屉"的模型列表与项目选型
# ============================================================

# 各厂商默认展示模型名（用户 Key 记录未绑定具体模型时使用）
# DeepSeek 使用 .env 中运维配置的 DEEPSEEK_MODEL，避免硬编码的旧模型名已下线
PROVIDER_DEFAULT_MODELS = {
    "deepseek": settings.DEEPSEEK_MODEL or "deepseek-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet",
    "qwen": "qwen-plus",
    "moonshot": "moonshot-v1-8k",
    "stability": "stable-image-core",
    "midjourney": "midjourney-v6",
    "runway": "gen3-alpha-turbo",
    "kling": "kling-v1",
    "sambert": "sambert-zhichu",
    "fishaudio": "fish-speech-1.5",
}

# 后端能力枚举值 -> 前端 Model.type 映射
CAPABILITY_TO_FRONTEND_TYPE = {
    "llm": "llm",
    "image": "image",
    "video": "video",
    "tts": "audio",
}


def _resolve_model_name(provider: str, model_name: str | None) -> str:
    """解析模型的展示名。

    用户 Key 记录（model_name 为空或 "user-key"）使用厂商默认模型名。

    Args:
        provider: 厂商标识。
        model_name: 配置中的模型名。

    Returns:
        str: 用于展示与项目配置的实际模型名。
    """
    if not model_name or model_name == "user-key":
        return PROVIDER_DEFAULT_MODELS.get(provider.lower(), f"{provider}-default")
    return model_name


async def list_models_for_user(
    db: AsyncSession, user_id: int, project_id: int | None = None
) -> list[dict]:
    """查询当前用户可见的模型列表（前端 Model 结构）。

    合并全局默认配置与用户自有 Key 配置；按项目级配置标记当前默认模型；
    按已存储的 Key 标记各厂商是否已配置。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。
        project_id: 项目 ID（可选，用于标记 is_default）。

    Returns:
        list[dict]: 模型列表，每项含
            id/name/provider/type/is_default/key_configured。
    """
    # 全局默认（user_id 为空）+ 用户自有配置（排除项目级记录）
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.project_id.is_(None),
            or_(ModelConfig.user_id.is_(None), ModelConfig.user_id == user_id),
        ).order_by(ModelConfig.id)
    )
    configs = result.scalars().all()

    # 用户可见的已配 Key 厂商集合（用户级有 Key 的 + 全局带 Key 的）
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.project_id.is_(None),
            ModelConfig.api_key_encrypted.isnot(None),
            or_(ModelConfig.user_id.is_(None), ModelConfig.user_id == user_id),
        )
    )
    keyed_providers = {c.provider.lower() for c in result.scalars().all()}

    # 项目当前默认模型（capability, provider, model_name）集合
    project_keys: set = set()
    if project_id:
        result = await db.execute(
            select(ModelConfig).where(ModelConfig.project_id == project_id)
        )
        project_keys = {
            (c.capability, c.provider, c.model_name) for c in result.scalars().all()
        }

    items = []
    for cfg in configs:
        name = _resolve_model_name(cfg.provider, cfg.model_name)
        items.append(
            {
                "id": cfg.id,
                "name": name,
                "provider": cfg.provider,
                "type": CAPABILITY_TO_FRONTEND_TYPE.get(
                    cfg.capability.value, cfg.capability.value
                ),
                "is_default": (cfg.capability, cfg.provider, name) in project_keys,
                "key_configured": cfg.provider.lower() in keyed_providers,
            }
        )
    return items


async def select_project_model(
    db: AsyncSession, user_id: int, project_id: int, model_id: int
) -> dict:
    """为项目选择模型（写入项目级配置）。

    根据候选模型 ID 读取其能力/厂商/模型名，更新或创建项目级配置；
    用户 Key 记录会解析为厂商默认模型名落库。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID（用于校验项目归属）。
        project_id: 项目 ID。
        model_id: 候选模型记录 ID。

    Returns:
        dict: 选择结果（model_id/capability/provider/model_name）。

    Raises:
        BizException: 项目或模型不存在、不归属当前用户时抛出 NOT_FOUND。
    """
    # 校验项目归属
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 查询候选模型（全局默认或用户自有，排除项目级记录）
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.id == model_id,
            ModelConfig.project_id.is_(None),
            or_(ModelConfig.user_id.is_(None), ModelConfig.user_id == user_id),
        )
    )
    cfg = result.scalars().first()
    if cfg is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="模型不存在")

    model_name = _resolve_model_name(cfg.provider, cfg.model_name)

    # 更新或创建项目级配置（同能力仅保留一条）
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.project_id == project_id,
            ModelConfig.capability == cfg.capability,
        )
    )
    pcfg = result.scalars().first()
    if pcfg is None:
        pcfg = ModelConfig(
            user_id=user_id,
            project_id=project_id,
            capability=cfg.capability,
            provider=cfg.provider,
            model_name=model_name,
            api_key_encrypted=cfg.api_key_encrypted,
            api_base=cfg.api_base,
        )
        db.add(pcfg)
    else:
        pcfg.provider = cfg.provider
        pcfg.model_name = model_name
        pcfg.api_base = cfg.api_base
        if cfg.api_key_encrypted:
            pcfg.api_key_encrypted = cfg.api_key_encrypted

    await db.commit()
    await db.refresh(pcfg)

    return {
        "model_id": pcfg.id,
        "capability": CAPABILITY_TO_FRONTEND_TYPE.get(
            cfg.capability.value, cfg.capability.value
        ),
        "provider": cfg.provider,
        "model_name": model_name,
    }
