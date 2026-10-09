"""
用户相关响应模型。

定义用户信息、配额、用量统计的 Pydantic 结构。
"""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class UserOut(BaseModel):
    """用户信息输出模型。

    Attributes:
        id: 用户ID。
        username: 用户名。
        email: 邮箱。
        phone: 手机号。
        avatar: 头像URL。
        vip_level: 会员等级。
        quota: 剩余点数。
        status: 状态（0禁用 1正常）。
    """

    id: int
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    vip_level: int
    quota: int
    status: int

    class Config:
        """Pydantic 配置：允许从 ORM 对象读取属性。"""

        from_attributes = True


class QuotaOut(BaseModel):
    """用户配额输出模型。

    Attributes:
        quota: 剩余点数。
        vip_level: 会员等级。
    """

    quota: int
    vip_level: int


class DailyUsage(BaseModel):
    """单日用量明细。

    Attributes:
        date: 日期（YYYY-MM-DD）。
        cost_points: 当日消耗点数。
    """

    date: date
    cost_points: int = 0


class UsageOut(BaseModel):
    """用户用量统计输出模型。

    Attributes:
        project_count: 项目总数。
        image_count: 图片数量。
        video_duration: 视频时长（秒）。
        cost_points: 累计消耗点数。
        daily: 按日统计数组。
    """

    project_count: int = 0
    image_count: int = 0
    video_duration: int = 0
    cost_points: int = 0
    daily: List[DailyUsage] = []
