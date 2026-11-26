"""驾驶风险评分业务逻辑（纯函数，可重复计算）。

对应 Azure Boards Task #61 `ScoringService - app/core/scoring.py`，
对齐 Phase-2 报告 Sec 10 与 C# `DriverAnalyticsNeon/Services/ScoringService.cs`：

  - 风险分从 100 起扣，clamp 到 0~100，保留 1 位小数；
  - Speeding：速度 > posted limit + buffer（默认 +5 km/h），且持续 >= 5 秒，
    算 1 个 distinct episode，每个 -5；posted limit 缺失的样本不参与判定（不编造）；
  - Harsh Acceleration：纵向加速度 >= 阈值（默认 +3.0 m/s²），每个事件 -3；
  - Harsh Braking：纵向加速度 <= 阈值（默认 -3.0 m/s²），每个事件 -3；
  - 风险类别：Low 80-100 / Medium 50-79 / High 0-49；
  - 结果带 rule_version（报告 Sec 8）。

阈值与扣分优先取自规则集（`SafetyRuleSet`），缺省时回落到报告里的固定值。
样本既可以是 dict（如 GPS 数据流直接产出的记录），也可以是带属性的对象
（如后续 `GpsSample` 模型），取值时两种都兼容。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence

from app.models.dimension import BASE_SCORE, SafetyRuleSet, ScoreDimension
from app.models.snapshot import DimensionScore, ScoreSnapshot

# 规则集缺项时的兜底（与报告 Sec 10 / C# 默认值一致）
_DEFAULT_SPEEDING_PENALTY = 5.0
_DEFAULT_EVENT_PENALTY = 3.0
_DEFAULT_BUFFER_KMH = 5.0
_DEFAULT_SPEEDING_DURATION_S = 5
_DEFAULT_ACCEL_THRESHOLD = 3.0
_DEFAULT_BRAKE_THRESHOLD = -3.0

_EPSILON = 1e-9


def _get(sample: Any, *names: str, default: Any = None) -> Any:
    """从 dict 或对象上取字段，兼容 camelCase / snake_case。"""
    if isinstance(sample, dict):
        for name in names:
            if name in sample:
                return sample[name]
        target = names[0].replace("_", "").lower()
        for key, value in sample.items():
            if str(key).replace("_", "").lower() == target:
                return value
        return default
    for name in names:
        if hasattr(sample, name):
            return getattr(sample, name)
    # 对象上也试一次驼峰转换
    camel = names[0]
    parts = camel.split("_")
    camel_name = parts[0] + "".join(p.capitalize() for p in parts[1:])
    if hasattr(sample, camel_name):
        return getattr(sample, camel_name)
    return default


def _as_datetime(value: Any) -> datetime:
    """时间字段可能是 datetime，也可能是 ISO 字符串。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    raise TypeError(f"无法解析时间字段：{value!r}")


def _clamp_score(value: float) -> float:
    return round(min(max(value, 0.0), BASE_SCORE), 1)


