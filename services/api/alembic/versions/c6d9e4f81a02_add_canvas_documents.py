"""add canvas_documents

Revision ID: c6d9e4f81a02
Revises: b3f7a2c94d15
Create Date: 2026-10-19 16:00:00.000000

画布文档表（B2 数据层）：
    - 每项目一份主画布（project_id 唯一索引 uk_canvas_documents_project）
    - nodes / edges / viewport 整体 JSON 存储
    - revision 整型乐观锁，每次保存 +1，初始为 0

手写迁移而非 autogenerate：对已建表的存量库 autogenerate 易产生空迁移，
显式 create_table/create_index 更稳（与 8e2a29164810 风格一致）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6d9e4f81a02'
down_revision: Union[str, None] = 'b3f7a2c94d15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构：新建 canvas_documents 表与 project_id 唯一索引。

    表为全新创建，对存量数据零影响。

    Returns:
        None

    Raises:
        OperationalError: MySQL 未启动或连接失败时抛出。
    """
    op.create_table('canvas_documents',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
    sa.Column('project_id', sa.BigInteger(), nullable=False, comment='项目ID（每项目一份）'),
    sa.Column('nodes', sa.JSON(), nullable=False, comment='节点列表JSON：[{id,type,position,data,dims}]'),
    sa.Column('edges', sa.JSON(), nullable=False, comment='边列表JSON：[{id,source,target,sourceHandle,targetHandle}]'),
    sa.Column('viewport', sa.JSON(), nullable=False, comment='视口JSON：{x,y,zoom}'),
    sa.Column('revision', sa.Integer(), server_default=sa.text("'0'"), nullable=False, comment='版本号（乐观锁，每次保存+1）'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='创建时间'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='更新时间'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uk_canvas_documents_project', 'canvas_documents', ['project_id'], unique=True)


def downgrade() -> None:
    """回滚数据库结构：删除 canvas_documents 表及其唯一索引。

    Returns:
        None
    """
    op.drop_index('uk_canvas_documents_project', table_name='canvas_documents')
    op.drop_table('canvas_documents')
