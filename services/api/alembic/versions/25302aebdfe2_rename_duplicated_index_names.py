"""rename duplicated index names

Revision ID: 25302aebdfe2
Revises: 8e2a29164810
Create Date: 2026-10-19 10:49:51.091338

根治跨表重名索引：原 idx_project_id（4 表复用）/ idx_status（3 表复用）/
idx_project_time（2 表复用）在 SQLite 等索引名全局唯一的数据库上冲突。
统一改为「表名前缀」唯一命名，列与索引语义完全不变。

对 SQLite 的影响：测试库通过 Base.metadata.create_all 建表（不跑迁移），
models 已同步改名，因此 SQLite 侧无任何影响。
MySQL 采用 drop_index + create_index 改名（等价语义重建）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25302aebdfe2'
down_revision: Union[str, None] = '8e2a29164810'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构：9 处重名索引改为表名前缀唯一命名。

    Returns:
        None

    Raises:
        OperationalError: MySQL 未启动或连接失败时抛出。
    """
    # ---- idx_project_time（2 表复用）----
    op.drop_index("idx_project_time", table_name="agent_events")
    op.create_index(
        "idx_agent_events_project_time", "agent_events", ["project_id", "created_at"], unique=False
    )
    op.drop_index("idx_project_time", table_name="revisions")
    op.create_index(
        "idx_revisions_project_time", "revisions", ["project_id", "created_at"], unique=False
    )

    # ---- idx_project_id（4 表复用）----
    op.drop_index("idx_project_id", table_name="characters")
    op.create_index("idx_characters_project_id", "characters", ["project_id"], unique=False)
    op.drop_index("idx_project_id", table_name="scenes")
    op.create_index("idx_scenes_project_id", "scenes", ["project_id"], unique=False)
    op.drop_index("idx_project_id", table_name="tasks")
    op.create_index("idx_tasks_project_id", "tasks", ["project_id"], unique=False)
    op.drop_index("idx_project_id", table_name="graph_runs")
    op.create_index("idx_graph_runs_project_id", "graph_runs", ["project_id"], unique=False)

    # ---- idx_status（3 表复用）----
    op.drop_index("idx_status", table_name="projects")
    op.create_index("idx_projects_status", "projects", ["status"], unique=False)
    op.drop_index("idx_status", table_name="storyboards")
    op.create_index("idx_storyboards_status", "storyboards", ["status"], unique=False)
    op.drop_index("idx_status", table_name="tasks")
    op.create_index("idx_tasks_status", "tasks", ["status"], unique=False)


def downgrade() -> None:
    """回滚数据库结构：恢复旧的复用式索引名。

    Returns:
        None
    """
    # ---- idx_status（3 表复用）----
    op.drop_index("idx_tasks_status", table_name="tasks")
    op.create_index("idx_status", "tasks", ["status"], unique=False)
    op.drop_index("idx_storyboards_status", table_name="storyboards")
    op.create_index("idx_status", "storyboards", ["status"], unique=False)
    op.drop_index("idx_projects_status", table_name="projects")
    op.create_index("idx_status", "projects", ["status"], unique=False)

    # ---- idx_project_id（4 表复用）----
    op.drop_index("idx_graph_runs_project_id", table_name="graph_runs")
    op.create_index("idx_project_id", "graph_runs", ["project_id"], unique=False)
    op.drop_index("idx_tasks_project_id", table_name="tasks")
    op.create_index("idx_project_id", "tasks", ["project_id"], unique=False)
    op.drop_index("idx_scenes_project_id", table_name="scenes")
    op.create_index("idx_project_id", "scenes", ["project_id"], unique=False)
    op.drop_index("idx_characters_project_id", table_name="characters")
    op.create_index("idx_project_id", "characters", ["project_id"], unique=False)

    # ---- idx_project_time（2 表复用）----
    op.drop_index("idx_revisions_project_time", table_name="revisions")
    op.create_index("idx_project_time", "revisions", ["project_id", "created_at"], unique=False)
    op.drop_index("idx_agent_events_project_time", table_name="agent_events")
    op.create_index("idx_project_time", "agent_events", ["project_id", "created_at"], unique=False)
