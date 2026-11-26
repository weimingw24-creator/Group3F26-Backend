"""评分维度（ScoreDimension）与安全规则集（SafetyRuleSet）。

对应 Azure Boards Task #64 `ScoreDimension - app/models/dimension.py`。

与 C# 原实现（`DriverAnalyticsNeon/Models/ScoreDimension.cs`）一一对应：
  - `ScoreDimension`  ：单个事件类型的规则定义（扣分、阈值、缓冲、持续时间）
  - `RiskCategory`    ：风险类别分档（Low / Medium / High，按最低分判定）
  - `SafetyRuleSet`   ：完整规则集 = 规则版本 + 三个事件维度 + 风险分档

报告 Sec 10 口径：风险分 100 起扣，仅 Speeding / Hard Acceleration /
Hard Braking 三类事件参与计算。

字段命名用 snake_case（Python 惯例）；`to_dict()` 输出 camelCase，
与 `mock-dimensions.json`、前端 JSON 保持一致。零第三方依赖，可平移到 Pydantic。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_RULE_VERSION = "classroom-v1.0"

#: 风险分上限：从 100 起扣（报告 Sec 10）
BASE_SCORE = 100.0

_MISSING = object()


def _pick(data: dict[str, Any], *names: str, default: Any = _MISSING) -> Any:
    """按多个候选键名取值，兼容 camelCase / snake_case / PascalCase。

    C# 反序列化时用了 `PropertyNameCaseInsensitive = true`，
    这里用显式键名列表做等价兼容，避免大小写不敏感匹配带来的歧义。
    """
    for name in names:
        if name in data:
            return data[name]
        # 兜底：忽略大小写与下划线比较一次
        target = name.replace("_", "").lower()
        for key, value in data.items():
            if str(key).replace("_", "").lower() == target:
                return value
    if default is _MISSING:
        raise KeyError(f"缺少字段，候选键：{names}")
    return default


@dataclass
class ScoreDimension:
    """单个事件类型的评分维度（一类事件一套阈值 + 扣分）。

    超速用 buffer_kmh / duration_seconds；
    急加速、急刹车用 acceleration_threshold（刹车为负值）。
    """

    key: str
    name: str
    penalty_per_event: float = 3.0
    buffer_kmh: float | None = None
    duration_seconds: int | None = None
    acceleration_threshold: float | None = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoreDimension":
        return cls(
            key=str(_pick(data, "key", "Key", default="")),
            name=str(_pick(data, "name", "Name", default="")),
            penalty_per_event=float(_pick(data, "penaltyPerEvent", "penalty_per_event", default=3.0)),
            buffer_kmh=_optional_float(_pick(data, "bufferKmh", "buffer_kmh", default=None)),
            duration_seconds=_optional_int(_pick(data, "durationSeconds", "duration_seconds", default=None)),
            acceleration_threshold=_optional_float(
                _pick(data, "accelerationThreshold", "acceleration_threshold", default=None)
            ),
            description=str(_pick(data, "description", "Description", default="")),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成 camelCase 字典（与 JSON / 前端字段一致）。"""
        return {
            "key": self.key,
            "name": self.name,
            "penaltyPerEvent": self.penalty_per_event,
            "bufferKmh": self.buffer_kmh,
            "durationSeconds": self.duration_seconds,
            "accelerationThreshold": self.acceleration_threshold,
            "description": self.description,
        }


@dataclass
class RiskCategory:
    """风险类别分档：name + 该档最低分（含）。"""

    name: str
    min_score: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskCategory":
        return cls(
            name=str(_pick(data, "name", "Name", default="")),
            min_score=float(_pick(data, "minScore", "min_score", default=0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "minScore": self.min_score}


def _default_categories() -> list[RiskCategory]:
    """Low 80-100 / Medium 50-79 / High 0-49（报告 Sec 10）。"""
    return [
        RiskCategory(name="Low", min_score=80.0),
        RiskCategory(name="Medium", min_score=50.0),
        RiskCategory(name="High", min_score=0.0),
    ]


def _default_dimensions() -> list[ScoreDimension]:
    """规则文件读不到时的内置兜底（与 C# MockDimensionProvider 一致）。"""
    return [
        ScoreDimension(
            key="speeding",
            name="Speeding",
            penalty_per_event=5.0,
            buffer_kmh=5.0,
            duration_seconds=5,
            description="Speeding episode: > posted limit + 5 km/h for >= 5 s (-5).",
        ),
        ScoreDimension(
            key="acceleration",
            name="Hard Acceleration",
            penalty_per_event=3.0,
            acceleration_threshold=3.0,
            description="Longitudinal accel >= +3.0 m/s^2 (-3).",
        ),
        ScoreDimension(
            key="braking",
            name="Hard Braking",
            penalty_per_event=3.0,
            acceleration_threshold=-3.0,
            description="Longitudinal accel <= -3.0 m/s^2 (-3).",
        ),
    ]


@dataclass
class SafetyRuleSet:
    """完整安全规则集：规则版本 + 事件维度 + 风险分档。"""

    rule_version: str = DEFAULT_RULE_VERSION
    dimensions: list[ScoreDimension] = field(default_factory=_default_dimensions)
    categories: list[RiskCategory] = field(default_factory=_default_categories)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyRuleSet":
        raw_version = _pick(data, "ruleVersion", "rule_version", default="")
        raw_dims = _pick(data, "dimensions", "Dimensions", default=[]) or []
        raw_cats = _pick(data, "categories", "Categories", default=[]) or []

        dimensions = [ScoreDimension.from_dict(d) for d in raw_dims]
        categories = [RiskCategory.from_dict(c) for c in raw_cats]

        return cls(
            rule_version=str(raw_version).strip() or DEFAULT_RULE_VERSION,
            # 文件里没有维度时落回内置兜底，避免后续评分拿到空规则
            dimensions=dimensions or _default_dimensions(),
            categories=categories or _default_categories(),
        )

    @classmethod
    def from_json(cls, text: str) -> "SafetyRuleSet":
        return cls.from_dict(json.loads(text))

    @classmethod
    def default(cls) -> "SafetyRuleSet":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruleVersion": self.rule_version,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "categories": [c.to_dict() for c in self.categories],
        }

    def dimension(self, key: str) -> ScoreDimension | None:
        """按 key 取单个维度（speeding / acceleration / braking）。"""
        for d in self.dimensions:
            if d.key == key:
                return d
        return None

    def category_for(self, score: float) -> str:
        """按分档判风险类别：取所有 min_score <= score 中门槛最高的档位。"""
        matched = [c for c in self.categories if score >= c.min_score]
        if not matched:
            return "High"
        return max(matched, key=lambda c: c.min_score).name


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def dimensions_to_dict(dimensions: Iterable[ScoreDimension]) -> list[dict[str, Any]]:
    """批量转字典的便捷函数（给 API 层序列化用）。"""
    return [d.to_dict() for d in dimensions]
