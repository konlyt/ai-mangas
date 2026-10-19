"""
资产 API 路由。

提供角色生成、查询、锁定、变体重生成，场景生成与查询，一致性报告查询。
路由挂载于 /projects 前缀下。
"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import assets as assets_domain
from app.models import User
from app.schemas.asset import (
    AssetRegenerateRequest,
    CharacterGenerateRequest,
    CharacterLockRequest,
)

router = APIRouter(tags=["资产"])


@router.post("/{id}/assets/characters", summary="生成角色定妆照")
async def generate_characters(
    id: int,
    req: CharacterGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """从剧本提取角色并批量生成三角度定妆照。

    Args:
        id: 项目 ID。
        req: 角色生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为角色列表。
    """
    characters = await assets_domain.generate_characters(db, id, req)
    return ok(data=[c.model_dump() for c in characters])


@router.get("/{id}/assets/characters", summary="查询角色列表")
async def get_characters(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目下的所有角色。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为角色列表。
    """
    characters = await assets_domain.get_characters(db, id)
    return ok(data=[c.model_dump() for c in characters])


@router.post("/{id}/assets/characters/{cid}/lock", summary="锁定角色")
async def lock_character(
    id: int,
    cid: int,
    req: CharacterLockRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """锁定角色并提取特征向量。

    Args:
        id: 项目 ID。
        cid: 角色 ID。
        req: 角色锁定请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为锁定后的角色信息。
    """
    character = await assets_domain.lock_character(db, id, cid, req)
    return ok(data=character.model_dump())


@router.post("/{id}/assets/characters/{cid}/unlock", summary="解锁角色")
async def unlock_character(
    id: int,
    cid: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """解锁角色，允许重新生成。

    Args:
        id: 项目 ID。
        cid: 角色 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构。
    """
    character = await assets_domain.unlock_character(db, id, cid)
    return ok(data=character.model_dump())


@router.delete("/{id}/assets/characters/{cid}", summary="删除角色")
async def delete_character(
    id: int,
    cid: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """删除指定角色及其所有变体图片。

    Args:
        id: 项目 ID。
        cid: 角色 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构。
    """
    await assets_domain.delete_character(db, id, cid)
    return ok(message="删除成功")


@router.post("/{id}/assets/characters/{cid}/regenerate", summary="重新生成单个角色（换一张）")
async def regenerate_character(
    id: int,
    cid: int,
    req: AssetRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """重新生成单个角色的主图（换一张），不影响其他角色。

    Args:
        id: 项目 ID。
        cid: 角色 ID。
        req: 重生成请求体（可含新的视觉提示词）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为更新后的角色信息。
    """
    visual_prompt = req.visual_prompt if req else None
    character = await assets_domain.regenerate_character(db, id, cid, visual_prompt)
    return ok(data=character.model_dump())


@router.post("/{id}/assets/{asset_id}/reference", summary="上传角色参考图")
async def upload_reference(
    id: int,
    asset_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """上传角色参考图（multipart，jpg/png/webp，≤5MB）。

    校验项目归属与角色存在后，图片保存到后端静态目录并以
    variant_type="reference" 的变体记录关联到角色。

    Args:
        id: 项目 ID。
        asset_id: 角色 ID。
        file: 上传的图片文件。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 {"url": 访问 URL, "filename": 文件名}。
    """
    result = await assets_domain.upload_character_reference(db, id, asset_id, file, user.id)
    return ok(data=result)


@router.post("/{id}/assets/variants/{vid}/regenerate", summary="重生成资产变体")
async def regenerate_variant(
    id: int,
    vid: int,
    req: AssetRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """重新生成单个资产变体。

    Args:
        id: 项目 ID。
        vid: 变体 ID。
        req: 重生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为重生成后的变体信息。
    """
    visual_prompt = req.visual_prompt if req else None
    variant = await assets_domain.regenerate_variant(db, vid, visual_prompt)
    return ok(data=variant.model_dump())


@router.get("/{id}/assets/scenes", summary="查询场景列表")
async def get_scenes(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目下的所有场景。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为场景列表。
    """
    scenes = await assets_domain.get_scenes(db, id)
    return ok(data=[s.model_dump() for s in scenes])


@router.post("/{id}/assets/scenes", summary="生成场景概念图")
async def generate_scenes(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """从剧本提取场景并生成概念图。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为场景列表。
    """
    scenes = await assets_domain.generate_scenes(db, id)
    return ok(data=[s.model_dump() for s in scenes])


@router.get("/{id}/consistency", summary="查询一致性报告")
async def get_consistency(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目的一致性校验报告。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为一致性报告列表。
    """
    reports = await assets_domain.get_consistency(db, id)
    return ok(data=reports)
