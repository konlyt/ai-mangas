"""add character ref board

Revision ID: 8e2a29164810
Revises: 1a90ce337774
Create Date: 2026-10-19 10:49:50.394222

characters 表新增两列（方案 A3）：
    - ref_board_url：四视图参考板 URL（头特写/正面/右侧90°/背面）
    - character_locks：不可变锚点 JSON（costume/hairstyle/appearance/body_type）

手写迁移而非 autogenerate：对已建表的存量库 autogenerate 易产生空迁移，
显式 add_column/drop_column 更稳。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e2a29164810'
down_revision: Union[str, None] = '1a90ce337774'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构：characters 表追加 ref_board_url / character_locks 两列。

    两列均可空、无默认值，对存量数据零影响（无需回填）。

    Returns:
        None

    Raises:
        OperationalError: MySQL 未启动或连接失败时抛出。
    """
    op.add_column(
        "characters",
        sa.Column(
            "ref_board_url",
            sa.String(length=255),
            nullable=True,
            comment="四视图参考板URL（头特写/正面/右侧90°/背面）",
        ),
    )
    op.add_column(
        "characters",
        sa.Column(
            "character_locks",
            sa.JSON(),
            nullable=True,
            comment="不可变锚点JSON：costume/hairstyle/appearance/body_type",
        ),
    )


def downgrade() -> None:
    """回滚数据库结构：删除 characters 表的两列。

    Returns:
        None
    """
    op.drop_column("characters", "character_locks")
    op.drop_column("characters", "ref_board_url")
