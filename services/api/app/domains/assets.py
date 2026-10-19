"""
资产领域服务。

提供角色生成、查询、锁定、变体重生成，场景生成与查询，以及一致性报告查询。
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import (
    AssetOwnerType,
    AssetVariant,
    AssetVariantStatus,
    Character,
    ConsistencyAction,
    ConsistencyReport,
    ConsistencySubjectType,
    Project,
    Scene,
    Script,
)
from app.providers.image.registry import get_image_registry
from app.providers.storage import save_artifact
from app.schemas.asset import (
    AssetVariantOut,
    CharacterGenerateRequest,
    CharacterLockRequest,
    CharacterOut,
    SceneOut,
)

logger = get_logger()

# 角色定妆照的三种角度
CHARACTER_VARIANT_TYPES = ["front", "side", "half"]

# 角色参考图对应的变体类型（复用 asset_variants 表存储，无需新增列）
REFERENCE_VARIANT_TYPE = "reference"

# 允许上传的参考图 content type -> 文件扩展名映射
ALLOWED_REFERENCE_TYPES: Dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# 参考图大小上限：5MB
REFERENCE_MAX_SIZE = 5 * 1024 * 1024


def _get_image_provider(name: Optional[str] = None):
    """获取图像生成 Provider 实例。

    兼容两种 registry 接口：优先使用 get_image_provider，
    不可用时回退到 get_image_registry().get_provider()。

    Args:
        name: Provider 名称，为空时使用默认。

    Returns:
        ImageProvider: 图像生成 Provider 实例。
    """
    try:
        # 尝试直接导入便捷函数（若 registry 后续补充）
        from app.providers.image.registry import get_image_provider  # type: ignore

        return get_image_provider(name)
    except Exception:
        return get_image_registry().get_provider(name)


def _build_character_out(character: Character, variants: List[AssetVariant]) -> CharacterOut:
    """将角色及其变体构造为输出模型，并提取参考图 URL。

    参考图以 variant_type="reference" 的变体记录存储，
    构造输出时会将其从常规角度变体列表中剔除，单独写入 reference_url 字段。

    Args:
        character: 角色 ORM 对象。
        variants: 该角色的资产变体列表。

    Returns:
        CharacterOut: 角色输出模型（含 variants 与 reference_url）。
    """
    out = CharacterOut.model_validate(character)
    # 提取参考图变体（上传的参考图）
    ref = next(
        (v for v in variants if v.variant_type == REFERENCE_VARIANT_TYPE),
        None,
    )
    out.reference_url = ref.image_url if ref else None
    # 常规角度变体（剔除 reference 类型，避免混入多角度列表）
    out.variants = [
        AssetVariantOut.model_validate(v)
        for v in variants
        if v.variant_type != REFERENCE_VARIANT_TYPE
    ]
    return out


def _extract_characters_from_script(content: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从结构化剧本中提取角色列表。

    Args:
        content: 剧本 content 字典。

    Returns:
        List[Dict]: 角色描述列表，每项包含 name / description / visual_prompt。
    """
    characters = content.get("characters", []) if isinstance(content, dict) else []
    result = []
    for ch in characters:
        if isinstance(ch, dict):
            name = ch.get("name") or ch.get("角色名")
            if not name:
                continue
            description = ch.get("description") or ch.get("描述") or ""
            # 整合外貌、服饰、性格等特征构建完整视觉提示词
            appearance = ch.get("appearance") or ch.get("外貌") or ""
            personality = ch.get("personality") or ch.get("性格") or ""
            age = ch.get("age") or ""
            gender = ch.get("gender") or ""

            # 按优先级组合视觉描述，确保包含足够的特征细节
            visual_prompt_parts = []
            if appearance:
                visual_prompt_parts.append(appearance)
            if description:
                visual_prompt_parts.append(description)
            if personality:
                visual_prompt_parts.append(f"气质{personality}")
            if age and gender:
                visual_prompt_parts.append(f"{gender}性，{age}岁")

            visual_prompt = ch.get("visual_prompt") or ch.get("提示词") or "，".join(visual_prompt_parts) or name
            result.append(
                {
                    "name": name,
                    "description": description,
                    "visual_prompt": visual_prompt,
                }
            )
    return result


