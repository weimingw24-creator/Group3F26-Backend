"""评分结果（ScoreSnapshot）与各维度得分（DimensionScore）。

配套 Task #61 `ScoringService - app/core/scoring.py`；C# 侧对应
`DriverAnalyticsNeon/Models/ScoreSnapshot.cs`。

注意与 `app/models/dimension.py` 的区别：
  - `ScoreDimension`（规则定义）：某类事件的阈值、扣分、缓冲、持续时间
  - `ScoreSnapshot`（评分结果）：某一时刻算出的总分、风险类别、事件计数、
    各维度得分，以及当时的规则版本

字段用 snake_case（Python 惯例），`to_dict()` 输出 camelCase，便于 API/前端直接消费。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.dimension import BASE_SCORE, DEFAULT_RULE_VERSION


@dataclass
class DimensionScore:
    """单个事件类型的得分与扣分（报告 Sec 10：每类事件独立扣分）。"""

    key: str
    name: str
    score: float = BASE_SCORE  # 该维度得分 0~100
    penalty: float = 0.0
    event_count: int = 0
    weight: float = 0.0  # 兼容保留，不参与总分

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DimensionScore":
        return cls(
            key=str(_pick(data, "key", default="")),
            name=str(_pick(data, "name", default="")),
            score=float(_pick(data, "score", default=BASE_SCORE)),
            penalty=float(_pick(data, "penalty", default=0.0)),
            event_count=int(_pick(data, "eventCount", "event_count", default=0)),
            weight=float(_pick(data, "weight", default=0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "score": self.score,
            "penalty": self.penalty,
            "eventCount": self.event_count,
            "weight": self.weight,
        }


@dataclass
class ScoreSnapshot:
    """某次风险评分快照：总分 + 风险类别 + 事件计数 + 各维度得分 + GPS 摘要。"""

    session_id: str
    recorded_at: datetime
    overall_score: float = BASE_SCORE
    risk_category: str = "High"
    rule_version: str = DEFAULT_RULE_VERSION
    speeding_episodes: int = 0
    hard_accel_events: int = 0
    hard_brake_events: int = 0
    dimensions: list[DimensionScore] = field(default_factory=list)
    latest_gps: Any | None = None
    sample_count: int = 0
    elapsed_seconds: float = 0.0

    def dimension(self, key: str) -> DimensionScore | None:
        """按 key 取某个维度的得分明细。"""
        for d in self.dimensions:
            if d.key == key:
                return d
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "recordedAt": self.recorded_at.isoformat(),
            "overallScore": self.overall_score,
            "riskCategory": self.risk_category,
            "ruleVersion": self.rule_version,
            "speedingEpisodes": self.speeding_episodes,
            "hardAccelEvents": self.hard_accel_events,
            "hardBrakeEvents": self.hard_brake_events,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "sampleCount": self.sample_count,
            "elapsedSeconds": self.elapsed_seconds,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _pick(data: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data:
            return data[name]
        target = name.replace("_", "").lower()
        for key, value in data.items():
            if str(key).replace("_", "").lower() == target:
                return value
    return default
