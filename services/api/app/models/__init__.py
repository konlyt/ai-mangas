"""
数据库 ORM 模型集合。

按架构文档 5.3 节定义全部 16 张数据表，所有模型继承自 Base。
时间字段统一使用 DateTime(timezone=True)，JSON 字段使用 SQLAlchemy JSON 类型，
枚举字段使用 sa.Enum 绑定 Python Enum。
"""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    DECIMAL,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


# ============================================================
# 枚举定义
# ============================================================


class ProjectStatus(str, enum.Enum):
    """项目阶段枚举。"""

    DRAFT = "draft"
    SCRIPTING = "scripting"
    ASSETS = "assets"
    STORYBOARD = "storyboard"
    KEYFRAMES = "keyframes"
    VIDEO = "video"
    VOICE = "voice"
    COMPOSE = "compose"
    REVIEW = "review"
    DONE = "done"


class AssetOwnerType(str, enum.Enum):
    """资产归属类型枚举。"""

    CHARACTER = "character"
    SCENE = "scene"
    PROP = "prop"


class AssetVariantStatus(str, enum.Enum):
    """资产变体状态枚举。"""

    PENDING = "pending"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


class StoryboardStatus(str, enum.Enum):
    """分镜状态枚举。"""

    PENDING = "pending"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


class ModelCapability(str, enum.Enum):
    """模型能力类型枚举。"""

    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"


class TaskType(str, enum.Enum):
    """任务类型枚举。"""

    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"
    COMPOSE = "compose"


class TaskStatus(str, enum.Enum):
    """任务状态枚举。"""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"


class QueueName(str, enum.Enum):
    """任务队列名称枚举。"""

    URGENT = "urgent"
    NORMAL = "normal"
    BACKGROUND = "background"


class GraphEntryPoint(str, enum.Enum):
    """Graph 执行入口枚举。"""

    FULL = "full"
    STAGE = "stage"
    PARTIAL = "partial"


class GraphRunStatus(str, enum.Enum):
    """Graph 执行状态枚举。"""

    RUNNING = "running"
    INTERRUPTED = "interrupted"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConsistencySubjectType(str, enum.Enum):
    """一致性校验对象类型枚举。"""

    ASSET = "asset"
    KEYFRAME = "keyframe"


class ConsistencyAction(str, enum.Enum):
    """一致性处置动作枚举。"""

    PASS = "pass"
    REGENERATE = "regenerate"
    MANUAL = "manual"


# ============================================================
# 模型定义
# ============================================================


class User(Base):
    """用户表。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户名")
    email: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, comment="手机号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="头像URL")
    vip_level: Mapped[int] = mapped_column(Integer, default=0, comment="会员等级")
    quota: Mapped[int] = mapped_column(Integer, default=0, comment="剩余点数")
    status: Mapped[int] = mapped_column(Integer, default=1, comment="状态：0禁用 1正常")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class Project(Base):
    """项目表。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户ID")
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="项目标题")
    genre: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="体裁")
    style: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="视觉风格")
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus), nullable=False, default=ProjectStatus.DRAFT, comment="项目阶段"
    )
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16", comment="输出比例")
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="项目级模型配置")
    cover_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="项目封面")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_status", "status"),
    )


class Script(Base):
    """剧本表。"""

    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    episode_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="剧集ID（NULL=主剧本）")
    content: Mapped[dict] = mapped_column(JSON, nullable=False, comment="结构化剧本")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始输入文本")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("uk_project_episode", "project_id", "episode_id", unique=True),
    )


class Character(Base):
    """角色表。"""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色名")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="角色描述")
    visual_prompt: Mapped[str] = mapped_column(Text, nullable=False, comment="视觉提示词")
    voice_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="绑定音色ID")
    main_asset_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="主定妆照URL")
    is_locked: Mapped[int] = mapped_column(Integer, default=0, comment="是否锁定")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_project_id", "project_id"),
    )


class AssetVariant(Base):
    """资产变体表。"""

    __tablename__ = "asset_variants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    owner_type: Mapped[AssetOwnerType] = mapped_column(
        SAEnum(AssetOwnerType), nullable=False, comment="资产归属类型"
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="归属对象ID")
    variant_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="变体类型")
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="图片URL")
    visual_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变体提示词")
    feature_vector: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="面部特征向量")
    similarity_score: Mapped[float | None] = mapped_column(
        DECIMAL(5, 4), nullable=True, comment="一致性校验得分"
    )
    status: Mapped[AssetVariantStatus] = mapped_column(
        SAEnum(AssetVariantStatus), default=AssetVariantStatus.PENDING, comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_owner", "owner_type", "owner_id"),
    )


class Scene(Base):
    """场景表。"""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="场景名")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="场景描述")
    visual_prompt: Mapped[str] = mapped_column(Text, nullable=False, comment="视觉提示词")
    asset_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="概念图URL")
    is_locked: Mapped[int] = mapped_column(Integer, default=0, comment="是否锁定")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_project_id", "project_id"),
    )


class Storyboard(Base):
    """分镜表。"""

    __tablename__ = "storyboards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    script_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="剧本ID")
    episode_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="剧集ID")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="镜头序号")
    shot_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="景别")
    camera_movement: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="运镜方式")
    duration: Mapped[int] = mapped_column(Integer, default=5, comment="预计时长（秒）")
    visual_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="画面描述")
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True, comment="对白/旁白")
    character_ids: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="涉及角色ID列表")
    scene_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="场景ID")
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True, comment="绘图提示词")
    keyframe_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="首帧URL")
    endframe_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="尾帧URL")
    video_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="视频片段URL")
    audio_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="配音URL")
    status: Mapped[StoryboardStatus] = mapped_column(
        SAEnum(StoryboardStatus), default=StoryboardStatus.PENDING, comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("uk_project_seq", "project_id", "episode_id", "sequence", unique=True),
        Index("idx_status", "status"),
        Index("idx_scene_id", "scene_id"),
    )