async def generate_characters(
    db: AsyncSession, project_id: int, req: Optional[CharacterGenerateRequest] = None
) -> List[CharacterOut]:
    """从剧本提取角色并批量生成三角度定妆照。

    为每个角色生成 front / side / half 三种角度的定妆照，
    写入 characters 与 asset_variants 表。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 角色生成请求体（可空）。

    Returns:
        List[CharacterOut]: 生成的角色列表（含变体）。

    Raises:
        BizException: 项目或剧本不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    result = await db.execute(
        select(Script)
        .where(Script.project_id == project_id)
        .order_by(desc(Script.version), desc(Script.id))
    )
    script = result.scalars().first()
    if script is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="剧本不存在，请先生成剧本")

    # 提取角色
    char_list = _extract_characters_from_script(script.content)
    if not char_list:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="剧本中未找到角色信息")

    # 若指定了 names，则过滤
    if req and req.names:
        name_set = set(req.names)
        char_list = [c for c in char_list if c["name"] in name_set]

    provider = _get_image_provider()
    created_characters: List[Character] = []
    created_variants_map: dict[int, List[AssetVariant]] = {}

    for char_info in char_list:
        # 创建角色记录
        character = Character(
            project_id=project_id,
            name=char_info["name"],
            description=char_info.get("description"),
            visual_prompt=char_info.get("visual_prompt") or char_info["name"],
        )
        db.add(character)
        await db.flush()  # 获取 character.id

        variants: List[AssetVariant] = []
        for vtype in CHARACTER_VARIANT_TYPES:
            prompt = f"{character.visual_prompt}，{vtype} 视图，动漫风格"
            try:
                image_url = await provider.generate(prompt)
                status = AssetVariantStatus.DONE
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[assets] 角色 {character.name} {vtype} 生成失败: {exc}")
                image_url = None
                status = AssetVariantStatus.FAILED

            variant = AssetVariant(
                owner_type=AssetOwnerType.CHARACTER,
                owner_id=character.id,
                variant_type=vtype,
                image_url=image_url,
                visual_prompt=prompt,
                status=status,
            )
            db.add(variant)
            variants.append(variant)

        # 主定妆照取 front 角度
        front = next((v for v in variants if v.variant_type == "front"), None)
        if front and front.image_url:
            character.main_asset_url = front.image_url

        created_characters.append(character)
        created_variants_map[character.id] = variants

    await db.commit()

    # 资产生成后自动触发一致性校验（CON-03）：为每个角色创建一致性报告
    # 当前特征向量为 mock 占位，相似度固定为 1.0 标记通过；
    # 待真实特征向量提取接入后，此处替换为实际相似度计算
    for character in created_characters:
        variants = created_variants_map.get(character.id, [])
        front_variant = next((v for v in variants if v.variant_type == "front" and v.status == AssetVariantStatus.DONE), None)
        if front_variant:
            report = ConsistencyReport(
                project_id=project_id,
                subject_type=ConsistencySubjectType.ASSET,
                subject_id=character.id,
                ref_asset_id=front_variant.id,
                similarity_score=1.0,  # mock：特征向量提取接入后替换为实际值
                threshold=0.85,
                action=ConsistencyAction.PASS,
            )
            db.add(report)
    await db.commit()

    # commit 后刷新并构造输出
    output: List[CharacterOut] = []
    for character in created_characters:
        await db.refresh(character)
        variants = created_variants_map.get(character.id, [])
        for v in variants:
            await db.refresh(v)
        output.append(_build_character_out(character, variants))

    return output


async def get_characters(db: AsyncSession, project_id: int) -> List[CharacterOut]:
    """查询项目下的所有角色及其变体。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        List[CharacterOut]: 角色列表（含变体）。
    """
    result = await db.execute(
        select(Character).where(Character.project_id == project_id)
    )
    characters = result.scalars().all()

    output: List[CharacterOut] = []
    for ch in characters:
        var_result = await db.execute(
            select(AssetVariant).where(
                AssetVariant.owner_type == AssetOwnerType.CHARACTER,
                AssetVariant.owner_id == ch.id,
            )
        )
        variants = var_result.scalars().all()
        output.append(_build_character_out(ch, variants))
    return output


async def lock_character(
    db: AsyncSession,
    project_id: int,
    character_id: int,
    req: Optional[CharacterLockRequest] = None,
) -> CharacterOut:
    """锁定角色，提取特征向量。

    将角色标记为已锁定，将主定妆照的变体标记为 done，并生成占位特征向量。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        character_id: 角色 ID。
        req: 角色锁定请求体（可空）。

    Returns:
        CharacterOut: 锁定后的角色信息。

    Raises:
        BizException: 角色不存在时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Character).where(
            Character.id == character_id, Character.project_id == project_id
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="角色不存在")

    character.is_locked = 1

    # 若指定了主变体，则更新主定妆照 URL
    if req and req.main_variant_id:
        var = await db.get(AssetVariant, req.main_variant_id)
        if var and var.image_url:
            character.main_asset_url = var.image_url

    # 为所有 done 的变体生成占位特征向量（mock：随机向量）
    var_result = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character.id,
        )
    )
    for v in var_result.scalars().all():
        if v.status == AssetVariantStatus.DONE and v.feature_vector is None:
            v.feature_vector = [0.0] * 16  # mock 特征向量

    await db.commit()
    await db.refresh(character)

    var_result2 = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character.id,
        )
    )
    return _build_character_out(character, list(var_result2.scalars().all()))


