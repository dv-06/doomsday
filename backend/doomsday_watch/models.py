"""Data model for snapshots, shows and source observations.

Every field that ends up in the UI either comes from a source response or is
explicitly marked as derived/heuristic. Nothing here invents showtimes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .config import iso_ist
from .formats import normalise_format

AVAILABILITY_ORDER = {"bookable": 0, "filling_fast": 1, "few_left": 2, "sold_out": 3, "unknown": 4}


def _availability_status(available: int | None, total: int | None, raw_status: str | None) -> str:
    raw = (raw_status or "").strip().lower()
    if available is not None and total is not None:
        if total > 0 and available <= 0:
            return "sold_out"
        if total > 0 and available / total <= 0.15:
            return "few_left"
    if raw in {"sold out", "housefull", "house full", "unavailable"}:
        return "sold_out"
    if raw in {"filling fast", "almost full", "fast filling"}:
        return "filling_fast"
    if raw in {"available", "book now", "open"}:
        return "bookable"
    if available is not None:
        return "bookable" if available > 0 else "sold_out"
    return "unknown"


def _area_dict(area: dict[str, Any]) -> dict[str, Any]:
    total = area.get("sTotal")
    available = area.get("sAvail")
    return {
        "label": area.get("label") or area.get("description") or "General",
        "code": area.get("code"),
        "price": area.get("price"),
        "total_seats": total,
        "available_seats": available,
        "status": _availability_status(available, total, area.get("seatStatus")),
        "status_raw": area.get("seatStatus"),
        "bookable": bool(area.get("disableClick") is False),
        "seat_classes": area.get("seatClasses") or [],
    }


def make_show(
    *,
    platform: str,
    theatre_id: str,
    date: str,
    start: str,
    screen: str,
    raw_format: str,
    areas: Iterable[dict[str, Any]] = (),
    total: int | None = None,
    available: int | None = None,
    raw_status: str | None = None,
    booking_url: str | None = None,
    source_show_id: str | None = None,
    source_time: str | None = None,
    languages: Iterable[str] = (),
    tags: Iterable[str] = (),
    notes: Iterable[str] = (),
) -> dict[str, Any]:
    area_list = [_area_dict(a) for a in areas]
    prices = [a["price"] for a in area_list if isinstance(a["price"], (int, float))]
    area_total = sum(a["total_seats"] or 0 for a in area_list)
    area_avail = sum(a["available_seats"] or 0 for a in area_list)
    total_seats = total if total is not None else (area_total or None)
    available_seats = available if available is not None else (area_avail if area_list else None)

    status = _availability_status(available_seats, total_seats, raw_status)
    if status == "unknown":
        for area in area_list:
            if area["status"] in {"bookable", "few_left"}:
                status = "bookable"
                break
    fmt = normalise_format(raw_format)
    show_id = "|".join([
        platform, theatre_id, date, start, screen or "-", fmt["key"],
        source_show_id or "",
    ])
    return {
        "id": show_id,
        "platform": platform,
        "theatre_id": theatre_id,
        "date": date,
        "start": start,
        "start_iso": f"{date}T{start}:00+05:30" if len(start) == 5 else f"{date}T{start}+05:30",
        "screen": screen or None,
        "format": fmt,
        "languages": list(languages),
        "price": {
            "currency": "INR",
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
        },
        "availability": {
            "status": status,
            "total_seats": total_seats,
            "available_seats": available_seats,
            "status_raw": raw_status,
            "areas": area_list,
            "source_exposes_seat_count": available_seats is not None,
        },
        "booking_url": booking_url,
        "source_show_id": source_show_id,
        "source_time": source_time,
        "tags": list(tags),
        "notes": list(notes),
    }


@dataclass
class TheatreObservation:
    platform: str
    theatre_id: str
    status: str  # ok | not_listed | blocked | error | unavailable | skipped
    listed: bool | None
    venue: dict[str, Any] = field(default_factory=dict)
    shows: list[dict[str, Any]] = field(default_factory=list)
    available_dates: list[str] = field(default_factory=list)
    error: str | None = None
    checked_at: str = field(default_factory=iso_ist)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        dates: dict[str, Any] = {}
        for show in self.shows:
            dates.setdefault(show["date"], {"listed": True, "shows": []})["shows"].append(show)
        for date in self.available_dates:
            dates.setdefault(date, {"listed": False, "shows": []})
        return {
            "platform": self.platform,
            "theatre_id": self.theatre_id,
            "status": self.status,
            "listed": self.listed,
            "venue": self.venue,
            "shows": sorted(self.shows, key=lambda s: s["start_iso"]),
            "dates": {
                d: {
                    "listed": bool(v["shows"]),
                    "shows": sorted(v["shows"], key=lambda s: s["start_iso"]),
                }
                for d, v in sorted(dates.items())
            },
            "error": self.error,
            "checked_at": self.checked_at,
            "notes": self.notes,
        }


@dataclass
class SourceResult:
    source: str
    status: str  # ok | partial | blocked | error
    message: str
    checked_at: str = field(default_factory=iso_ist)
    evidence: dict[str, Any] = field(default_factory=dict)
    movie: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, TheatreObservation] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "partial"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "message": self.message,
            "checked_at": self.checked_at,
            "evidence": self.evidence,
            "movie": self.movie,
            "notes": self.notes,
        }


def summarise_shows(shows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    shows = list(shows)
    formats: dict[str, dict[str, Any]] = {}
    for show in shows:
        key = show["format"]["key"]
        entry = formats.setdefault(key, {
            "key": key,
            "label": show["format"]["label"],
            "is_3d": show["format"]["is_3d"],
            "is_premium": show["format"]["is_premium"],
            "show_count": 0,
        })
        entry["show_count"] += 1
    avail = [s["availability"]["available_seats"] for s in shows if s["availability"]["available_seats"] is not None]
    return {
        "show_count": len(shows),
        "formats": sorted(formats.values(), key=lambda f: f["label"]),
        "booking_status": min(
            (s["availability"]["status"] for s in shows),
            key=lambda s: AVAILABILITY_ORDER.get(s, 9),
            default="unknown",
        ),
        "seats_available": sum(avail) if avail else None,
        "price_min": min((s["price"]["min"] for s in shows if s["price"]["min"] is not None), default=None),
        "price_max": max((s["price"]["max"] for s in shows if s["price"]["max"] is not None), default=None),
    }
