"""
i2i 恢复自动复测脚本（项目开发文档 09 号 R15 挂起型任务，永久保留）。

【用途】
    Agnes 图像网关（apihub.agnes-ai.com）的 i2i 通道当前不可用：
    POST /images/generations 携带 JSON "image": "<base64>" 字段时被网关
    分流到独立 i2i 队列，返回 503 "image queue is full"（纯 t2i 同时刻
    正常 200）。providers/image/agnes.py 已实现「i2i 优先 → 降级 t2i」，
    队列恢复后业务链路自动生效，无需改代码。本脚本供定时任务每日运行，
    自动盯梢 i2i 队列恢复情况：

        1. probe_i2i()：探测 i2i 通道是否恢复——Pillow 生成 512x512
           测试图 → base64 → POST images/generations（JSON 携带
           "image" 字段，Bearer 图像 Key）；未恢复 → 打印单行状态退出；
        2. run_reflock_retest()：恢复后按 08 号文档 §7.2 局限 2 执行
           两项复测并写报告 services/api/logs/i2i_probe_report.md——
              ① ref_lock 真实触发：以项目真实参考板（characters 表
                 ref_board_url，取不到则临时生成角色参考图）为参考，
                 ref_images=[{"data": <base64>, "mime": "image/png"}]
                 走 AgnesImageProvider 真实生图，断言 last_ref_dropped=False；
              ② 同角色跨镜头得分：同一参考图 + 两个不同镜头提示词各
                 生成一张图，下载产物后用 app/utils/image_sim 的
                 combined_similarity（aHash 0.6 + HSV 直方图 0.4）对比，
                 判断是否显著高于本轮 0.48–0.58 基线
                 （即 07 号文档 §3.2 正式验收的前置数据）。

【用法】
    # 工作目录任意（脚本内部自动把 services/api 加入 sys.path），
    # 建议由定时任务每日执行：
    e:/Class Project/ai漫剧/services/api/.venv/Scripts/python.exe ^
        "e:/Class Project/ai漫剧/services/api/scripts/probe_i2i_queue.py"

    每次运行追加一行执行痕迹到 services/api/logs/i2i_probe_history.log，
    作为定时任务「第一次执行已发生」的日志凭证。

【退出码】
    0 = 未恢复（仅完成探测，未执行复测）
    1 = 已恢复但复测过程异常（报告可能不完整）
    2 = 已恢复且复测完成（报告已写入，无论指标是否达标）

【设计约束】
    - 全程异常捕获，脚本永不崩溃（定时任务无人值守友好）；
    - 不修改 app/ 业务代码，仅只读调用 settings / AgnesImageProvider /
      combined_similarity 等公开接口；
    - MySQL 不可达时参考图自动回退为临时生成的角色图，不阻塞复测；
    - 配置优先经 app.core.config.settings 读取，app 包导入失败时回退为
      直接解析项目根 .env，保证脚本自包含可独立运行。
"""

import asyncio
import base64
import io
import sys
from datetime import datetime
from pathlib import Path

# ---- 路径自举：保证任意 cwd 运行都能导入 app 包与定位相对资源 ----
API_ROOT = Path(__file__).resolve().parents[1]  # services/api
PROJECT_ROOT = API_ROOT.parent.parent  # 项目根（ai漫剧）
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

# ---- 常量 ----
# 复测报告输出路径（仅 i2i 恢复并执行复测后写入，覆盖保留最新一次）
REPORT_PATH = API_ROOT / "logs" / "i2i_probe_report.md"
# 每次运行的执行痕迹日志（定时任务首次执行的日志凭证）
HISTORY_LOG_PATH = API_ROOT / "logs" / "i2i_probe_history.log"
# app 包不可用时的 .env 回退路径
ENV_FILE_PATH = PROJECT_ROOT / ".env"

