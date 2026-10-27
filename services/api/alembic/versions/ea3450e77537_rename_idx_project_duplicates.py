"""rename idx_project duplicates

Revision ID: ea3450e77537
Revises: 25302aebdfe2
Create Date: 2026-10-19 10:54:56.117152

补漏：idx_project（consistency_reports / operation_logs 两表复用）同样跨表
重名，改为表名前缀唯一命名，列与索引语义不变。与 25302aebdfe2 一起完成
全部重名索引根治。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea3450e77537'
down_revision: Union[str, None] = '25302aebdfe2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构：idx_project 两处重名改为表名前缀唯一命名。

    Returns:
        None

    Raises:
        OperationalError: MySQL 未启动或连接失败时抛出。
    """
    op.drop_index("idx_project", table_name="consistency_reports")
    op.create_index(
        "idx_consistency_reports_project",
        "consistency_reports",
        ["project_id", "subject_type"],
        unique=False,
    )
    op.drop_index("idx_project", table_name="operation_logs")
    op.create_index(
        "idx_operation_logs_project", "operation_logs", ["project_id"], unique=False
    )


def downgrade() -> None:
    """回滚数据库结构：恢复旧的复用式索引名 idx_project。

    Returns:
        None
    """
    op.drop_index("idx_operation_logs_project", table_name="operation_logs")
    op.create_index("idx_project", "operation_logs", ["project_id"], unique=False)
    op.drop_index("idx_consistency_reports_project", table_name="consistency_reports")
    op.create_index(
        "idx_project", "consistency_reports", ["project_id", "subject_type"], unique=False
    )
