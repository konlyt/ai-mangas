"""
一致性校验 Agent 节点（ConsistencyAgent）。

职责：
    对生成的角色资产与关键帧进行真实图像相似度比对（aHash + HSV 直方图加权），
    决定处置动作（pass / regenerate / manual），
    通过 LLM 提取角色特征标签并注入图像提示词保障生成一致性，
    将比对结果写入 state.consistency，
    并以独立数据库会话落库 consistency_reports 与 asset_variants.feature_vector。

多角色逐角色校验与 check_mode（方案 A5/A6）：
    关键帧校验不再以"首个带定妆照的角色"作全局参照，而是按分镜关联角色
    （resolve_storyboard_characters）逐角色比对，每个角色一条报告：
        - ref_lock     ：角色参考板（ref_board_url）在关键帧生成时真实注入且
                         未被 Provider 丢弃（读取分镜 ref_count/ref_dropped/
                         ref_character_names 标记）——参考板本身即锁定机制，
                         得分仅作质检参考，低于阈值不自动重生成（action=manual）；
        - feature_card ：参考图未生效/未注入，用特征卡/定妆照（main_asset_url 等）
                         作参照比对，保留既有阈值重生成逻辑；
        - quality_gate ：无任何可用参照，仅做关键帧存在性等基础质检。
    check_mode 随报告写入 state.consistency.reports，并真实落库
    ConsistencyReport.check_mode 列（历史行由迁移 b3f7a2c94d15 回填为
    quality_gate）。

输入（来自 state）：
    - characters: 角色列表（含 name / description / image_url / feature_tags）。
    - scenes: 场景列表。
    - storyboards: 分镜列表（可能为空）。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - consistency: 一致性校验结果汇总（含 need_regenerate 标记）。
    - stage: 下一阶段（assets 校验后为 storyboard；关键帧校验后为 video）。
"""

import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy import desc, select

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import (
    AssetOwnerType,
    AssetVariant,
    AssetVariantStatus,
    Character,
    ConsistencyAction,
    ConsistencyReport,
    ConsistencySubjectType,
)
from app.providers.llm.litellm_client import LLMClient, get_llm
from app.providers.storage import STATIC_ROOT
from app.utils.image_sim import combined_similarity

logger = get_logger()

# 一致性判定阈值：综合相似度低于该值时要求重新生成
SIMILARITY_THRESHOLD = 0.75

# 图像下载超时（秒）
_IMAGE_DOWNLOAD_TIMEOUT = 30.0

# 特征标签白名单字段（与图像提示词注入格式一一对应）
FEATURE_TAG_KEYS = ("appearance", "costume", "hairstyle", "body_type", "style_tag")

# 特征标签中文名映射（用于提示词注入格式）
_FEATURE_TAG_LABELS = {
    "appearance": "外貌",
    "costume": "服饰",
    "hairstyle": "发型",
    "body_type": "体型",
    "style_tag": "画风",
}


