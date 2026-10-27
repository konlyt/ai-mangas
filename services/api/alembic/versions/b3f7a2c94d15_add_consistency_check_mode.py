"""add consistency check_mode

Revision ID: b3f7a2c94d15
Revises: ea3450e77537
Create Date: 2026-10-19 12:00:00.000000

consistency_reports 表新增一列（方案 A7 收尾）：
    - check_mode：校验模式（ref_lock / feature_card / quality_gate），
      由 consistency_agent 落库时写入真实值；历史行统一回填为
      'quality_gate'（旧行缺少 state 层 check_mode，无法事后区分，
      保守按基础质检口径标注）。

手写迁移而非 autogenerate：对已建表的存量库 autogenerate 易产生空迁移，
显式 add_column/drop_column 更稳（与 8e2a29164810 风格一致）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7a2c94d15'
down_revision: Union[str, None] = 'ea3450e77537'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构：consistency_reports 表追加 check_mode 列并回填历史行。

    步骤：
        1. add_column 追加可空 String(20) 列（对存量数据零影响）；
        2. op.execute 将历史 NULL 行统一回填为 'quality_gate'。

    Returns:
        None

    Raises:
        OperationalError: MySQL 未启动或连接失败时抛出。
    """
    op.add_column(
        "consistency_reports",
        sa.Column(
            "check_mode",
            sa.String(length=20),
            nullable=True,
            comment="校验模式：ref_lock/feature_card/quality_gate",
        ),
    )
    op.execute(
        "UPDATE consistency_reports SET check_mode='quality_gate' WHERE check_mode IS NULL"
    )


def downgrade() -> None:
    """回滚数据库结构：删除 consistency_reports 表的 check_mode 列。

    Returns:
        None
    """
    op.drop_column("consistency_reports", "check_mode")
