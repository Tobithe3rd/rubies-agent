from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from core.config import AppConfig


class Clock:
    """Timezone-aware clock.

    The timezone comes from config (settings.timezone), never hardcoded. The
    time source is injectable so tests can freeze time:
        Clock("Africa/Lagos", now_source=lambda: datetime(2026, 1, 1, 0, 0))
    """

    def __init__(self, timezone_name: str, now_source: Optional[Callable[[], datetime]] = None):
        self._tz = ZoneInfo(timezone_name)
        self._now_source = now_source or datetime.now

    def now(self) -> datetime:
        moment = self._now_source()
        if moment.tzinfo is None:
            return moment.replace(tzinfo=self._tz)
        return moment.astimezone(self._tz)

    def iso_now(self) -> str:
        """ISO-8601 string with offset, e.g. 2026-10-27T20:30:00+01:00."""
        return self.now().isoformat()

    def naive_local_now(self) -> datetime:
        """Same wall time without tzinfo, for SQLite's naive TEXT columns."""
        return self.now().replace(tzinfo=None)

    def __repr__(self) -> str:
        return f"Clock(timezone={self._tz.key!r})"


def create_clock(cfg: AppConfig) -> Clock:
    return Clock(cfg.settings.timezone)


# Convenience entry points that use the real config, built once and cached.
_default_clock: Optional[Clock] = None


def _clock() -> Clock:
    global _default_clock
    if _default_clock is None:
        from core.config import load_config

        _default_clock = create_clock(load_config())
    return _default_clock


def now() -> datetime:
    return _clock().now()


def iso_now() -> str:
    return _clock().iso_now()


def naive_local_now() -> datetime:
    return _clock().naive_local_now()