async def _load_image_bytes(image_url: str) -> bytes:
    """按 URL 类型加载图像二进制内容。

    支持三种来源：
        - http:// / https:// 远程 URL：通过 httpx 异步下载；
        - /static/... 相对 URL：映射到后端静态目录（STATIC_ROOT）读取本地文件；
        - 其他格式：视为非法。

    Args:
        image_url: 图像访问地址（远程 URL 或 /static/... 相对路径）。

    Returns:
        bytes: 图像二进制内容。

    Raises:
        ValueError: 当 URL 为空/格式不支持、下载失败、HTTP 状态异常或本地文件缺失时抛出。
    """
    url = (image_url or "").strip()
    if not url:
        raise ValueError("图像 URL 为空，无法加载图像")

    if url.startswith("http://") or url.startswith("https://"):
        try:
            async with httpx.AsyncClient(timeout=_IMAGE_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise ValueError(f"图像下载失败 url={url}: {exc}") from exc
        if resp.status_code != 200:
            raise ValueError(f"图像下载返回非 200 状态 url={url}, status={resp.status_code}")
        return resp.content

    if url.startswith("/static/"):
        # 关键逻辑：将 /static/<subdir>/<file> 映射到 STATIC_ROOT 下的本地文件，
        # resolve 后校验仍位于静态根目录内，防止路径穿越
        relative = url[len("/static/"):].lstrip("/")
        file_path = (STATIC_ROOT / relative).resolve()
        if not str(file_path).startswith(str(STATIC_ROOT.resolve())):
            raise ValueError(f"非法的静态资源路径: {url}")
        if not file_path.is_file():
            raise ValueError(f"静态图像文件不存在: {file_path}")
        return file_path.read_bytes()

    raise ValueError(f"不支持的图像 URL 格式: {url}")


async def check_consistency(reference_image_url: str, candidate_image_url: str) -> dict:
    """对参照图与候选图进行真实图像相似度比对。

    下载两张图像后调用 image_sim.combined_similarity 计算
    aHash 结构相似度与 HSV 直方图相似度的加权综合得分。
    任何下载/解析失败都会抛出异常，绝不使用随机数伪造得分。

    Args:
        reference_image_url: 参照图 URL（如角色定妆照）。
        candidate_image_url: 候选图 URL（如重生成变体或关键帧）。

    Returns:
        dict: combined_similarity 的结果字典，含 hash_similarity /
            histogram_similarity / score / reference_hash / candidate_hash。

    Raises:
        ValueError: 当任一图像 URL 为空、格式不支持、下载失败或解码失败时抛出。
    """
    reference_bytes = await _load_image_bytes(reference_image_url)
    candidate_bytes = await _load_image_bytes(candidate_image_url)
    return combined_similarity(reference_bytes, candidate_bytes)


def build_consistent_prompt(base_prompt: str, feature_tags: dict) -> str:
    """将角色特征标签以固定格式后缀强注入图像生成提示词。

    仅注入非空的特征字段，按固定格式拼接一致性约束后缀，
    引导图像模型在多次生成中保持角色外貌/服饰/发型/体型/画风一致。
    feature_tags 为空或全部字段为空时返回原提示词。

    Args:
        base_prompt: 原始图像生成提示词。
        feature_tags: 角色特征标签字典（extract_feature_tags 的返回值）。

    Returns:
        str: 注入一致性约束后的提示词；无有效特征时与入参相同。
    """
    if not feature_tags or not isinstance(feature_tags, dict):
        return base_prompt

    parts = [
        f"{_FEATURE_TAG_LABELS[key]}：{str(feature_tags[key]).strip()}"
        for key in FEATURE_TAG_KEYS
        if feature_tags.get(key) and str(feature_tags.get(key)).strip()
    ]
    if not parts:
        return base_prompt

    suffix = f"【角色一致性约束】{'；'.join(parts)}。生成时必须严格保持上述角色特征前后一致。"
    return f"{base_prompt}，{suffix}"


def build_feature_card_text(char: dict) -> str:
    """构造角色特征卡文本段（无参考板角色的一致性约束兜底，方案 A5）。

    数据合并优先级：character_locks（不可变锚点）覆盖 feature_tags；
    仅保留 FEATURE_TAG_KEYS 白名单内的非空字段，按
    "{name}：外貌：…；服饰：…；发型：…；体型：…；画风：…" 格式输出。

    Args:
        char: 角色字典（含 name / character_locks / feature_tags）。

    Returns:
        str: 特征卡文本；无任何有效特征字段时仅返回角色名。
    """
    name = str(char.get("name", "")).strip() or "未命名角色"
    merged: dict = {}

    # 先并入 feature_tags（含 style_tag 画风标签）
    feature_tags = char.get("feature_tags")
    if isinstance(feature_tags, dict):
        for key in FEATURE_TAG_KEYS:
            value = feature_tags.get(key)
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()

    # 再并入 character_locks（不可变锚点优先级更高，覆盖同名 feature_tags 字段）
    locks = char.get("character_locks")
    if isinstance(locks, dict):
        for key in FEATURE_TAG_KEYS:
            value = locks.get(key)
            if value is not None and str(value).strip():
                merged[key] = str(value).strip()

    parts = [
        f"{_FEATURE_TAG_LABELS[key]}：{merged[key]}"
        for key in FEATURE_TAG_KEYS
        if key in merged
    ]
    if not parts:
        return name
    return f"{name}：{'；'.join(parts)}"


def resolve_storyboard_characters(sb: dict, characters: list[dict]) -> list[dict]:
    """解析分镜关联的角色列表（storyboard→characters 关联，方案 A5）。

    关联方式（按优先级）：
        1. sb["character_ids"]（Storyboard 表 character_ids JSON 列的 state
           形态）：按角色字典的 "id" 字段匹配（str/int 容错）；
        2. sb["character_names"]（字符串列表）：按角色名匹配；
        3. 均缺失：视为"全角色分镜"——storyboard_agent 生成的分镜提示词
           本身拼入全部角色名，语义上每个分镜涉及全部角色。

    Args:
        sb: 分镜字典（state.storyboards 中的一项）。
        characters: state.characters 角色列表。

    Returns:
        list[dict]: 关联角色列表。显式关联（方式 1/2）存在但匹配结果为空时
            返回空列表（调用方回退旧逻辑）；无显式关联字段时返回全部角色的浅拷贝。
    """
    sb_ids = sb.get("character_ids")
    if isinstance(sb_ids, (list, tuple)):
        if not sb_ids:
            return []
        wanted_ids: set[int] = set()
        for raw in sb_ids:
            try:
                wanted_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
        linked: list[dict] = []
        for char in characters:
            char_id = char.get("id")
            if char_id is None:
                continue
            try:
                if int(char_id) in wanted_ids:
                    linked.append(char)
            except (TypeError, ValueError):
                continue
        return linked

    sb_names = sb.get("character_names")
    if isinstance(sb_names, (list, tuple)):
        if not sb_names:
            return []
        wanted_names = {str(n).strip() for n in sb_names if str(n).strip()}
        return [
            char for char in characters
            if str(char.get("name", "")).strip() in wanted_names
        ]

    return list(characters)


async def extract_feature_tags(character_desc: str, llm: Optional[LLMClient] = None) -> dict:
    """调用文本大模型从角色描述中提取结构化特征标签。

    提取字段（JSON）：
        - appearance: 外貌特征；
        - costume: 服饰特征；
        - hairstyle: 发型特征；
        - body_type: 体型特征；
        - style_tag: 画风标签。

    解析结果仅保留白名单内且非空的字符串字段。
    任何失败（空描述、LLM 异常、JSON 解析失败）均返回空 dict，不向上抛出。

    Args:
        character_desc: 角色自然语言描述文本。
        llm: LLM 客户端实例；为 None 时使用 agnes Provider 的默认实例。

    Returns:
        dict: 特征标签字典（键为 FEATURE_TAG_KEYS 的子集）；失败时返回空 dict。
    """
    desc = (character_desc or "").strip()
    if not desc:
        return {}

    client = llm or get_llm("agnes")
    prompt = (
        "你是角色设定分析师。请从下面的角色描述中提取结构化特征标签，"
        "严格按照以下 JSON 格式输出（无法判断的字段填空字符串，不要输出任何其他内容）：\n"
        '{"appearance": "外貌特征", "costume": "服饰特征", "hairstyle": "发型特征", '
        '"body_type": "体型特征", "style_tag": "画风标签"}\n'
        f"角色描述：{desc}"
    )

    try:
        raw = await client.achat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[consistency_agent] 特征标签提取 LLM 调用失败: {exc}")
        return {}

    # 容错解析：剥离 markdown 代码块围栏后截取 JSON 主体
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(f"[consistency_agent] 特征标签 JSON 解析失败: {exc}, raw={text[:200]}")
        return {}

    if not isinstance(data, dict):
        return {}

    # 仅保留白名单内且非空的字符串字段
    tags: dict = {}
    for key in FEATURE_TAG_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            tags[key] = value.strip()
    return tags


def _hash_to_bits(hash_hex: str) -> list[int]:
    """将十六进制感知哈希转换为 64 位 0/1 特征向量（内部辅助函数）。

    用于写入 asset_variants.feature_vector（JSON 数组），保持与模型层
    "特征向量为 list" 的既有约定一致。

    Args:
        hash_hex: 16 字符十六进制感知哈希字符串。

    Returns:
        list[int]: 长度 64 的 0/1 列表，顺序与 aHash 二进制位一致。
    """
    return [int(bit) for bit in f"{int(hash_hex, 16):064b}"]


async def _persist_consistency_results(
    project_id: int,
    phase: str,
    reports: list[dict],
) -> None:
    """将一致性校验结果落库（内部辅助函数，独立数据库会话）。

    写入内容：
        - consistency_reports：每条带真实得分的报告一行，含真实 check_mode
          （报告缺失该字段时落 NULL，如资产阶段报告）；
        - asset_variants.feature_vector：资产校验阶段，将角色当前定妆照的
          aHash 64 位 0/1 向量写入该角色最新生成（DONE）的资产变体。

    说明：domain 层资产模块由其他任务并行修改中，为避免冲突，
    本函数在 Agent 内部使用 AsyncSessionLocal 独立会话写入，
    不复用也不修改 domains/ 下的代码，且不改变既有表结构。
    写入失败仅记录日志，不影响校验主流程。

    Args:
        project_id: 项目 ID；非正数时跳过写入（state 中无有效项目）。
        phase: 校验阶段（"asset" 或 "keyframe"）。
        reports: 校验报告列表（consistency_agent_node 产出的结构）。

    Returns:
        None

    Raises:
        无：任何数据库异常均捕获并降级为告警日志。
    """
    if project_id <= 0 or not reports:
        return

    try:
        async with AsyncSessionLocal() as session:
            # 1) 写入 consistency_reports
            for report in reports:
                score = report.get("similarity_score")
                if score is None:
                    # 下载失败等无真实得分的报告不落库
                    continue
                subject_type = (
                    ConsistencySubjectType.ASSET
                    if report.get("subject_type") == "asset"
                    else ConsistencySubjectType.KEYFRAME
                )
                action = ConsistencyAction(report.get("action", "pass"))
                # 真实 check_mode（ref_lock/feature_card/quality_gate），
                # 报告未携带时（如资产阶段报告）落 NULL
                raw_check_mode = report.get("check_mode")
                check_mode = (
                    str(raw_check_mode).strip() or None
                    if raw_check_mode is not None
                    else None
                )
                session.add(
                    ConsistencyReport(
                        project_id=project_id,
                        subject_type=subject_type,
                        subject_id=int(report.get("subject_id", 0) or 0),
                        ref_asset_id=0,
                        similarity_score=score,
                        threshold=SIMILARITY_THRESHOLD,
                        action=action,
                        check_mode=check_mode,
                    )
                )

            # 2) 资产校验阶段：回写 asset_variants.feature_vector（真实 aHash 特征向量）
            if phase == "asset":
                for report in reports:
                    candidate_hash = report.get("candidate_hash")
                    if not candidate_hash:
                        continue
                    name = report.get("subject_name", "")
                    result = await session.execute(
                        select(Character).where(
                            Character.project_id == project_id,
                            Character.name == name,
                        )
                    )
                    character = result.scalars().first()
                    if character is None:
                        continue
                    var_result = await session.execute(
                        select(AssetVariant)
                        .where(
                            AssetVariant.owner_type == AssetOwnerType.CHARACTER,
                            AssetVariant.owner_id == character.id,
                        )
                        .order_by(desc(AssetVariant.id))
                    )
                    # 优先回填最新 DONE 且带图像的变体，找不到则跳过
                    variant = next(
                        (
                            v
                            for v in var_result.scalars().all()
                            if v.status == AssetVariantStatus.DONE and v.image_url
                        ),
                        None,
                    )
                    if variant is not None:
                        variant.feature_vector = _hash_to_bits(candidate_hash)

            await session.commit()
            logger.info(
                f"[consistency_agent] 一致性结果已落库 project_id={project_id}, "
                f"reports={sum(1 for r in reports if r.get('similarity_score') is not None)}"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[consistency_agent] 一致性结果落库失败 project_id={project_id}: {exc}")


def _resolve_subject_id(characters: list[dict], name: str) -> int:
    """从角色列表中定位角色的数据库 ID（内部辅助函数）。

    Args:
        characters: state 中的角色列表。
        name: 角色名。

    Returns:
        int: 角色 DB ID；state 中未携带 ID 时返回 0（DB 写入时的占位值）。
    """
    for char in characters:
        if char.get("name") == name and char.get("id"):
            return int(char["id"])
    return 0


async def consistency_agent_node(state: ProductionState) -> dict:
    """一致性校验节点。

    使用真实图像相似度（aHash + HSV 直方图加权）替换随机数假数据：
        - 资产校验：比对角色参照定妆照与当前生成定妆照；
        - 关键帧校验（方案 A5/A6）：按分镜关联角色逐角色比对——
          参照优先取角色参考板（ref_board_url），其次定妆照（main_asset_url 等），
          每个角色一条报告并标注 check_mode（ref_lock/feature_card/quality_gate）；
          分镜无关联角色时回退旧行为（首个带定妆照角色作全局参照）；
        - 综合得分低于 SIMILARITY_THRESHOLD 时判定 regenerate
          （ref_lock 模式除外：参考板即锁定机制，低分记 manual 不自动重生成）；
        - 比对无法进行（缺参照图/图像加载失败）时判定 manual 并记录原因。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 consistency 与 stage 的状态增量；consistency 含
            threshold / all_pass / need_regenerate / reports。

    Raises:
        无：单条比对失败均降级为 manual 报告，不中断整体流程。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")

    characters = state.get("characters", []) or []
    storyboards = state.get("storyboards", []) or []

    # 判断本次一致性校验属于哪个阶段：
    # 若分镜已有关键帧 URL，则为关键帧校验（下游应为 video）；
    # 否则为资产校验（下游应为 storyboard）。
    has_keyframes = any(sb.get("keyframe_url") for sb in storyboards)
    phase = "keyframe" if has_keyframes else "asset"

    logger.info(f"[consistency_agent] 开始一致性校验 project_id={project_id}, phase={phase}")

    reports: list[dict] = []

    def _build_report(
        subject_type: str,
        subject_name: str,
        score: Optional[float],
        action: str,
        **extra: Any,
    ) -> dict:
        """构造单条校验报告并追加到 reports 列表（内部辅助函数）。

        Args:
            subject_type: 校验对象类型（"asset" / "keyframe"）。
            subject_name: 校验对象名称。
            score: 综合相似度得分；无法比对时为 None。
            action: 处置动作（"pass" / "regenerate" / "manual"）。
            **extra: 附加字段（subject_id / candidate_hash / error 等）。

        Returns:
            dict: 构造完成的报告字典（同时已追加进 reports）。
        """
        report = {
            "subject_type": subject_type,
            "subject_name": subject_name,
            "similarity_score": score,
            "threshold": SIMILARITY_THRESHOLD,
            "action": action,
            **extra,
        }
        reports.append(report)
        return report

    # 校验角色资产：参照 = 角色参照定妆照，候选 = 当前生成定妆照
    for char in characters:
        name = char.get("name", "")
        reference_url = char.get("main_asset_url") or char.get("reference_image_url")
        candidate_url = char.get("image_url")

        if not candidate_url:
            _build_report("asset", name, None, "manual", error="缺少候选定妆照，无法比对")
            continue
        if not reference_url:
            _build_report(
                "asset", name, None, "pass",
                subject_id=_resolve_subject_id(characters, name),
                note="无可比参照图，跳过相似度计算",
            )
            continue

        try:
            result = await check_consistency(reference_url, candidate_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[consistency_agent] 角色 {name} 图像比对失败: {exc}")
            _build_report(
                "asset", name, None, "manual",
                subject_id=_resolve_subject_id(characters, name),
                error=f"图像比对失败: {exc}",
            )
            continue

        score = result["score"]
        action = "pass" if score >= SIMILARITY_THRESHOLD else "regenerate"
        _build_report(
            "asset", name, score, action,
            subject_id=_resolve_subject_id(characters, name),
            hash_similarity=result["hash_similarity"],
            histogram_similarity=result["histogram_similarity"],
            candidate_hash=result["candidate_hash"],
        )

    # 校验关键帧（方案 A5/A6）：优先按分镜关联角色逐角色比对——
    # 每个角色的 ref_board_url / main_asset_url 各自与关键帧比对并各出一条
    # 报告（subject_name="分镜#N·角色名"）；分镜解析不出关联角色时回退旧行为：
    # 首个带定妆照的角色作全局参照（保持旧字段兼容）。
    fallback_reference_char = next((c for c in characters if c.get("image_url")), None)
    for sb in storyboards:
        board_label = f"分镜#{sb.get('sequence', '')}"
        candidate_url = sb.get("keyframe_url")

        if not candidate_url:
            _build_report(
                "keyframe", board_label, None, "manual",
                error="缺少关键帧图像，无法比对", check_mode="quality_gate",
            )
            continue

        linked_chars = resolve_storyboard_characters(sb, characters)
        if not linked_chars:
            # 回退旧逻辑：全局单参照比对（check_mode=feature_card）
            if fallback_reference_char is None:
                _build_report(
                    "keyframe", board_label, None, "pass",
                    note="无角色定妆照可作参照，跳过相似度计算", check_mode="quality_gate",
                )
                continue
            try:
                result = await check_consistency(fallback_reference_char.get("image_url"), candidate_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[consistency_agent] {board_label} 关键帧比对失败: {exc}")
                _build_report(
                    "keyframe", board_label, None, "manual",
                    error=f"图像比对失败: {exc}", check_mode="feature_card",
                )
                continue
            score = result["score"]
            action = "pass" if score >= SIMILARITY_THRESHOLD else "regenerate"
            _build_report(
                "keyframe", board_label, score, action,
                hash_similarity=result["hash_similarity"],
                histogram_similarity=result["histogram_similarity"],
                check_mode="feature_card",
            )
            continue

        # 逐角色比对：读取 keyframe_agent 写入分镜的参考图消费标记
        ref_count = int(sb.get("ref_count") or 0)
        ref_dropped = bool(sb.get("ref_dropped"))
        # 关键判定：Provider 真实消费了参考图（有参考图注入且未被降级丢弃）
        refs_consumed = ref_count > 0 and not ref_dropped
        ref_names = set(sb.get("ref_character_names") or [])
        multi = len(linked_chars) > 1

        for char in linked_chars:
            char_name = str(char.get("name", "")).strip() or "未命名角色"
            subject_label = f"{board_label}·{char_name}" if multi else board_label
            ref_board_url = str(char.get("ref_board_url") or "").strip()
            # 参照优先级：参考板 > 主定妆照 > 当前定妆照 > 参照定妆照
            reference_url = (
                ref_board_url
                or char.get("main_asset_url")
                or char.get("image_url")
                or char.get("reference_image_url")
            )

            # A6 check_mode 判定：
            #   ref_lock     - 角色参考板在生成时真实注入且未被 Provider 丢弃；
            #   feature_card - 参考图未生效/未注入，用特征卡/定妆照作参照比对；
            #   quality_gate - 无任何可用参照，仅做基础质检。
            is_ref_lock = bool(ref_board_url) and char_name in ref_names and refs_consumed
            check_mode = "ref_lock" if is_ref_lock else ("feature_card" if reference_url else "quality_gate")

            if check_mode == "quality_gate":
                _build_report(
                    "keyframe", subject_label, None, "pass",
                    note=f"角色 {char_name} 无可用参照图，仅做基础质检", check_mode=check_mode,
                )
                continue

            try:
                result = await check_consistency(reference_url, candidate_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[consistency_agent] {subject_label} 关键帧比对失败（{check_mode}）: {exc}")
                _build_report(
                    "keyframe", subject_label, None, "manual",
                    error=f"图像比对失败: {exc}", check_mode=check_mode,
                )
                continue

            score = result["score"]
            extra: dict = {
                "hash_similarity": result["hash_similarity"],
                "histogram_similarity": result["histogram_similarity"],
                "check_mode": check_mode,
            }
            if check_mode == "ref_lock":
                # 关键降级语义（A6）：ref_lock 模式下参考板参考图已在生成时真实注入，
                # 参考板本身就是一致性锁定机制，比对得分仅作质检参考；
                # 低于阈值时记为 manual 提示人工关注，但【不自动重生成】——
                # 重生成由用户手动触发，避免自动流程推翻已锁定的一致性基准。
                action = "pass" if score >= SIMILARITY_THRESHOLD else "manual"
                if action == "manual":
                    extra["note"] = "参考图锁定模式：得分低于阈值仅记录，不自动重生成，如需重生成请手动触发"
            else:
                # feature_card 模式：保留既有阈值重生成逻辑
                action = "pass" if score >= SIMILARITY_THRESHOLD else "regenerate"
            _build_report("keyframe", subject_label, score, action, **extra)

    # 汇总：低于阈值（action == regenerate）即要求重新生成
    need_regenerate = any(r["action"] == "regenerate" for r in reports)
    all_pass = all(r["action"] == "pass" for r in reports) if reports else True

    consistency = {
        "threshold": SIMILARITY_THRESHOLD,
        "all_pass": all_pass,
        "need_regenerate": need_regenerate,
        "reports": reports,
    }

    # 结果落库（独立会话，失败不影响主流程）
    await _persist_consistency_results(project_id, phase, reports)

    # 根据校验阶段决定下一阶段
    next_stage = "video" if phase == "keyframe" else "storyboard"

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="consistency_agent",
        input_digest=f"characters={len(characters)}, storyboards={len(storyboards)}",
        output_digest=truncate_digest(consistency),
    )

    return {"consistency": consistency, "stage": next_stage}
