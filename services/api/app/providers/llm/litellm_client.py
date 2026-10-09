"""
LLM 客户端模块。

基于 litellm 提供统一的大模型调用接口，默认使用 DeepSeek 作为底层模型。

调用策略（重要）：
    1. 先走 litellm.acompletion —— 模型标识必须带厂商前缀
       （deepseek/xxx、openai/xxx），否则 litellm 会抛
       `BadRequestError: LLM Provider NOT provided`；
    2. litellm 失败（或未安装）时，若 settings.LLM_ENABLE_HTTP_FALLBACK 为真，
       改用直连该网关 OpenAI 兼容的 /v1/chat/completions 接口重试一次；
    3. 两条路径都失败时抛出 BizException(AI_ERROR)，把真实失败原因暴露给调用方。
       只有在显式打开 settings.LLM_ALLOW_MOCK_FALLBACK 时才会降级为 mock 占位文本，
       避免历史上"调用失败却静默返回与用户输入无关的假剧本"的问题。

运行时凭证解析优先级：项目级 model_configs 配置 > 用户级 model_configs 配置
（AES 加密存储，经 resolve_llm_settings 解密读取）> .env 凭证。
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Optional

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.core.security import aes_decrypt
from app.models import ModelCapability, ModelConfig

logger = get_logger()

# 尝试导入 litellm；失败则依赖直连 HTTP 兜底（而非 mock）
try:  # pragma: no cover - 依赖环境
    import litellm  # type: ignore

    _HAS_LITELLM = True
except Exception:  # noqa: BLE001
    litellm = None  # type: ignore
    _HAS_LITELLM = False

# 视为"未配置"的占位 Key，命中时回退 .env 凭证
_PLACEHOLDER_API_KEYS = {
    "",
    "your-deepseek-api-key",
    "your-api-key",
    "your_key",
    "sk-xxx",
    "changeme",
}

# model_configs 中未绑定具体模型的占位名（用户在 API Key 管理里只填了 Key）
_PLACEHOLDER_MODEL_NAMES = {"", "user-key", "default", "none"}

# litellm 厂商前缀：缺少前缀会被 litellm 判定为 "LLM Provider NOT provided"
_LITELLM_PREFIX = {"deepseek": "deepseek/", "agnes": "openai/"}

# 直连 OpenAI 兼容接口的超时时间（秒）
_HTTP_TIMEOUT = 120.0


def _normalize_api_base(api_base: Optional[str]) -> str:
    """规范化 API 基础地址，去掉尾部斜杠。

    Args:
        api_base: 原始地址，可能为 None 或带尾斜杠。

    Returns:
        str: 规范化后的地址，空配置时返回空字符串。
    """
    return (api_base or "").strip().rstrip("/")


def _strip_prefix(model_name: str) -> str:
    """去掉模型名中可能携带的厂商前缀，返回裸模型名。

    兼容用户在模型配置里手写 "deepseek/deepseek-flash"、"openai/agnes-3.0-flash"
    等带前缀写法，避免出现 "deepseek/deepseek/deepseek-flash" 这类重复前缀。

    Args:
        model_name: 原始模型名。

    Returns:
        str: 裸模型名（首个斜杠之后的部分），无斜杠时原样返回。
    """
    raw = (model_name or "").strip()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1].strip()
    return raw


class LLMClient:
    """大语言模型统一调用客户端。

    封装 litellm.acompletion 接口，提供非流式与流式两种调用方式，
    并在 litellm 侧失败时直连 OpenAI 兼容 HTTP 接口兜底。
    支持 deepseek（默认）与 agnes 两种底层配置。

    Attributes:
        provider: 当前使用的 Provider 标识（"deepseek" / "agnes"）。
        _allow_mock: 是否允许 mock 降级（来自 settings.LLM_ALLOW_MOCK_FALLBACK）。
        _mock_mode: 是否处于 mock 降级模式。
        _model: litellm 模型标识（带厂商前缀）。
        _raw_model: 模型裸名（直连 HTTP 兜底时使用）。
        _api_base: 厂商 API 基础地址。
        _api_key: 厂商 API Key。
    """

    def __init__(
        self,
        provider: str = "deepseek",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        """初始化 LLM 客户端。

        显式覆盖参数（来自项目级 / 用户级 model_configs 配置）优先，
        为 None 时回退 .env 中对应 provider 的默认配置。

        Args:
            provider: Provider 标识，支持 "deepseek"（默认）与 "agnes"。
            api_key: 显式覆盖的 API Key；None 时使用 settings 默认凭证。
            api_base: 显式覆盖的 API 基础地址；None 时使用 settings 默认地址。
            model_name: 显式覆盖的模型名称；None 时使用 settings 默认模型。

        Returns:
            None
        """
        self.provider = provider
        self._allow_mock = bool(getattr(settings, "LLM_ALLOW_MOCK_FALLBACK", False))

        if provider == "agnes":
            base_model = _strip_prefix(
                model_name or settings.AGNES_LLM_MODEL or "agnes-3.0-flash"
            ) or "agnes-3.0-flash"
            # agnes 走 LiteLLM 的 openai/ 前缀兼容层，经 api_base 指向 Agnes APIHub
            self._model = f"{_LITELLM_PREFIX['agnes']}{base_model}"
            self._raw_model = base_model
            self._api_base = _normalize_api_base(
                api_base if api_base is not None else settings.AGNES_BASE_URL
            )
            self._api_key = (
                api_key if api_key is not None else (settings.AGNES_LLM_API_KEY or "")
            )
        else:
            # deepseek 分支：项目级/用户级配置优先，缺省回退 .env。
            # 关键修复：模型标识必须带 deepseek/ 前缀，否则 litellm 无法识别厂商，
            # 会抛 "LLM Provider NOT provided" 并（历史上）被静默降级为 mock 文案。
            base_model = _strip_prefix(
                model_name or settings.DEEPSEEK_MODEL or "deepseek-flash"
            ) or "deepseek-flash"
            self._model = f"{_LITELLM_PREFIX['deepseek']}{base_model}"
            self._raw_model = base_model
            self._api_base = _normalize_api_base(
                api_base if api_base is not None else settings.DEEPSEEK_BASE_URL
            )
            self._api_key = (
                api_key if api_key is not None else settings.DEEPSEEK_API_KEY
            )

        self._api_key = (self._api_key or "").strip()

        # mock 仅在显式开启 LLM_ALLOW_MOCK_FALLBACK 且确实无法真实调用时才启用
        key_missing = self._api_key.lower() in _PLACEHOLDER_API_KEYS
        self._mock_mode = self._allow_mock and (not _HAS_LITELLM or key_missing)
        if self._mock_mode:
            logger.warning(
                f"[llm:{provider}] 进入 mock 模式"
                f"（LLM_ALLOW_MOCK_FALLBACK=true 且 litellm 不可用或 API Key 缺失）。"
            )
        elif key_missing:
            logger.warning(
                f"[llm:{provider}] 未解析到有效 API Key，调用将失败并向上报错"
                f"（如需演示降级请设置 LLM_ALLOW_MOCK_FALLBACK=true）。"
            )

        logger.info(
            f"[llm:{provider}] 初始化 model={self._model}, api_base={self._api_base or '(默认)'}, "
            f"api_key={(self._api_key[:8] + '...') if self._api_key else '(空)'}"
        )

    @property
    def model_id(self) -> str:
        """返回当前使用的 litellm 模型标识（带厂商前缀）。

        Returns:
            str: 形如 "deepseek/deepseek-flash"。
        """
        return self._model

    def _chat_url(self) -> str:
        """构造 OpenAI 兼容的 chat/completions 直连地址。

        兼容 api_base 已带 /v1 与不带 /v1 两种写法，避免出现 /v1/v1 重复。

        Returns:
            str: 完整请求地址；api_base 为空时返回空字符串。
        """
        base = self._api_base
        if not base:
            return ""
        if base.endswith("/v1") or "/v1/" in base:
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _headers(self) -> dict:
        """构造直连 HTTP 的请求头。

        Returns:
            dict: 含 Bearer 鉴权与 JSON Content-Type 的请求头。
        """
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _http_fallback_enabled(self) -> bool:
        """判断直连 HTTP 兜底是否可用。

        Returns:
            bool: 开关打开且 api_base 已配置时返回 True。
        """
        return bool(getattr(settings, "LLM_ENABLE_HTTP_FALLBACK", True)) and bool(
            self._chat_url()
        )

    async def _http_chat(self, messages: list[dict], temperature: float) -> str:
        """直连 OpenAI 兼容接口做一次非流式补全。

        Args:
            messages: 对话消息列表。
            temperature: 采样温度。

        Returns:
            str: 模型返回的完整文本。

        Raises:
            Exception: 网络异常或非 200 响应时抛出，由调用方决定是否降级。
        """
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                self._chat_url(),
                headers=self._headers(),
                json={
                    "model": self._raw_model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                },
            )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"响应缺少 choices 字段: {str(data)[:300]}")
        return (choices[0].get("message") or {}).get("content") or ""

    async def _http_chat_stream(
        self, messages: list[dict], temperature: float
    ) -> AsyncGenerator[str, None]:
        """直连 OpenAI 兼容接口做一次流式补全，逐个 yield 增量文本。

        Args:
            messages: 对话消息列表。
            temperature: 采样温度。

        Yields:
            str: 模型返回的增量文本片段。

        Raises:
            Exception: 网络异常或非 200 响应时抛出，由调用方决定是否降级。
        """
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            async with client.stream(
                "POST",
                self._chat_url(),
                headers=self._headers(),
                json={
                    "model": self._raw_model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"HTTP {resp.status_code}: {body.decode('utf-8', 'ignore')[:300]}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except Exception:  # noqa: BLE001 - 跳过无法解析的心跳/噪声行
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content") or ""
                    if delta:
                        yield delta

    async def achat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> str:
        """非流式调用大模型，返回完整文本。

        Args:
            messages: 对话消息列表，每项为 {"role": ..., "content": ...}。
            model: 模型名称，默认取初始化时按 provider 解析的模型。
            temperature: 采样温度，默认 0.7。
            stream: 是否流式（本方法始终返回完整文本，该参数仅作兼容）。

        Returns:
            str: 模型生成的文本内容。

        Raises:
            BizException: litellm 与直连 HTTP 兜底均失败时抛出，错误码为 AI_ERROR。
        """
        # model 入参为完整 litellm 标识（调用方自行决定是否带厂商前缀），否则用默认
        target_model = model or self._model

        if self._mock_mode:
            return self._mock_achat(messages, target_model)

        errors: list[str] = []

        if _HAS_LITELLM:
            try:
                response = await litellm.acompletion(  # type: ignore
                    model=target_model,
                    messages=messages,
                    temperature=temperature,
                    api_base=self._api_base or None,
                    api_key=self._api_key or None,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                errors.append(f"litellm: {exc}")
                logger.error(
                    f"[llm:{self.provider}] achat litellm 调用失败 model={target_model}: {exc}"
                )
        else:
            errors.append("litellm 未安装")

        if self._http_fallback_enabled():
            try:
                text = await self._http_chat(messages, temperature)
                logger.warning(
                    f"[llm:{self.provider}] achat 已改用直连 HTTP 兜底成功 "
                    f"url={self._chat_url()} model={self._raw_model}"
                )
                return text
            except Exception as exc:  # noqa: BLE001
                errors.append(f"direct-http: {exc}")
                logger.error(
                    f"[llm:{self.provider}] achat 直连 HTTP 兜底失败 url={self._chat_url()}: {exc}"
                )

        if self._allow_mock:
            logger.warning(f"[llm:{self.provider}] 全部真实调用失败，按配置降级为 mock")
            return self._mock_achat(messages, target_model)

        raise BizException(
            ErrorCode.AI_ERROR,
            "LLM 调用失败（litellm 与直连 HTTP 均失败）: " + " | ".join(errors),
        )

    async def achat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """流式调用大模型，逐个 yield 增量文本片段。

        Args:
            messages: 对话消息列表。
            model: 模型名称，默认取初始化时按 provider 解析的模型。
            temperature: 采样温度，默认 0.7。

        Yields:
            str: 模型返回的增量文本片段。

        Raises:
            BizException: litellm 与直连 HTTP 兜底均失败时抛出，错误码为 AI_ERROR。
        """
        target_model = model or self._model

        if self._mock_mode:
            for chunk in self._mock_achat(messages, target_model):
                yield chunk
                await asyncio.sleep(0)
            return

        errors: list[str] = []
        # litellm 是否已经吐出过增量内容：吐过则不再重试，避免内容重复
        litellm_produced = False

        if _HAS_LITELLM:
            try:
                stream = await litellm.acompletion(  # type: ignore
                    model=target_model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                    api_base=self._api_base or None,
                    api_key=self._api_key or None,
                )
                async for part in stream:
                    delta = part.choices[0].delta.content or ""
                    if delta:
                        litellm_produced = True
                        yield delta
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"litellm: {exc}")
                logger.error(
                    f"[llm:{self.provider}] achat_stream litellm 调用失败 "
                    f"model={target_model}: {exc}"
                )
                # 已流出部分内容后中断：直接报错，避免与兜底路径内容重复拼接
                if litellm_produced:
                    raise BizException(
                        ErrorCode.AI_ERROR,
                        f"LLM 流式输出中断: {exc}",
                    ) from exc
        else:
            errors.append("litellm 未安装")

        if self._http_fallback_enabled():
            produced = False
            try:
                logger.warning(
                    f"[llm:{self.provider}] achat_stream 改用直连 HTTP 兜底 "
                    f"url={self._chat_url()} model={self._raw_model}"
                )
                async for delta in self._http_chat_stream(messages, temperature):
                    produced = True
                    yield delta
                if produced:
                    return
                errors.append("direct-http: 未返回任何内容")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"direct-http: {exc}")
                logger.error(
                    f"[llm:{self.provider}] achat_stream 直连 HTTP 兜底失败 "
                    f"url={self._chat_url()}: {exc}"
                )

        if self._allow_mock:
            logger.warning(f"[llm:{self.provider}] 全部真实调用失败，按配置降级为 mock")
            for chunk in self._mock_achat(messages, target_model):
                yield chunk
                await asyncio.sleep(0)
            return

        raise BizException(
            ErrorCode.AI_ERROR,
            "LLM 流式调用失败（litellm 与直连 HTTP 均失败）: " + " | ".join(errors),
        )

    @staticmethod
    def _mock_achat(messages: list[dict], model: str) -> str:
        """根据消息上下文生成 mock 结构化响应。

        仅在 LLM_ALLOW_MOCK_FALLBACK=true 时才会被调用，用于离线演示；
        默认配置下不会返回本函数的任何内容。

        通过分析 system prompt 的关键词判断当前任务类型（剧本/角色/场景/分镜等），
        返回对应的 JSON 结构，保证下游业务流程可完整跑通。

        Args:
            messages: 对话消息列表（用于判断任务类型）。
            model: 模型名称（仅用于日志）。

        Returns:
            str: 符合任务上下文的 JSON 字符串。
        """
        logger.info(f"[llm] mock 调用 model={model}, messages_count={len(messages)}")
        # 拼接所有消息文本用于关键词匹配
        full_text = "\n".join(m.get("content", "") for m in messages)

        # 剧本生成：返回含角色和场景的结构化剧本
        if "剧本" in full_text or "script" in full_text.lower():
            return json.dumps(
                {
                    "title": "未来之旅",
                    "logline": "少年穿越到未来世界，展开一段奇幻冒险。",
                    "characters": [
                        {
                            "name": "小星",
                            "role": "主角",
                            "age": 16,
                            "gender": "男",
                            "personality": "勇敢、好奇",
                            "appearance": "黑发少年，穿着休闲夹克",
                        },
                        {
                            "name": "AI助手",
                            "role": "配角",
                            "age": 0,
                            "gender": "中性",
                            "personality": "理性、忠诚",
                            "appearance": "悬浮的蓝色光球",
                        },
                    ],
                    "scenes": [
                        {
                            "scene_id": 1,
                            "location": "现代卧室",
                            "time": "夜晚",
                            "description": "小星在房间里发现一个神秘发光装置",
                            "dialogues": [
                                {"character": "小星", "text": "这是什么？居然在发光！"},
                            ],
                        },
                        {
                            "scene_id": 2,
                            "location": "未来城市",
                            "time": "白天",
                            "description": "小星被传送到高楼林立的未来都市",
                            "dialogues": [
                                {"character": "AI助手", "text": "欢迎来到2150年，我是你的向导。"},
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        # 角色生成：返回角色设定详情
        if "角色" in full_text or "character" in full_text.lower():
            return json.dumps(
                {
                    "name": "小星",
                    "appearance": "黑发少年，身高170cm，穿着休闲夹克和牛仔裤",
                    "personality": "勇敢、好奇、富有正义感",
                    "background": "普通高中生，意外获得穿越能力",
                },
                ensure_ascii=False,
            )

        # 场景生成：返回场景设定详情
        if "场景" in full_text or "scene" in full_text.lower():
            return json.dumps(
                {
                    "name": "未来城市",
                    "description": "高楼林立的未来都市，空中有飞行汽车穿梭",
                    "atmosphere": "科技感、明亮、充满活力",
                },
                ensure_ascii=False,
            )

        # 分镜生成：返回分镜列表
        if "分镜" in full_text or "storyboard" in full_text.lower():
            return json.dumps(
                {
                    "shots": [
                        {
                            "shot_id": 1,
                            "scene_id": 1,
                            "shot_type": "特写",
                            "description": "小星惊讶地看着发光装置",
                            "duration": 3,
                            "camera_movement": "推镜",
                        },
                        {
                            "shot_id": 2,
                            "scene_id": 2,
                            "shot_type": "全景",
                            "description": "未来城市全景，飞行汽车穿梭",
                            "duration": 5,
                            "camera_movement": "摇镜",
                        },
                    ],
                },
                ensure_ascii=False,
            )

        # 默认：返回通用占位文本
        return "这是 mock 模式下的占位响应。"


# 单例缓存：按 provider 维度各持有一个 LLMClient 实例
_llm_clients: dict[str, LLMClient] = {}


def get_llm(
    provider: str = "deepseek",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model_name: Optional[str] = None,
) -> LLMClient:
    """获取指定 Provider 的 LLMClient 实例。

    无覆盖参数（三个覆盖参数均为 None）时复用按 provider 维度缓存的
    单例，行为与原有调用方完全一致；任一覆盖参数非 None 时（即来自
    项目级 / 用户级 model_configs 配置的动态凭证）每次创建独立实例，
    不写入单例缓存，避免动态配置污染全局默认客户端。

    Args:
        provider: Provider 标识，"deepseek"（默认）或 "agnes"。
        api_key: 显式覆盖的 API Key；None 时使用 settings 默认凭证。
        api_base: 显式覆盖的 API 基础地址；None 时使用 settings 默认地址。
        model_name: 显式覆盖的模型名称；None 时使用 settings 默认模型。

    Returns:
        LLMClient: 对应 Provider 与凭证配置的大模型客户端实例。
    """
    global _llm_clients
    # 无任何覆盖参数：走原有单例缓存路径
    if api_key is None and api_base is None and model_name is None:
        client = _llm_clients.get(provider)
        if client is None:
            client = LLMClient(provider=provider)
            _llm_clients[provider] = client
        return client
    # 有覆盖参数（项目级 / 用户级配置）：新建独立实例，不入缓存
    return LLMClient(
        provider=provider, api_key=api_key, api_base=api_base, model_name=model_name
    )


def _map_provider(provider: str, api_base: Optional[str], model_name: Optional[str]) -> str:
    """将 model_configs 的 provider 字段映射为本模块支持的 Provider 标识。

    优先直接使用 provider 字段（agnes/deepseek）；字段值不在支持范围时，
    按 api_base 与 model_name 中的关键词推断；仍无法识别则回退 deepseek。

    Args:
        provider: model_configs 表的 provider 字段值。
        api_base: 用户配置的 API 基础地址（用于推断，可为 None）。
        model_name: 用户配置的模型名称（用于推断，可为 None）。

    Returns:
        str: 本模块支持的 Provider 标识（"deepseek" / "agnes"）。
    """
    if provider in ("agnes", "deepseek"):
        return provider
    # 由 api_base / model_name 关键词推断（如自建 OpenAI 兼容网关带 agnes 字样）
    haystack = f"{api_base or ''} {model_name or ''}".lower()
    if "agnes" in haystack:
        return "agnes"
    return "deepseek"


async def resolve_llm_settings(
    db: AsyncSession,
    user_id: int,
    capability: ModelCapability = ModelCapability.LLM,
    project_id: Optional[int] = None,
) -> dict:
    """解析模型运行时配置（项目级优先，其次用户级，最后回退 .env）。

    查询顺序：
        1. project_id 匹配、user_id 匹配、capability 匹配的最新一条项目级配置；
        2. 若项目级不存在，则取 user_id 匹配、project_id 为 NULL 的最新用户级配置。
    存在则解密 api_key_encrypted 得到明文 Key，返回
    {provider, api_key, model_name, api_base, scope} 供 get_llm 覆盖 .env
    默认凭证；无记录或解密失败时返回空 dict，表示调用方应回退 .env 凭证。

    当前已接线调用点：domains/scripts.py 的 generate_script / score_script；
    其他 LLM 调用点（storyboard / consistency 等）可按需接入本函数。

    Args:
        db: 异步数据库会话（由调用方管理生命周期）。
        user_id: 用户 ID。
        capability: 模型能力类型，默认 LLM；未来可扩展 IMAGE/VIDEO/TTS。
        project_id: 项目 ID；传入时会优先采用项目级模型选型。

    Returns:
        dict: 运行时配置 {"provider": "deepseek"|"agnes",
        "api_key": 明文Key或None, "model_name": 模型名或None,
        "api_base": API地址或None, "scope": "project"|"user"}；
        无记录或解密失败返回 {}。

    Raises:
        无：数据库查询异常不在此吞掉（由调用方决定处理策略），
        仅解密失败时降级为 {} 并记录 warning 日志。
    """
    cfg = None
    scope = "user"

    # 1) 项目级模型选型优先（模型配置抽屉里点选的模型落在此处）
    if project_id is not None:
        result = await db.execute(
            select(ModelConfig)
            .where(
                ModelConfig.user_id == user_id,
                ModelConfig.project_id == project_id,
                ModelConfig.capability == capability,
            )
            .order_by(desc(ModelConfig.id))
            .limit(1)
        )
        cfg = result.scalars().first()
        if cfg is not None:
            scope = "project"

    # 2) 回退用户级 API Key 配置
    if cfg is None:
        result = await db.execute(
            select(ModelConfig)
            .where(
                ModelConfig.user_id == user_id,
                ModelConfig.project_id.is_(None),
                ModelConfig.capability == capability,
            )
            .order_by(desc(ModelConfig.id))
            .limit(1)
        )
        cfg = result.scalars().first()

    # 无任何记录 → 返回空 dict，调用方回退 .env 凭证
    if cfg is None:
        return {}

    api_key: Optional[str] = None
    if cfg.api_key_encrypted:
        try:
            api_key = aes_decrypt(cfg.api_key_encrypted)
        except Exception as exc:  # noqa: BLE001
            # 解密失败（密钥轮换/密文损坏等）→ 降级回退 .env，不阻断业务
            logger.warning(
                f"[resolve_llm_settings] 模型 Key 解密失败 user_id={user_id}, "
                f"config_id={cfg.id}: {exc}，降级回退 .env 凭证"
            )
            return {}

    provider = _map_provider(cfg.provider, cfg.api_base, cfg.model_name)

    # model_name 为占位值（如 "user-key"，用户在 API Key 管理里只填了 Key）时，
    # 按 provider 选择 .env 中运维配置的真实模型，避免把占位标识传给模型接口
    model_name = (cfg.model_name or "").strip()
    if model_name.lower() in _PLACEHOLDER_MODEL_NAMES:
        if provider == "agnes":
            model_name = (settings.AGNES_LLM_MODEL or "").strip()
        else:
            model_name = (settings.DEEPSEEK_MODEL or "").strip()
        model_name = model_name or None

    resolved = {
        "provider": provider,
        "api_key": api_key,
        "model_name": model_name,
        "api_base": cfg.api_base or None,
        "scope": scope,
    }
    logger.info(
        f"[resolve_llm_settings] user_id={user_id}, project_id={project_id}, "
        f"scope={scope}, provider={provider}, model={model_name or '(默认)'}, "
        f"api_base={cfg.api_base or '(默认)'}, key={'已配置' if api_key else '未配置'}"
    )
    return resolved