class ScoringService:
    """按规则集对 GPS 样本序列打分，产出 `ScoreSnapshot`。"""

    def compute_score(
        self,
        session_id: str,
        rule_set: SafetyRuleSet,
        samples: Sequence[Any] | Iterable[Any],
        started_at: datetime,
        now: datetime | None = None,
    ) -> ScoreSnapshot:
        """计算一次评分快照。

        :param session_id: 行程 ID
        :param rule_set: 安全规则集（提供阈值、扣分、分档、规则版本）
        :param samples: GPS 样本序列（dict 或对象均可）
        :param started_at: 行程开始时间
        :param now: 评分时刻，缺省为当前时间
        """
        samples = list(samples)
        now = now or datetime.now()

        snapshot = ScoreSnapshot(
            session_id=session_id,
            recorded_at=now,
            sample_count=len(samples),
            elapsed_seconds=max(0.0, (now - started_at).total_seconds()),
            rule_version=rule_set.rule_version,
        )

        # 没有任何样本：满分、按分档归类、各维度 0 扣分
        if not samples:
            snapshot.overall_score = BASE_SCORE
            snapshot.risk_category = rule_set.category_for(BASE_SCORE)
            snapshot.dimensions = [
                DimensionScore(key=d.key, name=d.name, score=BASE_SCORE)
                for d in rule_set.dimensions
            ]
            return snapshot

        speeding_dim = rule_set.dimension("speeding")
        accel_dim = rule_set.dimension("acceleration")
        brake_dim = rule_set.dimension("braking")

        speeding_episodes = self.count_speeding_episodes(samples, rule_set)
        accel_threshold = (
            accel_dim.acceleration_threshold if accel_dim and accel_dim.acceleration_threshold is not None
            else _DEFAULT_ACCEL_THRESHOLD
        )
        brake_threshold = (
            brake_dim.acceleration_threshold if brake_dim and brake_dim.acceleration_threshold is not None
            else _DEFAULT_BRAKE_THRESHOLD
        )

        accel_events = sum(
            1 for s in samples if self._acceleration(s) >= accel_threshold - _EPSILON
        )
        brake_events = sum(
            1 for s in samples if self._acceleration(s) <= brake_threshold + _EPSILON
        )

        speeding_penalty = speeding_episodes * (
            speeding_dim.penalty_per_event if speeding_dim else _DEFAULT_SPEEDING_PENALTY
        )
        accel_penalty = accel_events * (accel_dim.penalty_per_event if accel_dim else _DEFAULT_EVENT_PENALTY)
        brake_penalty = brake_events * (brake_dim.penalty_per_event if brake_dim else _DEFAULT_EVENT_PENALTY)

        overall = _clamp_score(BASE_SCORE - speeding_penalty - accel_penalty - brake_penalty)

        snapshot.overall_score = overall
        snapshot.risk_category = rule_set.category_for(overall)
        snapshot.speeding_episodes = speeding_episodes
        snapshot.hard_accel_events = accel_events
        snapshot.hard_brake_events = brake_events
        snapshot.dimensions = [
            DimensionScore(
                key="speeding",
                name=(speeding_dim.name if speeding_dim else "Speeding"),
                score=_clamp_score(BASE_SCORE - speeding_penalty),
                penalty=speeding_penalty,
                event_count=speeding_episodes,
            ),
            DimensionScore(
                key="acceleration",
                name=(accel_dim.name if accel_dim else "Hard Acceleration"),
                score=_clamp_score(BASE_SCORE - accel_penalty),
                penalty=accel_penalty,
                event_count=accel_events,
            ),
            DimensionScore(
                key="braking",
                name=(brake_dim.name if brake_dim else "Hard Braking"),
                score=_clamp_score(BASE_SCORE - brake_penalty),
                penalty=brake_penalty,
                event_count=brake_events,
            ),
        ]

        # 附带最新 GPS 样本供前端展示
        snapshot.latest_gps = samples[-1]
        return snapshot

    # ---- 事件检测 ----

    @staticmethod
    def count_speeding_episodes(samples: Sequence[Any], rule_set: SafetyRuleSet) -> int:
        """统计 distinct speeding episodes。

        规则：连续样本中速度超过 `posted limit + buffer`，且首尾时间跨度
        >= durationSeconds 的一段，计 1 个 episode。
        posted limit 缺失的样本视为"不超速"，不会开启也不会延续一段 episode。
        """
        dim: ScoreDimension | None = rule_set.dimension("speeding")
        buffer_kmh = dim.buffer_kmh if dim and dim.buffer_kmh is not None else _DEFAULT_BUFFER_KMH
        min_duration = (
            dim.duration_seconds if dim and dim.duration_seconds is not None else _DEFAULT_SPEEDING_DURATION_S
        )

        episodes = 0
        run_start: int | None = None

        for i, sample in enumerate(samples):
            over = ScoringService._is_over_limit(sample, buffer_kmh)
            if over and run_start is None:
                run_start = i
            elif not over and run_start is not None:
                duration = ScoringService._span_seconds(samples, run_start, i)
                if duration >= min_duration - _EPSILON:
                    episodes += 1
                run_start = None

        if run_start is not None:
            duration = ScoringService._span_seconds(samples, run_start, len(samples) - 1)
            if duration >= min_duration - _EPSILON:
                episodes += 1

        return episodes

    # ---- 字段读取（dict / 对象兼容） ----

    @staticmethod
    def _speed(sample: Any) -> float:
        value = _get(sample, "speed_kmh", "speed", "SpeedKmh", default=0.0)
        return float(value or 0.0)

    @staticmethod
    def _acceleration(sample: Any) -> float:
        value = _get(
            sample,
            "longitudinal_acceleration",
            "acceleration",
            "LongitudinalAcceleration",
            default=0.0,
        )
        return float(value or 0.0)

    @staticmethod
    def _posted_limit(sample: Any) -> float | None:
        value = _get(
            sample,
            "posted_speed_limit_kmh",
            "posted_limit_kmh",
            "PostedSpeedLimitKmh",
            default=None,
        )
        return None if value is None else float(value)

    @staticmethod
    def _timestamp(sample: Any) -> datetime:
        value = _get(sample, "timestamp", "Timestamp", default=None)
        return _as_datetime(value)

    @staticmethod
    def _is_over_limit(sample: Any, buffer_kmh: float) -> bool:
        """是否超限；无 posted limit 一律返回 False（报告 Sec 10：不编造超速）。"""
        limit = ScoringService._posted_limit(sample)
        if limit is None:
            return False
        return ScoringService._speed(sample) > limit + buffer_kmh

    @staticmethod
    def _span_seconds(samples: Sequence[Any], start: int, end: int) -> float:
        try:
            start_ts = ScoringService._timestamp(samples[start])
            end_ts = ScoringService._timestamp(samples[end])
            return (end_ts - start_ts).total_seconds()
        except (TypeError, ValueError):
            return 0.0