PROBE_SIZE = 512  # 探测用测试图边长（像素），任务约定 512x512
RETEST_SIZE = 1024  # 复测生成图边长（与业务默认生成分辨率一致）
REQUEST_TIMEOUT = 60.0  # 探测/下载请求超时（秒）
DB_QUERY_TIMEOUT = 15.0  # 查询真实参考板的数据库超时（秒），超时回退临时图
BASELINE_SCORE = 0.58  # 本轮同角色跨镜头综合得分基线上限（基线区间 0.48–0.58）
SIGNIFICANT_MARGIN = 0.12  # 「显著高于基线」判定余量（得分 ≥ 基线 + 余量，即 ≥ 0.70）

# 复测镜头提示词（同一参考图 + 两个不同镜头，模拟 keyframe_agent 的
# {{ref N}} 参考板协议 + Immutable locks 统一尾注）
_RETEST_PROMPTS = (
    (
        "校园天台傍晚，女主望向远方夕阳，半身镜头。"
        "{{ref 1}}：角色外观与参考板完全一致。"
        "Immutable locks：服装、发型、画风与参考图严格一致。"
    ),
    (
        "夜晚教室窗边，女主低头看书，侧面特写。"
        "{{ref 1}}：角色外观与参考板完全一致。"
        "Immutable locks：服装、发型、画风与参考图严格一致。"
    ),
)


def _load_agnes_config() -> tuple[str, str, str]:
    """读取 Agnes 图像网关配置（base_url / api_key / model）。

    优先经 app.core.config.settings 读取（pydantic-settings 加载项目根
    .env）；app 包导入失败时回退为直接解析 .env 文件，保证脚本自包含。

    Returns:
        tuple[str, str, str]: (base_url, image_api_key, image_model)，
            未配置项为空字符串；model 缺省 "agnes-image-2.5-flash"。

    Raises:
        OSError: 回退路径下 .env 文件读取失败时抛出（由调用方捕获归入
            「未恢复」）。
    """
    try:
        # 延迟导入：probe 分支不强依赖 app 包，包损坏时仍可走 .env 回退
        from app.core.config import settings

        return (
            (settings.AGNES_BASE_URL or "").rstrip("/"),
            settings.AGNES_IMAGE_API_KEY or "",
            settings.AGNES_IMAGE_MODEL or "agnes-image-2.5-flash",
        )
    except Exception:  # noqa: BLE001 —— app 包不可用时回退手动解析 .env
        config: dict[str, str] = {}
        for raw_line in ENV_FILE_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip().strip('"').strip("'")
        return (
            config.get("AGNES_BASE_URL", "").rstrip("/"),
            config.get("AGNES_IMAGE_API_KEY", ""),
            config.get("AGNES_IMAGE_MODEL", "agnes-image-2.5-flash"),
        )


def _make_test_image_base64(size: int = PROBE_SIZE) -> str:
    """用 Pillow 生成探测用测试图并编码为裸 base64（PNG）。

    生成「纵向渐变 + 白色圆形」的合成图（非纯色），贴近真实生成图的
    特征分布，避免网关对退化输入的异常处理干扰探测结论。

    Args:
        size: 图像边长（像素），默认 PROBE_SIZE（512）。

    Returns:
        str: PNG 二进制的裸 base64 字符串。

    Raises:
        Exception: Pillow 绘图/编码异常（由调用方捕获归入「未恢复」）。
    """
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):  # 纵向渐变底色
        c = y * 255 // size
        draw.line([(0, y), (size, y)], fill=(c, 255 - c, 128))
    radius = size // 4  # 中心白色圆形（提供结构特征）
    draw.ellipse(
        [size // 2 - radius, size // 2 - radius, size // 2 + radius, size // 2 + radius],
        fill=(255, 255, 255),
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def probe_i2i() -> dict:
    """探测 Agnes 图像网关 i2i 通道是否恢复。

    生成 512x512 测试图 → base64 → POST {base}/images/generations，
    JSON 体携带 {"image": <base64>, "prompt": ..., "model": ...}，
    Bearer 认证使用图像 Key。网关识别 "image" 字段后分流到独立 i2i
    队列：200=恢复，503/4xx=未恢复，网络异常=未恢复。

    Returns:
        dict: {"recovered": bool, "status": int | None, "detail": str}。
            status 为 None 表示网络层异常（未收到 HTTP 响应）。

    说明:
        配置缺失 / 网络异常 / 响应解析异常均在本函数内消化并归入
        「未恢复」，永不向外抛出（定时任务友好）。
    """
    result: dict = {"recovered": False, "status": None, "detail": ""}
    try:
        base_url, api_key, model = _load_agnes_config()
        if not base_url or not api_key:
            result["detail"] = "未配置 AGNES_BASE_URL / AGNES_IMAGE_API_KEY"
            return result

        image_b64 = _make_test_image_base64()
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{base_url}/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "image": image_b64,
                    "prompt": "a cute orange cat sitting on grass, cartoon style",
                    "model": model,
                },
            )

        result["status"] = resp.status_code
        if resp.status_code == 200:
            # 200 即视为 i2i 队列恢复（网关仅在该通道不可用时返回 5xx）
            result["recovered"] = True
        # 响应要点：优先提取产物 URL，其余截断正文便于排查
        try:
            data = resp.json().get("data") or []
            result["detail"] = (data[0].get("url") or resp.text[:200]) if data else resp.text[:200]
        except Exception:  # noqa: BLE001 —— 响应结构变化不影响恢复判定
            result["detail"] = resp.text[:200]
        return result
    except Exception as exc:  # noqa: BLE001 —— 网络异常/超时统一归入「未恢复」
        result["status"] = None
        result["detail"] = f"{type(exc).__name__}: {exc}"[:200]
        return result


