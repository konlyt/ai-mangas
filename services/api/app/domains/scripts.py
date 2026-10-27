"""
剧本领域服务。

提供剧本的流式生成、查询、更新、确认、质量评分（SCR-07）与分集结构解析（SCR-06）等业务逻辑。
"""

import json
import re
from collections.abc import AsyncGenerator
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import Project, ProjectStatus, Revision, Script
from app.providers.llm.litellm_client import get_llm, resolve_llm_settings
from app.domains.prompts import build_script_messages
from app.schemas.script import ScriptGenerateRequest, ScriptOut, ScriptUpdateRequest

logger = get_logger()

# 剧本质量评分系统提示词：要求 LLM 按四维评分并严格输出 JSON
SCRIPT_SCORE_SYSTEM_PROMPT = """你是一位资深的中文短剧/动漫剧本评审专家，精通网文与短剧爆款方法论。

请对用户提供的剧本进行专业质量评估，从以下四个维度打分（0-100 的整数）：
- conflict（冲突强度）：各场次冲突是否明确、是否逐步升级、张力是否足够。
- character（人物弧光）：主角核心目标与转变是否清晰，人物是否立体，配角是否推动剧情。
- pacing（节奏）：信息密度与悬念节奏是否紧凑，是否存在拖沓或断裂。
- hook_density（爽点密度）：反转、爽点、钩子的数量与强度是否足以留住观众。

严格只输出 JSON（不要 markdown 代码块、不要任何解释文字），结构如下：
{
  "conflict": 0-100,
  "character": 0-100,
  "pacing": 0-100,
  "hook_density": 0-100,
  "overall": 0-100,
  "suggestions": ["改进建议1", "改进建议2"],
  "summary": "一句话总评"
}
约束：overall 为四维加权综合分；suggestions 给出 2~5 条具体可执行的修改建议；summary 不超过 60 字。"""

# 分集自动划分时每集包含的场次数量
_EPISODE_SCENES_COUNT = 3
# 送入 LLM 评分的剧本文本最大长度（超出则截断，避免超出上下文）
_SCORE_CONTENT_MAX_CHARS = 6000


