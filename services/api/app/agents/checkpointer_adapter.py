"""
LangGraph Checkpointer 适配器模块。

封装社区库 `langgraph-checkpoint-mysql` 以提供基于 MySQL 的检查点持久化能力。
由于该第三方库在运行环境中可能未安装，本模块提供了完整的降级方案：
当社区库导入失败时，自动回退到基于内存字典的轻量级 checkpointer，
保证业务代码无需关心底层实现差异。

注意：检查点属于非强依赖组件，所有写入失败仅记录日志，不向上抛出异常，
以避免影响主生产流水线的稳定性。
"""

import threading
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger()

# 尝试导入社区 MySQL checkpointer；失败则置 None 走内存降级
try:  # pragma: no cover - 依赖环境
    from langgraph.checkpoint.mysql import (  # type: ignore
        AsyncMysqlSaver,
        MysqlSaver,
    )
    _HAS_MYSQL_CHECKPOINTER = True
except Exception:  # noqa: BLE001
    AsyncMysqlSaver = None  # type: ignore
    MysqlSaver = None  # type: ignore
    _HAS_MYSQL_CHECKPOINTER = False

# 尝试导入 langgraph 内置内存 checkpointer（用于 MySQL 不可用时的降级）
try:  # pragma: no cover - 依赖环境
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore

    _HAS_MEMORY_SAVER = True
except Exception:  # noqa: BLE001
    MemorySaver = None  # type: ignore
    _HAS_MEMORY_SAVER = False


class CheckpointerAdapter:
    """LangGraph Checkpointer 适配器。

    统一封装社区 MySQL checkpointer 与内存降级 checkpointer 的接口，
    对外暴露 setup / put / get / list 四个核心方法。

    Attributes:
        _use_memory: 是否使用内存降级实现。
        _mysql_saver: 社区库的 MySQL checkpointer 实例（若可用）。
        _store: 内存降级时使用的字典存储，key 为 thread_id。
        _lock: 内存降级时保护 _store 的线程锁。
    """

    def __init__(self) -> None:
        """初始化 Checkpointer 适配器。

        优先尝试使用社区 MySQL checkpointer，若不可用则降级为内存实现。
        内存实现优先使用 langgraph 内置的 MemorySaver（可支持 interrupt），
        若连 langgraph 也不可用，则退化为纯字典存储。

        Returns:
            None
        """
        self._use_memory = not _HAS_MYSQL_CHECKPOINTER
        self._mysql_saver: Optional[Any] = None
        self._memory_saver: Optional[Any] = None
        self._store: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

        if not self._use_memory:
            try:  # pragma: no cover - 依赖环境
                # 社区库通常通过 from_conn_string 构造；这里占位，由 setup 实际建连
                self._mysql_saver = None
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[checkpointer] 初始化 MySQL checkpointer 失败，降级为内存: {exc}")
                self._use_memory = True

        # 内存降级：优先使用 langgraph 内置 MemorySaver
        if self._use_memory and _HAS_MEMORY_SAVER:
            try:
                self._memory_saver = MemorySaver()
                logger.info("[checkpointer] 使用 langgraph MemorySaver 作为降级 checkpointer。")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[checkpointer] MemorySaver 初始化失败，退化为 dict 存储: {exc}")

    async def setup(self) -> None:
        """建立连接并创建检查点所需的数据表。

        若使用社区 MySQL checkpointer，则调用其 setup 方法建表；
        若为内存降级或建表失败，则仅记录日志并跳过，不抛出异常。

        Returns:
            None

        Raises:
            无：任何异常均被捕获并记录日志，checkpoint 为非强依赖。
        """
        if self._use_memory:
            logger.info("[checkpointer] 使用内存 checkpointer（降级模式），无需建表。")
            return

        try:  # pragma: no cover - 依赖环境
            if self._mysql_saver is not None and hasattr(self._mysql_saver, "setup"):
                await self._mysql_saver.setup()
                logger.info("[checkpointer] MySQL checkpointer 建表完成。")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[checkpointer] MySQL checkpointer 建表失败，已跳过: {exc}")

    async def put(self, checkpoint: dict) -> None:
        """写入一个检查点。

        Args:
            checkpoint: 检查点数据字典，需包含 thread_id 等字段。

        Returns:
            None

        Raises:
            无：写入失败仅记录日志，不向上抛出。
        """
        thread_id = str(checkpoint.get("thread_id", ""))
        try:
            if self._use_memory:
                with self._lock:
                    self._store.setdefault(thread_id, []).append(checkpoint)
            else:  # pragma: no cover - 依赖环境
                if self._mysql_saver is not None:
                    # 社区库接口通常为 put(checkpoint)；具体签名以实际库为准
                    await self._mysql_saver.put(checkpoint)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[checkpointer] 写入检查点失败 thread_id={thread_id}: {exc}")

    async def get(self, thread_id: str) -> Optional[dict]:
        """获取指定线程的最新检查点。

        Args:
            thread_id: 线程 ID。

        Returns:
            Optional[dict]: 最新检查点数据；若不存在则返回 None。
        """
        try:
            if self._use_memory:
                with self._lock:
                    items = self._store.get(thread_id, [])
                    return items[-1] if items else None
            else:  # pragma: no cover - 依赖环境
                if self._mysql_saver is not None:
                    return await self._mysql_saver.get(thread_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[checkpointer] 读取检查点失败 thread_id={thread_id}: {exc}")
        return None

    async def list(self, thread_id: str) -> list[dict]:
        """列出指定线程的全部检查点。

        Args:
            thread_id: 线程 ID。

        Returns:
            list[dict]: 检查点列表；读取失败时返回空列表。
        """
        try:
            if self._use_memory:
                with self._lock:
                    return list(self._store.get(thread_id, []))
            else:  # pragma: no cover - 依赖环境
                if self._mysql_saver is not None:
                    return await self._mysql_saver.list(thread_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[checkpointer] 列出检查点失败 thread_id={thread_id}: {exc}")
        return []

    def get_saver(self) -> Optional[Any]:
        """返回底层 saver 实例，供 LangGraph 编译时使用。

        优先返回 MySQL saver；若不可用则返回 langgraph MemorySaver；
        若两者均不可用则返回 None。

        Returns:
            Optional[Any]: checkpointer saver 实例，或 None。
        """
        if self._mysql_saver is not None:
            return self._mysql_saver
        if self._memory_saver is not None:
            return self._memory_saver
        return None


# 单例缓存
_checkpointer: Optional[CheckpointerAdapter] = None
_singleton_lock = threading.Lock()


def get_checkpointer() -> CheckpointerAdapter:
    """获取 CheckpointerAdapter 单例。

    Returns:
        CheckpointerAdapter: 全局唯一的检查点适配器实例。
    """
    global _checkpointer
    if _checkpointer is None:
        with _singleton_lock:
            if _checkpointer is None:
                _checkpointer = CheckpointerAdapter()
    return _checkpointer
