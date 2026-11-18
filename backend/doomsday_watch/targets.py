"""Programmatic target-date rules.

Keeping the rules here (not as hand-written JSON) makes it impossible to
silently drop a date when the list is regenerated.
"""

from __future__ import annotations

from datetime import date, timedelta


def ramayana_target_dates() -> tuple[str, ...]:
    """19–30 Nov 2026 plus every Sat/Sun in Dec 2026, in IST calendar dates."""
    dates: list[date] = []
    current = date(2026, 11, 19)
    end = date(2026, 11, 30)
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)

    current = date(2026, 12, 1)
    end = date(2026, 12, 31)
    while current <= end:
        if current.weekday() >= 5:  # Saturday=5, Sunday=6
            dates.append(current)
        current += timedelta(days=1)
    return tuple(d.isoformat() for d in dates)