async def unlock_character(
    db: AsyncSession,
    project_id: int,
    character_id: int,
) -> CharacterOut:
    """解锁角色，允许重新生成。

    将角色标记为未锁定，清除锁定状态。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        character_id: 角色 ID。

    Returns:
        CharacterOut: 解锁后的角色信息。

    Raises:
        BizException: 角色不存在时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Character).where(
            Character.id == character_id, Character.project_id == project_id
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="角色不存在")

    character.is_locked = 0
    await db.commit()
    await db.refresh(character)

    var_result = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character.id,
        )
    )
    return _build_character_out(character, list(var_result.scalars().all()))


async def delete_character(
    db: AsyncSession,
    project_id: int,
    character_id: int,
) -> None:
    """删除角色及其所有变体图片。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        character_id: 角色 ID。

    Raises:
        BizException: 角色不存在时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Character).where(
            Character.id == character_id, Character.project_id == project_id
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="角色不存在")

    # 删除关联的变体
    var_result = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character.id,
        )
    )
    for v in var_result.scalars().all():
        await db.delete(v)

    await db.delete(character)
    await db.commit()


async def upload_character_reference(
    db: AsyncSession,
    project_id: int,
    character_id: int,
    file: UploadFile,
    user_id: int,
) -> Dict[str, Any]:
    """为角色上传参考图。

    校验项目归属（user_id）与角色存在后，将图片保存到后端静态目录
    （时间戳 + uuid 文件名防碰撞），并以 variant_type="reference" 的
    资产变体记录把 URL 关联到角色；若已存在参考图记录则覆盖其 image_url。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        character_id: 角色 ID。
        file: 上传的图片文件（multipart，jpg/png/webp，≤5MB）。
        user_id: 当前登录用户 ID，用于校验项目归属。

    Returns:
        Dict[str, Any]: {"url": 参考图访问 URL, "filename": 落盘文件名}。

    Raises:
        BizException: 项目不存在（NOT_FOUND）、非项目所有者（FORBIDDEN）、
            角色不存在（NOT_FOUND）、文件类型不符或为空或超过 5MB（PARAM_ERROR）、
            文件落盘失败（SERVER_ERROR）。
    """
    # 1. 校验项目存在且属于当前用户
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")
    if project.user_id != user_id:
        raise BizException(code=ErrorCode.FORBIDDEN, message="无权操作该项目")

    # 2. 校验角色存在且属于该项目
    result = await db.execute(
        select(Character).where(
            Character.id == character_id, Character.project_id == project_id
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="角色不存在")

    # 3. 校验文件类型（仅 jpg/png/webp）
    ext = ALLOWED_REFERENCE_TYPES.get(file.content_type or "")
    if ext is None:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="仅支持 jpg/png/webp 格式图片")

    # 4. 校验文件非空且大小 ≤5MB
    data = await file.read()
    if not data:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="上传文件为空")
    if len(data) > REFERENCE_MAX_SIZE:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="图片大小不能超过 5MB")

    # 5. 保存到静态目录，URL 形如 /static/references/<timestamp>_<uuid>.<ext>
    try:
        url = save_artifact(data, "references", ext)
    except OSError as exc:
        logger.error(f"[assets] 参考图保存失败: {exc}")
        raise BizException(code=ErrorCode.SERVER_ERROR, message="参考图保存失败") from exc
    filename = url.rsplit("/", 1)[-1]

    # 6. 以 reference 变体记录关联到角色（已存在则覆盖 URL）
    var_result = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character.id,
            AssetVariant.variant_type == REFERENCE_VARIANT_TYPE,
        )
    )
    variant = var_result.scalar_one_or_none()
    if variant is None:
        variant = AssetVariant(
            owner_type=AssetOwnerType.CHARACTER,
            owner_id=character.id,
            variant_type=REFERENCE_VARIANT_TYPE,
            image_url=url,
            visual_prompt="用户上传的参考图",
            status=AssetVariantStatus.DONE,
        )
        db.add(variant)
    else:
        variant.image_url = url
        variant.status = AssetVariantStatus.DONE

    await db.commit()
    logger.info(f"[assets] 角色 {character.name} 参考图已上传 url={url}")
    return {"url": url, "filename": filename}


