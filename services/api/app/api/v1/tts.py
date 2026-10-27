"""
配音（TTS）API 路由。

提供内置音色库查询（VO-02）与项目字幕查询（VO-05）端点。
路由自带完整路径（/tts/voices、/projects/{id}/subtitles），
在 api/v1/__init__.py 中无前缀注册。
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode, ok
from app.domains import voice as voice_domain
from app.models import Storyboard, User, Character

logger = get_logger()

router = APIRouter(tags=["配音"])


@router.get("/tts/voices", summary="查询音色库")
async def get_tts_voices(
    user: User = Depends(get_current_user),
) -> dict:
    """返回内置音色映射表（VO-02）。

    覆盖 mock（default）与 agnes（OpenAI 风格预置音色）的可用音色；
    agnes 音色在网关 /audio/speech 就绪后实际生效。

    Args:
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为音色列表
            [{voice_id, name, gender, style, provider}]。
    """
    return ok(data=voice_domain.list_voices())


@router.post("/tts/preview", summary="试听音色")
async def preview_voice(
    voice_id: str = Query(..., description="音色 ID"),
    text: str = Query("你好，我是配音演员，这是我的试听效果。", description="试听文本"),
    user: User = Depends(get_current_user),
) -> dict:
    """试听指定音色：真实调用 TTS Provider 合成试听文本并返回音频 URL。

    Args:
        voice_id: 音色 ID。
        text: 试听文本。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 {"url": 音频URL, "voice_id": 音色ID}。
    """
    from app.providers.tts.registry import get_tts_registry

    provider = get_tts_registry().get_provider("qianwen")
    try:
        url = await provider.synthesize(text, voice_id or "Cherry")
        degraded = getattr(provider, "last_degraded", False)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[tts-preview] 试听合成失败 voice={voice_id}: {exc}")
        raise BizException(code=ErrorCode.SERVER_ERROR, message=f"试听合成失败: {exc}") from exc
    return ok(data={"url": url, "voice_id": voice_id, "degraded": degraded})


class _VoiceLineBody(BaseModel):
    voice_id: str
    text: str
    speed: float = 1.0


@router.post("/projects/{id}/storyboards/{sb_id}/voice", summary="生成单句配音并写回分镜")
async def generate_voice_line(
    id: int,
    sb_id: int,
    body: _VoiceLineBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from app.providers.tts.registry import get_tts_registry

    provider = get_tts_registry().get_provider("qianwen")
    try:
        url = await provider.synthesize(body.text, body.voice_id or "Cherry", {"speed": body.speed})
    except Exception as exc:
        logger.error(f"[voice-line] 合成失败 sb={sb_id}: {exc}")
        raise BizException(code=ErrorCode.SERVER_ERROR, message=f"配音合成失败: {exc}") from exc

    await db.execute(
        update(Storyboard).where(Storyboard.id == sb_id).values(audio_url=url)
    )
    await db.commit()
    return ok(data={"url": url, "sb_id": sb_id})


class _BindVoiceBody(BaseModel):
    voice_id: str


class _SubtitleLine(BaseModel):
    sb_id: int
    text: str


@router.put("/projects/{id}/characters/{cid}/voice", summary="绑定角色音色")
async def bind_character_voice(
    id: int,
    cid: int,
    body: _BindVoiceBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await db.execute(
        update(Character).where(Character.id == cid, Character.project_id == id).values(voice_id=body.voice_id)
    )
    await db.commit()
    return ok(data={"cid": cid, "voice_id": body.voice_id})


class _DialogueBody(BaseModel):
    dialogue: str


@router.put("/projects/{id}/storyboards/{sb_id}/dialogue", summary="更新分镜台词")
async def update_storyboard_dialogue(
    id: int,
    sb_id: int,
    body: _DialogueBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await db.execute(
        update(Storyboard).where(Storyboard.id == sb_id, Storyboard.project_id == id).values(dialogue=body.dialogue)
    )
    await db.commit()
    return ok(data={"sb_id": sb_id})


class _SubtitleSelectionBody(BaseModel):
    selected_texts: list[str]


@router.post("/projects/{id}/subtitles/save", summary="保存用户选择的字幕勾选")
async def save_subtitle_selection(
    id: int,
    body: _SubtitleSelectionBody,
    user: User = Depends(get_current_user),
) -> dict:
    """保存用户勾选的台词文本列表，加载对白时恢复勾选状态。"""
    import json
    from app.tasks.compose_tasks import STATIC_ROOT
    out = STATIC_ROOT / "subtitles" / f"{id}_selected.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body.selected_texts, ensure_ascii=False), encoding="utf-8")
    return ok(data={"saved": len(body.selected_texts)})


@router.get("/projects/{id}/subtitles/selection", summary="读取用户字幕勾选")
async def load_subtitle_selection(
    id: int,
    user: User = Depends(get_current_user),
) -> dict:
    import json
    from app.tasks.compose_tasks import STATIC_ROOT
    f = STATIC_ROOT / "subtitles" / f"{id}_selected.json"
    if not f.is_file():
        return ok(data={"selected_texts": []})
    texts = json.loads(f.read_text(encoding="utf-8"))
    return ok(data={"selected_texts": texts})


@router.get("/projects/{id}/subtitles", summary="查询项目字幕")
async def get_project_subtitles(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """返回项目全部分镜的字幕（VO-05）。

    按镜头顺序以台词 + 配音时长拼装标准 SRT 文本，同时返回分镜级
    字幕分段明细，供合成阶段（批次 D）消费。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 {"srt": SRT文本, "segments": [...], "total": N}。
    """
    result = await voice_domain.get_project_subtitles(db, id)
    return ok(data=result)
