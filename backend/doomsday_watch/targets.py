"""Programmatic target-date rules.

Ramayana is intentionally not an every-day range. These are the exact dates
agreed for the 2026 Bengaluru 4DX watch, and they are asserted in tests.
"""

from __future__ import annotations

# Ordered, unique, and deliberately excludes 20/23-27/30 Nov and late December.
RAMAYANA_2026_DATES: tuple[str, ...] = (
    "2026-11-18",  # Wednesday, today
    "2026-11-19",  # Thursday, tomorrow
    "2026-11-21",  # Saturday
    "2026-11-22",  # Sunday
    "2026-11-28",  # Saturday
    "2026-11-29",  # Sunday
    "2026-12-05",  # Saturday
    "2026-12-06",  # Sunday
    "2026-12-12",  # Saturday
    "2026-12-13",  # Sunday
)


def ramayana_target_dates() -> tuple[str, ...]:
    return RAMAYANA_2026_DATES