def _static_url_to_local(url: str) -> Path | None:
    """把 /static/... 相对访问 URL 映射为 services/api/static/ 本地路径。

    Args:
        url: 产物/参考板访问 URL（如 /static/references/xxx.png）。

    Returns:
        Path | None: 本地文件路径；http(s) 绝对 URL 或非 /static/ 前缀
            返回 None。
    """
    if not url or not url.startswith("/static/"):
        return None
    return API_ROOT / "static" / url.removeprefix("/static/")


async def _download_artifact(url: str) -> bytes:
    """下载（或本地读取）Provider 产物图像二进制。

    Args:
        url: 产物地址。/static/... 相对 URL 直接读本地静态目录；
            http(s) URL 用 httpx 下载（60 秒超时，跟随重定向）。

    Returns:
        bytes: 图像二进制内容。

    Raises:
        RuntimeError: 本地文件缺失、URL 形态无法识别或下载非 200 时抛出。
        httpx.HTTPError: 网络层异常（超时、连接失败等）向上透传。
    """
    local = _static_url_to_local(url)
    if local is not None:
        if not local.exists():
            raise RuntimeError(f"本地静态产物不存在: {local}")
        return local.read_bytes()

    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError(f"无法识别的产物地址: {url[:120]}")

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"产物下载失败 HTTP {resp.status_code}: {url[:120]}")
    return resp.content


def _make_placeholder_ref_image() -> bytes:
    """临时生成一张「角色参考图」（库中无可用真实参考板时的回退）。

    合成 512x512 非纯色图（渐变底 + 圆形头部 + 矩形身体 + 面部特征），
    保证 i2i 参考与跨镜头相似度计算有结构与色彩特征可依。

    Returns:
        bytes: PNG 二进制内容。

    Raises:
        Exception: Pillow 绘图/编码异常（由调用方捕获回退）。
    """
    size = 512
    img = Image.new("RGB", (size, size), (240, 228, 208))
    draw = ImageDraw.Draw(img)
    for y in range(size):  # 暖色纵向渐变底
        c = y * 60 // size
        draw.line([(0, y), (size, y)], fill=(240 - c, 228 - c, 208 - c))
    # 简化角色轮廓：头部 + 身体 + 双眼 + 嘴（供 i2i 保持身份特征）
    draw.ellipse([176, 64, 336, 224], fill=(255, 224, 189), outline=(60, 40, 30), width=4)
    draw.rectangle([166, 236, 346, 460], fill=(70, 110, 200), outline=(30, 50, 100), width=4)
    draw.rectangle([196, 96, 236, 136], fill=(40, 40, 40))  # 左眼
    draw.rectangle([276, 96, 316, 136], fill=(40, 40, 40))  # 右眼
    draw.arc([216, 140, 296, 200], start=20, end=160, fill=(150, 60, 40), width=6)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