class ModelConfig(Base):
    """模型配置表。"""

    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="用户ID（NULL=全局默认）")
    project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="项目ID（NULL=用户级）")
    capability: Mapped[ModelCapability] = mapped_column(
        SAEnum(ModelCapability), nullable=False, comment="能力类型"
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="厂商标识")
    model_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="模型名称")
    api_key_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="AES加密后的Key")
    api_base: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="自定义API地址")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="参数")
    price_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="计价元数据")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_scope", "user_id", "project_id", "capability"),
    )


class Task(Base):
    """任务表。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    storyboard_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="分镜ID")
    graph_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联Graph执行")
    type: Mapped[TaskType] = mapped_column(SAEnum(TaskType), nullable=False, comment="任务类型")
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.QUEUED, comment="状态"
    )
    queue_name: Mapped[QueueName] = mapped_column(
        SAEnum(QueueName), default=QueueName.NORMAL, comment="队列"
    )
    priority: Mapped[int] = mapped_column(Integer, default=5, comment="优先级")
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="幂等键")
    provider_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="第三方任务ID")
    result_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="结果文件URL")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="已重试次数")
    max_retry: Mapped[int] = mapped_column(Integer, default=3, comment="最大重试次数")
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="下次重试时间"
    )
    cost_points: Mapped[int] = mapped_column(Integer, default=0, comment="消耗点数")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("uk_idempotency", "idempotency_key", unique=True),
        Index("idx_status", "status"),
        Index("idx_project_id", "project_id"),
        Index("idx_queue", "queue_name", "status", "priority"),
    )


class GraphCheckpoint(Base):
    """LangGraph 检查点表（由 Checkpointer 维护）。"""

    __tablename__ = "graph_checkpoints"

    thread_id: Mapped[str] = mapped_column(String(255), primary_key=True, comment="线程ID")
    checkpoint_ns: Mapped[str] = mapped_column(String(255), primary_key=True, comment="命名空间")
    checkpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True, comment="检查点ID")
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="父检查点ID")
    type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="类型")
    checkpoint: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, comment="检查点数据")
    checkpoint_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True, comment="元数据"
    )


class GraphRun(Base):
    """Graph 执行表。"""

    __tablename__ = "graph_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="执行标识")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    entry_point: Mapped[GraphEntryPoint] = mapped_column(
        SAEnum(GraphEntryPoint), nullable=False, comment="执行入口"
    )
    target_node: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="partial目标节点")
    status: Mapped[GraphRunStatus] = mapped_column(
        SAEnum(GraphRunStatus), default=GraphRunStatus.RUNNING, comment="状态"
    )
    interrupt_at: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="中断所在节点")
    resumed_from: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="恢复自哪个run")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="触发用户")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("uk_run_id", "run_id", unique=True),
        Index("idx_project_id", "project_id"),
    )


class AgentEvent(Base):
    """Agent 事件表。"""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    graph_run_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="关联执行")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    node_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="Agent节点名")
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="链路追踪ID")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="耗时")
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输入token")
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输出token")
    cost_points: Mapped[int] = mapped_column(Integer, default=0, comment="消耗点数")
    input_digest: Mapped[str | None] = mapped_column(Text, nullable=True, comment="输入摘要")
    output_digest: Mapped[str | None] = mapped_column(Text, nullable=True, comment="输出摘要")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_run", "graph_run_id"),
        Index("idx_project_time", "project_id", "created_at"),
    )


class ConsistencyReport(Base):
    """一致性报告表。"""

    __tablename__ = "consistency_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    subject_type: Mapped[ConsistencySubjectType] = mapped_column(
        SAEnum(ConsistencySubjectType), nullable=False, comment="校验对象类型"
    )
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="对象ID")
    ref_asset_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="参照定妆照资产ID")
    similarity_score: Mapped[float] = mapped_column(DECIMAL(5, 4), nullable=False, comment="相似度得分")
    threshold: Mapped[float] = mapped_column(DECIMAL(5, 4), nullable=False, comment="阈值")
    action: Mapped[ConsistencyAction] = mapped_column(
        SAEnum(ConsistencyAction), nullable=False, comment="处置动作"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_project", "project_id", "subject_type"),
    )


class Revision(Base):
    """版本快照表。"""

    __tablename__ = "revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="项目ID")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, comment="阶段")
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, comment="阶段产出快照")
    graph_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="对应检查点")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="操作用户")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_project_time", "project_id", "created_at"),
    )


class OperationLog(Base):
    """操作日志表。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="操作人")
    project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="关联项目")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作类型")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="操作详情")
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作IP")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
        Index("idx_project", "project_id"),
    )


class Order(Base):
    """订单表。"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户ID")
    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="订单号")
    amount: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, comment="金额")
    points: Mapped[int] = mapped_column(Integer, nullable=False, comment="充值点数")
    pay_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="支付方式")
    status: Mapped[int] = mapped_column(Integer, default=0, comment="状态")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="支付时间")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (
        Index("uk_order_no", "order_no", unique=True),
        Index("idx_user", "user_id"),
    )


# 显式导出全部模型，便于 from app.models import *
__all__ = [
    "Base",
    "User",
    "Project",
    "Script",
    "Character",
    "AssetVariant",
    "Scene",
    "Storyboard",
    "ModelConfig",
    "Task",
    "GraphCheckpoint",
    "GraphRun",
    "AgentEvent",
    "ConsistencyReport",
    "Revision",
    "OperationLog",
    "Order",
]