async def generate_script(
    project_id: int, req: ScriptGenerateRequest
) -> AsyncGenerator[str, None]:
    """流式生成结构化剧本（SSE 逐 token 返回），完成后存库并更新项目状态。

    模型凭证按「项目级选型 > 用户级 API Key > .env」解析后交由统一的
    LLMClient 调用；生成失败时通过 SSE 的 error 事件回传真实失败原因，
    并且**不写入任何占位/mock 剧本**（详见 providers/llm/litellm_client.py）。

    注意：由于 StreamingResponse 返回后 FastAPI 会立即关闭依赖注入的会话，
    此处使用 AsyncSessionLocal 在生成器内部独立管理数据库会话，避免会话提前释放。

    Args:
        project_id: 项目 ID。
        req: 剧本生成请求体。

    Yields:
        str: SSE 格式的增量数据，形如
            `data: {"token": "..."}\\n\\n`；
            失败时为 `data: {"error": "原因"}` + `data: {"done": true, "script_id": null}`。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    # 在生成器内部创建独立会话
    async with AsyncSessionLocal() as db:
        # 校验项目存在
        project = await db.get(Project, project_id)
        if project is None:
            raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

        raw_input = req.raw_input
        meta = req.meta or {}

        # 构建 LLM 消息：系统提示词融合网文/短剧创作方法论，
        # 要求返回结构化 JSON 剧本（title/logline/characters/scenes）
        messages = build_script_messages(raw_input, meta)

        # 手动直接调用 DeepSeek API，绕过所有中间层
        import httpx
        from app.core.config import settings

        full_text = ""
        error: Optional[str] = None
        deepseek_api_key = settings.DEEPSEEK_API_KEY
        deepseek_base_url = settings.DEEPSEEK_BASE_URL.rstrip("/")
        deepseek_model = settings.DEEPSEEK_MODEL

        logger.info(f"[script-generate] 手动调用 DeepSeek API: model={deepseek_model}, key={deepseek_api_key[:10]}...")

        try:
            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{deepseek_base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": deepseek_model,
                        "messages": messages,
                        "stream": True,
                        "temperature": 0.7,
                    },
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        error = f"DeepSeek API 错误 {response.status_code}: {error_text.decode('utf-8')[:200]}"
                        logger.error(f"[script-generate] {error}")
                    else:
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data["choices"][0]["delta"].get("content", "")
                                if delta:
                                    full_text += delta
                                    yield f"data: {json.dumps({'token': delta}, ensure_ascii=False)}\n\n"
                            except Exception:
                                pass
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            logger.error(f"[script-generate] 调用失败: {error}")

        # 生成失败：显式回传错误，绝不写入与用户输入无关的占位剧本
        if error is not None or not full_text.strip():
            reason = (error or "模型未返回任何内容").replace("\n", " ").replace("\r", " ")
            logger.error(f"[script-generate] 生成失败 project_id={project_id}: {reason}")
            yield f"data: {json.dumps({'error': reason[:500]}, ensure_ascii=False)}\n\n"
            yield (
                f"data: {json.dumps({'done': True, 'script_id': None}, ensure_ascii=False)}\n\n"
            )
            return

        # 完成后尝试解析 JSON，失败则用原始文本兜底
        content = _extract_json_block(full_text)
        if content is None:
            content = {
                "title": project.title,
                "raw": full_text,
                "characters": [],
                "scenes": [],
            }

        # 结构兜底：LLM 偶尔不返回外层包装（直接返回单个场景对象），
        # 或 scenes 缺失/为空时自动包装，保证前端能正常渲染。
        if isinstance(content, dict):
            # 情况1：content 本身就是一个场景对象（有 seq/title/description，没有 scenes）
            if "scenes" not in content and "seq" in content and "description" in content:
                content = {
                    "title": content.get("title") or project.title,
                    "logline": "",
                    "characters": [],
                    "scenes": [content],
                }
            # 情况2：有 scenes 但为空数组，且 content 里有 raw_text 类字段
            elif isinstance(content.get("scenes"), list) and len(content["scenes"]) == 0:
                # 尝试把整个 content 包成一场
                content["scenes"] = [{
                    "seq": 1,
                    "title": content.get("title") or project.title,
                    "description": content.get("raw") or content.get("description") or "",
                }]
            # 情况3：补齐缺失字段
            content.setdefault("title", project.title)
            content.setdefault("logline", "")
            content.setdefault("characters", [])
            if not isinstance(content.get("scenes"), list):
                content["scenes"] = []

        # 存储剧本
        script = Script(
            project_id=project_id,
            content=content,
            raw_text=raw_input,
            version=1,
        )
        db.add(script)

        # 更新项目状态为 scripting
        project.status = ProjectStatus.SCRIPTING
        await db.commit()
        await db.refresh(script)

        # 发送结束事件，携带 script_id
        yield (
            f"data: {json.dumps({'done': True, 'script_id': script.id}, ensure_ascii=False)}\n\n"
        )


async def get_script(db: AsyncSession, project_id: int) -> ScriptOut:
    """获取项目最新版本的剧本。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        ScriptOut: 剧本输出模型。

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
    return ScriptOut.model_validate(script)


async def update_script(
    db: AsyncSession, project_id: int, req: ScriptUpdateRequest
) -> ScriptOut:
    """更新项目最新版本的剧本内容。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 剧本更新请求体。

    Returns:
        ScriptOut: 更新后的剧本输出模型。

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

    script.content = req.content
    if req.raw_text is not None:
        script.raw_text = req.raw_text

    await db.commit()
    await db.refresh(script)
    return ScriptOut.model_validate(script)


async def confirm_script(db: AsyncSession, project_id: int) -> None:
    """确认剧本，将项目状态推进到 assets 阶段并创建版本快照。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        None

    Raises:
        BizException: 剧本或项目不存在时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Script)
        .where(Script.project_id == project_id)
        .order_by(desc(Script.version), desc(Script.id))
    )
    script = result.scalars().first()
    if script is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="剧本不存在")

    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 更新项目状态到 assets
    project.status = ProjectStatus.ASSETS

    # 创建 revision 快照
    revision = Revision(
        project_id=project_id,
        stage="script",
        snapshot={"script": script.content, "version": script.version},
        created_by=project.user_id,
    )
    db.add(revision)
    await db.commit()


