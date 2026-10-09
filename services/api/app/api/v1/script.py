"""
剧本 API 路由。

提供剧本生成（SSE 流式）、查询、更新、确认等端点，全部需要登录。
路由挂载于 /projects 前缀下。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import scripts as scripts_domain
from app.models import User
from app.schemas.script import ScriptGenerateRequest, ScriptUpdateRequest

router = APIRouter(tags=["剧本"])


@router.post("/{project_id}/script/generate", summary="流式生成剧本")
async def generate_script(
    project_id: int,
    req: ScriptGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """流式生成结构化剧本。

    Args:
        project_id: 项目 ID。
        req: 剧本生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        StreamingResponse: SSE 流式响应，逐 token 返回生成内容。
    """
    return StreamingResponse(
        scripts_domain.generate_script(project_id, req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{project_id}/script", summary="获取剧本")
async def get_script(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取项目最新版本的剧本。

    Args:
        project_id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为剧本信息。
    """
    script = await scripts_domain.get_script(db, project_id)
    return ok(data=script.model_dump())


@router.put("/{project_id}/script", summary="更新剧本")
async def update_script(
    project_id: int,
    req: ScriptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """更新剧本内容。

    Args:
        project_id: 项目 ID。
        req: 剧本更新请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为更新后的剧本信息。
    """
    script = await scripts_domain.update_script(db, project_id, req)
    return ok(data=script.model_dump())


@router.post("/{project_id}/script/confirm", summary="确认剧本")
async def confirm_script(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """确认剧本，推进到资产阶段并创建版本快照。

    Args:
        project_id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 None。
    """
    await scripts_domain.confirm_script(db, project_id)
    return ok(data=None, message="剧本已确认")


@router.post("/{project_id}/script/score", summary="剧本质量评分")
async def score_script(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """对项目最新剧本进行四维质量评分（SCR-07）。

    LLM 按冲突强度/人物弧光/节奏/爽点密度评分并给出建议；
    LLM 输出解析失败时返回基于结构特征的兜底估算分（estimated=True）。

    Args:
        project_id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为评分结果（含四维分数、总分、建议、评语）。
    """
    result = await scripts_domain.score_script(db, project_id, user.id)
    return ok(data=result)


@router.get("/{project_id}/script/episodes", summary="获取剧本分集结构")
async def get_script_episodes(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取项目剧本的分集结构（SCR-06 简化版）。

    content 已含 episodes 字段时直接返回；否则按每 3 场一集自动划分。

    Args:
        project_id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 {script_id, source, episodes}。
    """
    result = await scripts_domain.get_script_episodes(db, project_id)
    return ok(data=result)