async def regenerate_variant(
    db: AsyncSession, variant_id: int, visual_prompt: Optional[str] = None
) -> AssetVariantOut:
    """重新生成单个资产变体。

    Args:
        db: 异步数据库会话。
        variant_id: 变体 ID。
        visual_prompt: 新的视觉提示词，为空时使用原提示词。

    Returns:
        AssetVariantOut: 重生成后的变体信息。

    Raises:
        BizException: 变体不存在时抛出 NOT_FOUND。
    """
    variant = await db.get(AssetVariant, variant_id)
    if variant is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="资产变体不存在")

    variant.status = AssetVariantStatus.GENERATING
    await db.commit()

    provider = _get_image_provider()
    prompt = visual_prompt or variant.visual_prompt or ""
    try:
        image_url = await provider.generate(prompt)
        variant.image_url = image_url
        variant.visual_prompt = prompt
        variant.status = AssetVariantStatus.DONE
        variant.feature_vector = [0.0] * 16  # mock 重新提取特征
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[assets] 变体 {variant_id} 重生成失败: {exc}")
        variant.status = AssetVariantStatus.FAILED

    await db.commit()
    await db.refresh(variant)
    return AssetVariantOut.model_validate(variant)


async def get_scenes(db: AsyncSession, project_id: int) -> List[SceneOut]:
    """查询项目下的所有场景。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        List[SceneOut]: 场景列表。
    """
    result = await db.execute(
        select(Scene).where(Scene.project_id == project_id)
    )
    scenes = result.scalars().all()
    return [SceneOut.model_validate(s) for s in scenes]


