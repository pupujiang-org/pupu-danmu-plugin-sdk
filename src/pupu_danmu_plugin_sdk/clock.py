"""Deterministic clock for repeatable local plugin replays."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta


class ReplayClock:
    """An explicit, monotonic UTC clock that never reads the system clock."""

    __slots__ = ("_now",)

    def __init__(self, start: datetime | None = None) -> None:
        initial = start or datetime(2000, 1, 1, tzinfo=UTC)
        if initial.tzinfo is None or initial.utcoffset() is None:
            raise ValueError("replay clock start must be timezone-aware")
        self._now = initial.astimezone(UTC)

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float) -> datetime:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise ValueError(
                "replay clock advance must be a finite non-negative number"
            )
        self._now += timedelta(seconds=seconds)
        return self._now

    def advance_to(self, instant: datetime) -> datetime:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("replay clock instant must be timezone-aware")
        target = instant.astimezone(UTC)
        if target < self._now:
            raise ValueError("replay clock cannot move backwards")
        self._now = target
        return self._now


__all__ = ["ReplayClock"]
