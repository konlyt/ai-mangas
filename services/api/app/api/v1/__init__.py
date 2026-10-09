"""
API v1 路由入口。

聚合各业务模块路由，统一挂载到 /api/v1 前缀下。
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.projects import router as projects_router
from app.api.v1.models import router as models_router
from app.api.v1.script import router as script_router
from app.api.v1.assets import router as assets_router
from app.api.v1.storyboard import router as storyboard_router
from app.api.v1.generate import router as generate_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.compose import router as compose_router
from app.api.v1.graph import router as graph_router
from app.api.v1.revisions import router as revisions_router
from app.api.v1.orders import router as orders_router
from app.api.v1.tts import router as tts_router
from app.core.response import ok

# v1 总路由
api_router = APIRouter()


@api_router.get("/health", summary="健康检查")
async def health() -> dict:
    """健康检查端点。

    Returns:
        dict: 统一响应结构，data 为服务状态。
    """
    return ok(data={"status": "ok"})


# 认证与用户（路由自身已带 prefix）
api_router.include_router(auth_router, tags=["认证"])
api_router.include_router(users_router, tags=["用户"])

# 项目（路由自身已带 prefix）
api_router.include_router(projects_router, tags=["项目"])

# 创作五阶段（统一挂在 /projects 下）
api_router.include_router(script_router, prefix="/projects", tags=["剧本"])
api_router.include_router(assets_router, prefix="/projects", tags=["资产"])
api_router.include_router(storyboard_router, prefix="/projects", tags=["分镜"])
api_router.include_router(generate_router, prefix="/projects", tags=["生成"])
api_router.include_router(compose_router, prefix="/projects", tags=["合成"])

# 任务与图编排
api_router.include_router(tasks_router, prefix="/tasks", tags=["任务"])
api_router.include_router(graph_router, prefix="/projects", tags=["Graph"])
api_router.include_router(revisions_router, prefix="/projects", tags=["版本"])

# 模型与订单（models 路由自身已带 prefix）
api_router.include_router(models_router, tags=["模型"])
api_router.include_router(orders_router, prefix="/orders", tags=["订单"])

# 配音（tts 路由自身已带完整路径：/tts/voices、/projects/{id}/subtitles）
api_router.include_router(tts_router, tags=["配音"])
