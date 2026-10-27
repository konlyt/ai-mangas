"""drop canvas_documents

Revision ID: d7e0f5a92b13
Revises: c6d9e4f81a02
Create Date: 2026-10-19 18:45:00.000000

回退画布功能（产品决策：放弃无限画布，保留人物一致性链路）。
删除 canvas_documents 表及其唯一索引，与已应用的 c6d9e4f81a02 迁移反向。
手写迁移（与 c6d9e4f81a02 风格一致），不依赖 autogenerate。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e0f5a92b13'
down_revision: Union[str, None] = 'c6d9e4f81a02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构：删除 canvas_documents 表与 project_id 唯一索引。

    Returns:
        None

    Raises:
        OperationalError: 数据库连接失败时抛出。
    """
    op.drop_index('uk_canvas_documents_project', table_name='canvas_documents')
    op.drop_table('canvas_documents')


def downgrade() -> None:
    """回滚数据库结构：重建 canvas_documents 表与唯一索引。

    Returns:
        None
    """
    op.create_table(
        'canvas_documents',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('project_id', sa.BigInteger(), nullable=False, comment='项目ID（每项目一份）'),
        sa.Column('nodes', sa.JSON(), nullable=False, comment='节点列表JSON：[{id,type,position,data,dims}]'),
        sa.Column('edges', sa.JSON(), nullable=False, comment='边列表JSON：[{id,source,target,sourceHandle,targetHandle}]'),
        sa.Column('viewport', sa.JSON(), nullable=False, comment='视口JSON：{x,y,zoom}'),
        sa.Column('revision', sa.Integer(), server_default=sa.text("'0'"), nullable=False, comment='版本号（乐观锁，每次保存+1）'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uk_canvas_documents_project', 'canvas_documents', ['project_id'], unique=True)
