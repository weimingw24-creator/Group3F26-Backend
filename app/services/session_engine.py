"""驾驶会话引擎（核心业务流程）。

对应 Azure Boards Task #58 `SessionEngine - app/services/session_engine.py`。

流程：
  1. 驾驶员点击“开始记录” → 创建行程（关联车辆，状态 Active）
  2. GPS 开始逐条读取 mock 数据（MockGpsDataService）
  3. 业务逻辑（ScoringService）按报告 Sec 10 规则计算风险分/类别
  4. 评分维度（ScoreDimension）写入存储（ScoreStorageService）
  5. 前端通过 API 从存储层读取最新评分并展示

依赖均通过构造函数注入，便于替换成 MongoDB 实现或测试替身。
"""

from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.session import DriverSession, TripStatus
from app.models.snapshot import ScoreSnapshot

_logger = logging.getLogger(__name__)


async def _resolve(value: Any) -> Any:
    """兼容同步/异步的依赖实现：协程就 await，普通值原样返回。"""
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass
class ActiveSession:
    """内存中的活跃行程状态（C# 里的 ActiveSession）。"""

    session: DriverSession
    rule_set: Any
    samples: list[Any] = field(default_factory=list)
    last_sample_time: datetime = field(default_factory=datetime.now)
    last_dimension: ScoreSnapshot | None = None

    def __post_init__(self) -> None:
        self.last_sample_time = self.session.started_at


class SessionEngine:
    """行程编排：start / advance / end，状态存内存，结果落库。"""

    MAX_SAMPLES = 5000  # 防止长行程样本无限增长

    def __init__(
        self,
        gps: Any,
        dimensions: Any,
        scoring: Any,
        storage: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        :param gps: MockGpsDataService，需有 reset()（可选）与 next_sample(timestamp, step_seconds)
        :param dimensions: MockDimensionProvider，需有 get_rule_set()
        :param scoring: ScoringService，需有 compute_score(session_id, rule_set, samples, started_at, now)
        :param storage: ScoreStorageService，需有 save_session / save_dimension / get_latest_dimension / get_recent_sessions
        :param logger: 日志器，缺省用模块 logger
        """
        self._gps = gps
        self._dimensions = dimensions
        self._scoring = scoring
        self._storage = storage
        self._logger = logger or _logger

        # session_id -> ActiveSession，相当于 C# 的 ConcurrentDictionary
        self._active: dict[str, ActiveSession] = {}

    @property
    def storage_mode(self) -> str:
        return str(getattr(self._storage, "storage_mode", "unknown"))

    async def start_session(
        self,
        driver_name: str,
        vehicle_id: str | None = None,
        vehicle_label: str | None = None,
    ) -> DriverSession:
        """开始一次新的驾驶行程（报告 UC05：驾驶员选择自己的车辆后开始）。"""
        now = datetime.now()

        session = DriverSession(
            session_id=uuid.uuid4().hex,
            driver_name=(driver_name or "").strip() or "Driver",
            started_at=now,
            is_active=True,
            status=TripStatus.ACTIVE,
            vehicle_id=vehicle_id,
            vehicle_label=vehicle_label,
            sample_data_flag=True,
        )

        active = ActiveSession(session=session, rule_set=await _resolve(self._dimensions.get_rule_set()))

        self._active[session.session_id] = active
        await _resolve(self._storage.save_session(session))

        # GPS 游标回到数据流开头（单例实现才有 reset；按会话新建时可省略）
        reset = getattr(self._gps, "reset", None)
        if callable(reset):
            await _resolve(reset())

        # 生成第一个 GPS 样本并计算初始评分
        first = await _resolve(self._gps.next_sample(session.started_at, 1.0))
        active.samples.append(first)

        dimension = await _resolve(
            self._scoring.compute_score(
                session.session_id,
                active.rule_set,
                active.samples,
                session.started_at,
                datetime.now(),
            )
        )
        active.last_dimension = dimension
        await _resolve(self._storage.save_dimension(dimension))

        self._logger.info(
            "Trip %s started for %s (vehicle %s).",
            session.session_id,
            session.driver_name,
            vehicle_label or "none",
        )
        return session

    async def advance(self, session_id: str) -> ScoreSnapshot | None:
        """推进当前会话：产生一个新样本、重算评分、写入存储。"""
        active = self._active.get(session_id)
        if active is None:
            return None

        now = datetime.now()
        step = max(0.1, (now - active.last_sample_time).total_seconds())
        active.last_sample_time = now

        sample = await _resolve(self._gps.next_sample(now, step))
        active.samples.append(sample)

        if len(active.samples) > self.MAX_SAMPLES:
            del active.samples[: len(active.samples) - self.MAX_SAMPLES]

        dimension = await _resolve(
            self._scoring.compute_score(
                session_id,
                active.rule_set,
                active.samples,
                active.session.started_at,
                now,
            )
        )
        active.last_dimension = dimension

        # 同步会话状态并落库
        active.session.sample_count = getattr(dimension, "sample_count", len(active.samples))
        active.session.duration_seconds = getattr(dimension, "elapsed_seconds", 0.0)

        await _resolve(self._storage.save_session(active.session))
        await _resolve(self._storage.save_dimension(dimension))

        return dimension

    async def end_session(self, session_id: str) -> DriverSession | None:
        """结束会话（报告 UC05：重复 End 不重复结算），计算最终风险分并落库。"""
        active = self._active.pop(session_id, None)
        if active is None:
            return None

        now = datetime.now()
        dimension = await _resolve(
            self._scoring.compute_score(
                session_id,
                active.rule_set,
                active.samples,
                active.session.started_at,
                now,
            )
        )
        active.last_dimension = dimension

        active.session.is_active = False
        active.session.status = TripStatus.COMPLETED
        active.session.ended_at = now
        active.session.final_score = getattr(dimension, "overall_score", None)
        active.session.risk_category = getattr(dimension, "risk_category", None)
        active.session.sample_count = getattr(dimension, "sample_count", len(active.samples))
        active.session.duration_seconds = getattr(dimension, "elapsed_seconds", 0.0)

        await _resolve(self._storage.save_session(active.session))
        await _resolve(self._storage.save_dimension(dimension))

        self._logger.info(
            "Trip %s ended with risk %s (%s).",
            session_id,
            active.session.final_score,
            active.session.risk_category,
        )
        return active.session

    async def get_latest(self, session_id: str) -> ScoreSnapshot | None:
        """获取某会话的最新评分维度：先看内存，再回落到存储层。"""
        active = self._active.get(session_id)
        if active is not None and active.last_dimension is not None:
            return active.last_dimension
        return await _resolve(self._storage.get_latest_dimension(session_id))

    async def get_recent_sessions(
        self, limit: int = 20, driver_name: str | None = None
    ) -> list[DriverSession]:
        """获取最近的历史行程。员工可看全部；司机只看自己的（报告 UC11 授权边界）。"""
        return await _resolve(self._storage.get_recent_sessions(limit, driver_name))

    def is_active(self, session_id: str) -> bool:
        return session_id in self._active