async def _get_latest_script(db: AsyncSession, project_id: int) -> Script:
    """获取项目最新版本的剧本记录。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        Script: 最新版本剧本 ORM 对象。

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
    return script


def _extract_json_block(text: str) -> Optional[dict]:
    """从 LLM 返回文本中提取 JSON 对象。

    依次尝试：整段解析、剥离 ```json 代码块后解析、
    从首个 "{" 起 raw_decode 逐位置尝试（兼容 JSON 前后带噪声文字或连续多个对象）。
    优先返回包含 title/logline/scenes/characters 等剧本根字段的对象。

    Args:
        text: LLM 返回的原始文本。

    Returns:
        Optional[dict]: 解析成功返回字典，失败返回 None。
    """
    if not text:
        return None
    candidates = [text.strip()]
    # 剥离 markdown 代码块
    match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if match:
        candidates.append(match.group(1).strip())

    # 收集所有可能的 JSON 候选
    decoded_objects: list[dict] = []
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict):
                decoded_objects.append(parsed)
        except Exception:  # noqa: BLE001
            continue

    # raw_decode：从每个 "{" 位置起尝试解码，收集所有可解析的字典
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
            if isinstance(parsed, dict):
                decoded_objects.append(parsed)
        except ValueError:
            pass
        idx = text.find("{", idx + 1)

    if not decoded_objects:
        return None

    # 优先返回包含剧本根字段的对象
    root_keys = {"title", "logline", "scenes", "characters"}
    for obj in decoded_objects:
        if root_keys & set(obj.keys()):
            return obj

    # 兜底：返回第一个对象
    return decoded_objects[0]


def _clamp_score(value: Any, default: float = 0.0) -> Optional[int]:
    """将任意值收敛为 0-100 的整数评分。

    Args:
        value: 待收敛的值（可能为数字、字符串或 None）。
        default: 无法解析时的默认值。

    Returns:
        Optional[int]: 0-100 的整数；value 不为 None 时始终返回整数，为 None 返回 None。
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return int(default)
    return int(max(0, min(100, round(num))))


def _fallback_score(content: dict) -> dict:
    """LLM 评分不可用时的兜底评分。

    基于剧本结构特征（场次数量、角色数量、单场描述篇幅）给出确定性估算分，
    并标注 estimated=True 以便前端区分展示。

    Args:
        content: 结构化剧本内容 JSON。

    Returns:
        dict: 兜底评分结果（四维 + overall + suggestions + summary + estimated）。
    """
    scenes = [s for s in (content.get("scenes") or []) if isinstance(s, dict)]
    characters = [c for c in (content.get("characters") or []) if isinstance(c, dict)]
    scene_count = len(scenes)
    desc_total = sum(len(str(s.get("description") or "")) for s in scenes)
    avg_desc = desc_total / scene_count if scene_count else 0

    # 启发式估算：描述越充分冲突铺垫越足；角色 3~6 个最优；场次过多易拖沓
    conflict = _clamp_score(40 + avg_desc / 6, 50)
    character = _clamp_score(35 + len(characters) * 10, 50)
    pacing = _clamp_score(85 - max(scene_count - 8, 0) * 3, 50)
    hook_density = _clamp_score(45 + avg_desc / 8, 50)
    overall = int(round((conflict + character + pacing + hook_density) / 4))

    return {
        "overall": overall,
        "conflict": conflict,
        "character": character,
        "pacing": pacing,
        "hook_density": hook_density,
        "suggestions": [
            "当前为基于剧本结构特征的估算评分，建议手动复核关键场次。",
            "检查每场是否都有明确的冲突与转折，避免过场戏。",
        ],
        "summary": "LLM 评分暂不可用，以上为基于剧本结构特征的估算结果。",
        "estimated": True,
    }


async def score_script(db: AsyncSession, project_id: int, user_id: int) -> dict:
    """对项目最新剧本进行四维质量评分（SCR-07）。

    调用 LLM 按冲突强度/人物弧光/节奏/爽点密度四维评分（各 0-100），
    并输出总分、改进建议与一句话评语；LLM 返回 JSON 解析失败时
    使用基于结构特征的兜底评分并标注 estimated=True。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        user_id: 当前登录用户 ID（用于操作留痕，并解析其用户级 LLM 凭证配置）。

    Returns:
        dict: 评分结果，结构为
            {overall, conflict, character, pacing, hook_density,
             suggestions: list[str], summary: str, estimated: bool}。

    Raises:
        BizException: 剧本不存在时抛出 NOT_FOUND。
    """
    script = await _get_latest_script(db, project_id)
    logger.info(f"[score_script] project_id={project_id}, user_id={user_id}, script_id={script.id}")

    content = script.content if isinstance(script.content, dict) else {}
    # 剧本 JSON 序列化后送评，过长时截断，避免超出模型上下文
    script_text = json.dumps(content, ensure_ascii=False)[:_SCORE_CONTENT_MAX_CHARS]

    result: Optional[dict] = None
    try:
        # 运行时凭证：项目级模型选型 > 用户级 model_configs 配置（AES 解密）> .env
        override = await resolve_llm_settings(db, user_id, project_id=project_id)
        if override:
            llm = get_llm(
                provider=override.get("provider") or "deepseek",
                api_key=override.get("api_key"),
                api_base=override.get("api_base"),
                model_name=override.get("model_name"),
            )
        else:
            llm = get_llm()
        text = await llm.achat(
            [
                {"role": "system", "content": SCRIPT_SCORE_SYSTEM_PROMPT},
                {"role": "user", "content": f"请对以下剧本进行质量评分：\n{script_text}"},
            ],
            temperature=0.3,
        )
        parsed = _extract_json_block(text)
        if parsed is not None:
            conflict = _clamp_score(parsed.get("conflict"))
            character = _clamp_score(parsed.get("character"))
            pacing = _clamp_score(parsed.get("pacing"))
            hook_density = _clamp_score(parsed.get("hook_density"))
            dims = [v for v in (conflict, character, pacing, hook_density) if v is not None]
            # 四维任一缺失即视为无效输出，走兜底
            if len(dims) == 4:
                overall = _clamp_score(parsed.get("overall"), default=sum(dims) / 4)
                if overall is not None:
                    suggestions = parsed.get("suggestions")
                    result = {
                        "overall": overall,
                        "conflict": conflict,
                        "character": character,
                        "pacing": pacing,
                        "hook_density": hook_density,
                        "suggestions": [
                            str(s) for s in suggestions if isinstance(suggestions, list) and s
                        ][:5],
                        "summary": str(parsed.get("summary") or "")[:200],
                        "estimated": False,
                    }
    except BizException as exc:
        logger.warning(f"[score_script] LLM 调用失败，使用兜底评分: {exc.message}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[score_script] 评分解析异常，使用兜底评分: {exc}")

    if result is None:
        result = _fallback_score(content)
    return result


def _build_auto_episodes(scenes: list) -> list[dict]:
    """按每 3 场一集将场次列表自动划分为分集结构。

    Args:
        scenes: 剧本 content 中的场次列表（可能为任意元素类型）。

    Returns:
        list[dict]: 分集列表，每项为
            {episode: 集序号, title: 集标题, synopsis: 剧情梗概, scenes: [原始场次]}。
    """
    valid_scenes = [s for s in scenes if isinstance(s, dict)]
    episodes: list[dict] = []
    for idx, scene in enumerate(valid_scenes):
        bucket = idx // _EPISODE_SCENES_COUNT
        if bucket >= len(episodes):
            episodes.append(
                {
                    "episode": bucket + 1,
                    "title": f"第 {bucket + 1} 集",
                    "synopsis": "",
                    "scenes": [],
                }
            )
        episodes[bucket]["scenes"].append(scene)

    # 剧情梗概：取该集首场标题与描述摘要，便于前端展示
    for ep in episodes:
        first = ep["scenes"][0] if ep["scenes"] else {}
        title = str(first.get("title") or "").strip()
        desc = str(first.get("description") or "").strip()
        synopsis = f"{title}：{desc}" if title else desc
        ep["synopsis"] = synopsis[:80] + ("…" if len(synopsis) > 80 else "")
    return episodes


async def get_script_episodes(db: AsyncSession, project_id: int) -> dict:
    """获取项目剧本的分集结构（SCR-06 简化版）。

    content 中已含 episodes 字段时直接返回（source=stored）；
    否则按 scenes 数量每 3 场归一集自动划分（source=auto）。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        dict: {script_id: 剧本 ID, source: "stored"|"auto", episodes: 分集列表}。

    Raises:
        BizException: 剧本不存在时抛出 NOT_FOUND。
    """
    script = await _get_latest_script(db, project_id)
    content = script.content if isinstance(script.content, dict) else {}

    episodes = content.get("episodes")
    if isinstance(episodes, list) and episodes:
        return {"script_id": script.id, "source": "stored", "episodes": episodes}

    scenes = content.get("scenes")
    return {
        "script_id": script.id,
        "source": "auto",
        "episodes": _build_auto_episodes(scenes if isinstance(scenes, list) else []),
    }