async def _fetch_real_ref_board() -> tuple[bytes, str] | None:
    """从 characters 表取最新一张四视图参考板作为复测参考图。

    查询 ref_board_url 非空的最新角色记录，把 /static/... 相对 URL 映射
    到 services/api/static/ 本地文件读取；无记录或文件缺失返回 None。

    Returns:
        tuple[bytes, str] | None: (参考板图像二进制, 角色名)；无可用数据
            返回 None。

    Raises:
        Exception: 数据库连接失败 / 查询异常 / asyncio.wait_for 超时均
            向上透出，由调用方捕获后回退临时参考图。
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models import Character

    async def _query() -> tuple[bytes, str] | None:
        """执行参考板查询与本地读取（内部辅助协程）。

        Returns:
            tuple[bytes, str] | None: (参考板二进制, 角色名)；无可用数据
                返回 None。
        """
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(Character.name, Character.ref_board_url)
                    .where(Character.ref_board_url.isnot(None))
                    .order_by(Character.id.desc())
                    .limit(1)
                )
            ).first()
        if not row:
            return None
        name, ref_url = row[0], (row[1] or "").strip()
        local_path = _static_url_to_local(ref_url)
        if local_path is not None and local_path.exists():
            return local_path.read_bytes(), name
        return None

    # 超时兜底：MySQL 未启动时连接可能长时间挂起，wait_for 强制回退
    return await asyncio.wait_for(_query(), timeout=DB_QUERY_TIMEOUT)


async def run_reflock_retest() -> dict:
    """i2i 恢复后执行两项一致性复测（08 号文档 §7.2 局限 2）。

    复测① ref_lock 真实触发：项目真实参考板（取不到则临时生成角色图）
    经 ref_images=[{"data": <base64>, "mime": "image/png"}] 走
    AgnesImageProvider 真实生图，检查 last_ref_dropped=False（参考图被
    网关真实消费，ref_lock 模式真实触发）。

    复测② 同角色跨镜头得分：同一参考图 + 两个不同镜头提示词各生成一张
    图，下载产物后用 combined_similarity（aHash*0.6 + HSV*0.4）对比，
    判断是否显著高于本轮 0.48–0.58 基线。

    Returns:
        dict: 复测数据（任何一步异常不向外抛，记入 "error" 字段）：
            - ref_source (str): 参考图来源描述；
            - ref_dropped (list[bool]): 两次生成的 last_ref_dropped；
            - ref_lock_triggered (bool): 两次生成参考图均被真实消费；
            - generated_urls (list[str]): 两次生成的产物 URL（失败位空串）；
            - similarity (dict | None): combined_similarity 结果；
            - baseline (float): 基线上限 0.58；
            - above_baseline (bool): 得分高于基线；
            - significantly_above (bool): 得分 ≥ 基线 + 0.12（≥ 0.70 视为显著）；
            - error (str | None): 过程异常摘要（无异常为 None）。
    """
    result: dict = {
        "ref_source": "",
        "ref_dropped": [],
        "ref_lock_triggered": False,
        "generated_urls": [],
        "similarity": None,
        "baseline": BASELINE_SCORE,
        "above_baseline": False,
        "significantly_above": False,
        "error": None,
    }
    try:
        # ---- 准备参考图：优先项目真实参考板，取不到回退临时生成 ----
        ref_bytes: bytes | None = None
        try:
            fetched = await _fetch_real_ref_board()
            if fetched:
                ref_bytes, ref_name = fetched
                result["ref_source"] = f"characters 表参考板（角色：{ref_name}）"
        except Exception as exc:  # noqa: BLE001 —— MySQL 未启动等场景自动回退
            result["ref_source"] = f"临时生成参考图（真实参考板获取失败: {type(exc).__name__}）"
        if ref_bytes is None:
            if not result["ref_source"]:
                result["ref_source"] = "临时生成参考图（库中无 ref_board_url 记录）"
            ref_bytes = _make_placeholder_ref_image()
        ref_b64 = base64.b64encode(ref_bytes).decode("ascii")

        # ---- 走 Agnes Provider 真实生图（i2i 恢复时参考图被真实消费）----
        from app.providers.image.agnes import AgnesImageProvider
        from app.utils.image_sim import combined_similarity

        provider = AgnesImageProvider()
        urls: list[str] = []
        for prompt in _RETEST_PROMPTS:
            url = await provider.generate(
                prompt,
                ref_images=[{"data": ref_b64, "mime": "image/png"}],
                params={"width": RETEST_SIZE, "height": RETEST_SIZE},
            )
            # 关键：last_ref_dropped 只反映最近一次 generate，须逐次即时读取
            result["ref_dropped"].append(bool(provider.last_ref_dropped))
            urls.append(url or "")
        result["generated_urls"] = urls
        result["ref_lock_triggered"] = len(urls) == 2 and not any(result["ref_dropped"])

        # ---- 同角色跨镜头相似度（两次 i2i 均成功时才有对比意义）----
        if result["ref_lock_triggered"]:
            img1 = await _download_artifact(urls[0])
            img2 = await _download_artifact(urls[1])
            sim = combined_similarity(img1, img2)
            result["similarity"] = sim
            score = float(sim["score"])
            result["above_baseline"] = score > BASELINE_SCORE
            result["significantly_above"] = score >= BASELINE_SCORE + SIGNIFICANT_MARGIN
    except Exception as exc:  # noqa: BLE001 —— 复测异常不向外抛，记入 error 字段
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return result


def _write_report(probe: dict, retest: dict | None) -> None:
    """把探测与复测结果写入 logs/i2i_probe_report.md（覆盖写保留最新）。

    报告含：生成时间、探测结果、两项复测数据、与基线对比结论、
    是否可启动 07 号文档 §3.2 正式验收。

    Args:
        probe: probe_i2i() 的返回结果。
        retest: run_reflock_retest() 的返回结果；None 表示未执行复测。

    Returns:
        None

    Raises:
        OSError: 报告写入失败时由内部捕获吞掉（不影响退出码语义）。
    """
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        base_url, _, model = _load_agnes_config()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines: list[str] = [
            "# i2i 恢复复测报告（09 号文档 R15）",
            "",
            f"- 生成时间：{now}",
            f"- 网关：{base_url or '（未配置）'}（模型 {model}）",
            "",
            "## 一、i2i 队列探测",
            "",
            "- 请求：POST images/generations（JSON \"image\" 字段，512x512 测试图）",
            f"- 结果：HTTP {probe.get('status')}，recovered={probe.get('recovered')}",
            f"- 响应要点：{probe.get('detail')}",
            "",
        ]

        if retest is None:
            lines += ["## 二、一致性复测", "", "- 未执行（探测未恢复）", ""]
        else:
            dropped = retest.get("ref_dropped") or []
            lines += [
                "## 二、一致性复测（08 号文档 §7.2 局限 2）",
                "",
                "### ① ref_lock 真实触发",
                "",
                f"- 参考图来源：{retest.get('ref_source')}",
                '- ref_images 协议：[{"data": <base64>, "mime": "image/png"}]',
                f"- last_ref_dropped（两次生成）：{dropped}",
                "- 结论："
                + (
                    "ref_lock 模式真实触发（参考图被网关真实消费，未降级 t2i/mock）"
                    if retest.get("ref_lock_triggered")
                    else "参考图未被真实消费（发生降级），ref_lock 未真实触发"
                ),
                "- 生成产物：",
            ]
            for idx, url in enumerate(retest.get("generated_urls") or [], 1):
                lines.append(f"  - 镜头 {idx}：{url or '（生成失败）'}")
            lines.append("")

            lines += [
                "### ② 同角色跨镜头得分（combined_similarity = aHash*0.6 + HSV*0.4）",
                "",
            ]
            sim = retest.get("similarity")
            if sim:
                lines += [
                    f"- hash_similarity：{sim.get('hash_similarity')}",
                    f"- histogram_similarity：{sim.get('histogram_similarity')}",
                    f"- 综合得分：**{sim.get('score')}**",
                    f"- 本轮基线：0.48–0.58（上限 {BASELINE_SCORE}，显著线 "
                    f"{BASELINE_SCORE + SIGNIFICANT_MARGIN:.2f}）",
                    "- 与基线对比："
                    + (
                        "显著高于基线"
                        if retest.get("significantly_above")
                        else ("高于基线但未达显著线" if retest.get("above_baseline") else "未高于基线")
                    ),
                ]
            else:
                lines.append(
                    f"- 未产生有效得分（ref_lock 未触发或复测异常：{retest.get('error')}）"
                )
            lines.append("")

        ready = bool(
            retest is not None
            and retest.get("ref_lock_triggered")
            and retest.get("significantly_above")
        )
        lines += [
            "## 三、结论",
            "",
            f"- i2i 通道：{'已恢复' if probe.get('recovered') else '未恢复'}",
            f"- ref_lock 真实触发：{'是' if retest and retest.get('ref_lock_triggered') else '否'}",
            f"- 跨镜头得分显著高于基线：{'是' if retest and retest.get('significantly_above') else '否'}",
            "- 是否可启动 07 号文档 §3.2 正式验收（≥6 镜头一致率 ≥80%）："
            + (
                "可以——请按 07 §3.2 组织 ≥6 镜头人工评审"
                if ready
                else "暂不可——i2i 通道或复测指标未达标，待下次探测"
            ),
            "",
        ]
        REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    except Exception:  # noqa: BLE001 —— 报告写入失败不影响主流程与退出码
        pass


def _append_history(line: str) -> None:
    """追加一行执行痕迹到 logs/i2i_probe_history.log（自动补时间戳）。

    该日志是定时任务「第一次执行已发生」的凭证；写入失败静默忽略，
    不影响主流程。

    Args:
        line: 单行内容（不含时间戳前缀，函数自动追加）。

    Returns:
        None
    """
    try:
        HISTORY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with HISTORY_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {line}\n")
    except Exception:  # noqa: BLE001 —— 痕迹写入失败不影响主流程
        pass


async def main() -> int:
    """脚本主入口：先探测；未恢复打印单行状态，恢复则复测并写报告。

    Returns:
        int: 退出码——0=未恢复；1=已恢复但复测异常；2=复测完成。

    Raises:
        Exception: 理论上不外抛（probe_i2i / run_reflock_retest 内部全
            捕获，报告与痕迹写入各自吞异常）；仅作为最后防线由
            __main__ 块兜底。
    """
    probe = await probe_i2i()

    if not probe["recovered"]:
        status = probe["status"] if probe["status"] is not None else "unreachable"
        detail = probe["detail"] or "-"
        print(f"[i2i-probe] 未恢复 status={status}（纯 t2i 正常） detail={detail}")
        _append_history(f"未恢复 status={status} detail={detail}")
        return 0

    print(f"[i2i-probe] 已恢复 status={probe['status']}，开始执行两项复测 ...")
    retest = await run_reflock_retest()
    _write_report(probe, retest)

    if retest.get("error"):
        print(f"[i2i-probe] 复测执行异常：{retest['error']}（报告可能不完整）")
        _append_history(f"已恢复 status={probe['status']}，复测异常：{retest['error']}")
        return 1

    sim = retest.get("similarity") or {}
    score = sim.get("score", "-")
    print(
        f"[i2i-probe] 复测完成 ref_lock_triggered={retest['ref_lock_triggered']} "
        f"cross_shot_score={score}（基线上限 {BASELINE_SCORE}，"
        f"显著线 {BASELINE_SCORE + SIGNIFICANT_MARGIN:.2f}）"
    )
    print(f"[i2i-probe] 报告已写入：{REPORT_PATH}")
    _append_history(
        f"已恢复 status={probe['status']}，复测完成 ref_lock_triggered="
        f"{retest['ref_lock_triggered']} score={score}"
    )
    return 2


if __name__ == "__main__":
    # Windows 控制台/重定向场景的中文输出兜底（GBK 环境降级替换不崩溃）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 老 Python/非常规终端忽略
        pass
    try:
        sys.exit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 —— 最后防线：脚本永不崩溃
        print(f"[i2i-probe] 未恢复 status=script-error（脚本异常: {type(exc).__name__}: {exc}）")
        sys.exit(0)
