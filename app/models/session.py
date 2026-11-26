"""行程（DriverSession）与状态枚举。

对应 Azure Boards Task #60 `DriverSession - app/models/session.py`。
先用标准库 dataclass 保证零依赖可跑；团队若要字段校验，可平移到 Pydantic
BaseModel（字段名保持不变，camelCase 仅在 API 层转换）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TripStatus(str, Enum):
    """行程状态。字符串值直接进 Mongo 与 JSON，前端无需再映射。"""

    ACTIVE = "Active"
    COMPLETED = "Completed"


@dataclass
class DriverSession:
    """一次从开始到结束的行程；评分的分析单元。"""

    session_id: str
    driver_name: str
    started_at: datetime
    is_active: bool = True
    status: TripStatus = TripStatus.ACTIVE
    vehicle_id: str | None = None
    vehicle_label: str | None = None
    sample_data_flag: bool = True  # 演示数据标记（报告 Sec 8）
    ended_at: datetime | None = None
    final_score: float | None = None
    risk_category: str | None = None
    sample_count: int = 0
    duration_seconds: float = 0.0