async def generate_scenes(db: AsyncSession, project_id: int) -> List[SceneOut]:
    """从剧本提取场景并生成场景概念图。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        List[SceneOut]: 生成的场景列表。

    Raises:
        BizException: 剧本不存在时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Script)
        .where(Script.project_id == project_id)
        .order_by(desc(Script.version), desc(Script.id))
    )
    script = result.scalars().first()
    if script is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="剧本不存在")

    scenes_data = script.content.get("scenes", []) if isinstance(script.content, dict) else []
    provider = _get_image_provider()
    created_scenes: List[Scene] = []

    for sc in scenes_data:
        if not isinstance(sc, dict):
            continue
        name = sc.get("name") or sc.get("场景名") or f"场景{len(created_scenes) + 1}"
        description = sc.get("description") or sc.get("描述") or ""
        visual_prompt = sc.get("visual_prompt") or description or name

        try:
            asset_url = await provider.generate(visual_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[assets] 场景 {name} 概念图生成失败: {exc}")
            asset_url = None

        scene = Scene(
            project_id=project_id,
            name=name,
            description=description,
            visual_prompt=visual_prompt,
            asset_url=asset_url,
        )
        db.add(scene)
        created_scenes.append(scene)

    await db.commit()
    output: List[SceneOut] = []
    for scene in created_scenes:
        await db.refresh(scene)
        output.append(SceneOut.model_validate(scene))
    return output


async def get_consistency(db: AsyncSession, project_id: int) -> List[Dict[str, Any]]:
    """查询项目的一致性报告。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        List[Dict]: 一致性报告列表。
    """
    result = await db.execute(
        select(ConsistencyReport).where(ConsistencyReport.project_id == project_id)
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id,
            "subject_type": r.subject_type.value,
            "subject_id": r.subject_id,
            "ref_asset_id": r.ref_asset_id,
            "similarity_score": float(r.similarity_score),
            "threshold": float(r.threshold),
            "action": r.action.value,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]

async def regenerate_character(
    db: AsyncSession,
    project_id: int,
    character_id: int,
    visual_prompt: Optional[str] = None,
) -> CharacterOut:
    """重新生成单个角色的主图（换一张）。

    找到该角色的主定妆照变体（front 类型），调用图像生成 Provider 重新生成，
    不影响其他角色。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        character_id: 角色 ID。
        visual_prompt: 新的视觉提示词，为空时使用原提示词。

    Returns:
        CharacterOut: 更新后的角色信息。

    Raises:
        BizException: 角色不存在时抛出 NOT_FOUND。
    """
    # 校验角色存在且属于该项目
    character = await db.get(Character, character_id)
    if character is None or character.project_id != project_id:
        raise BizException(code=ErrorCode.NOT_FOUND, message="角色不存在")

    # 查找该角色的主图变体（front 类型）
    result = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character_id,
            AssetVariant.variant_type == "front",
        )
    )
    variant = result.scalar_one_or_none()

    if variant is None:
        # 如果没有 front 变体，取第一个变体
        result = await db.execute(
            select(AssetVariant).where(
                AssetVariant.owner_type == AssetOwnerType.CHARACTER,
                AssetVariant.owner_id == character_id,
            ).limit(1)
        )
        variant = result.scalar_one_or_none()

    if variant is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="角色主图变体不存在")

    # 标记生成中
    variant.status = AssetVariantStatus.GENERATING
    await db.commit()

    # 调用图像生成
    provider = _get_image_provider()
    prompt = visual_prompt or variant.visual_prompt or ""
    try:
        image_url = await provider.generate(prompt)
        variant.image_url = image_url
        if visual_prompt:
            variant.visual_prompt = visual_prompt
        variant.status = AssetVariantStatus.DONE
        variant.feature_vector = [0.0] * 16
        # 同步更新 character 表的 main_asset_url 字段（数据库字段）
        character.main_asset_url = image_url
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[assets] 角色 {character_id} 重生成失败: {exc}")
        variant.status = AssetVariantStatus.FAILED
        raise BizException(code=ErrorCode.INTERNAL, message=f"生成失败: {exc}")

    await db.commit()
    await db.refresh(variant)
    await db.refresh(character)

    # 重新查询所有变体并返回角色信息
    var_result = await db.execute(
        select(AssetVariant).where(
            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
            AssetVariant.owner_id == character_id,
        )
    )
    variants = var_result.scalars().all()

    # 同步更新主图 URL（main_asset_url 是动态字段，需要从 front 变体提取）
    front = next((v for v in variants if v.variant_type == "front"), None)
    if front and front.image_url:
        character.main_asset_url = front.image_url

    return _build_character_out(character, variants)
