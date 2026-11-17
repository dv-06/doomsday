"""Seat recommendation engine.

Two modes, never mixed silently:

* ``layout``     – an actual seat map with coordinates is available (supplied as
                   data/seatmaps/<theatre-id>.json, or captured from a public
                   layout when one is exposed). Seats are scored by horizontal
                   distance from the screen centre and viewing depth.
* ``heuristic``  – no seat numbers are public. We use the *real* published
                   auditorium/area data for the chosen show (area names, seat
                   counts, prices) and recommend a zone, explicitly labelled as
                   a heuristic. We never invent row or seat numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .formats import format_depth_guidance

EDGE_LEFT = 0.12
EDGE_RIGHT = 0.88


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def load_layout(path: Path) -> dict[str, Any] | None:
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return layout if isinstance(layout, dict) and isinstance(layout.get("rows"), list) else None


def _normalise_layout(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten rows into seats with x (0..1 left→right) and y (0..1 front→back)."""
    rows = [r for r in layout.get("rows", []) if isinstance(r, dict)]
    seats: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        row_seats = [s for s in (row.get("seats") or []) if isinstance(s, dict)]
        count = len(row_seats)
        for seat_index, seat in enumerate(row_seats):
            x = seat.get("x")
            if not isinstance(x, (int, float)):
                x = (seat_index / (count - 1)) if count > 1 else 0.5
            y = seat.get("y")
            if not isinstance(y, (int, float)):
                y = (row_index / (len(rows) - 1)) if len(rows) > 1 else 0.5
            seats.append({
                "row": str(row.get("row") or row.get("id") or row_index + 1),
                "number": str(seat.get("number") or seat.get("id") or seat_index + 1),
                "x": _clamp(float(x)),
                "y": _clamp(float(y)),
                "type": str(seat.get("type") or "standard"),
                "status": str(seat.get("status") or "unknown").lower(),
                "price": seat.get("price"),
            })
    return seats


def _score_seat(seat: dict[str, Any], low: float, high: float) -> tuple[float, list[str]]:
    reasons: list[str] = []
    centre_offset = abs(seat["x"] - 0.5)
    centrality = 1 - _clamp(centre_offset / 0.5)
    if centre_offset <= 0.08:
        reasons.append("almost dead-centre horizontally, so the screen is symmetrical")
    elif centre_offset <= 0.2:
        reasons.append("inside the centre block")
    else:
        reasons.append("off to the side of the screen centre")

    if low <= seat["y"] <= high:
        depth = 1.0
        reasons.append("in the preferred middle-to-rear viewing band")
    else:
        gap = (low - seat["y"]) if seat["y"] < low else (seat["y"] - high)
        depth = _clamp(1 - gap / 0.3)
        if seat["y"] < low:
            reasons.append("closer to the screen than ideal for this format")
        else:
            reasons.append("further back than ideal, but still comfortable")

    if seat["y"] < 0.18:
        depth *= 0.35
        reasons.append("very front row: neck strain and distorted geometry")
    if seat["x"] < EDGE_LEFT or seat["x"] > EDGE_RIGHT:
        reasons.append("extreme side seat: off-axis viewing and audio imbalance")

    type_bonus = {"recliner": 0.08, "premium": 0.05, "executive": 0.03}.get(seat["type"], 0.0)
    if type_bonus:
        reasons.append(f"{seat['type']} seating")

    score = 0.55 * centrality + 0.45 * depth + type_bonus
    return round(score, 4), reasons


def recommend_from_layout(layout: dict[str, Any], format_key: str) -> dict[str, Any]:
    seats = _normalise_layout(layout)
    low, high, depth_note = format_depth_guidance(format_key)
    available = [s for s in seats if s["status"] in {"available", "open", "vacant", ""}]
    scored = []
    for seat in available:
        score, reasons = _score_seat(seat, low, high)
        scored.append({**seat, "score": score, "reasons": reasons})
    scored.sort(key=lambda s: s["score"], reverse=True)

    best = scored[:6]
    second = scored[6:12]
    avoid = sorted(
        [s for s in seats if s["status"] in {"available", "open", "vacant", ""}],
        key=lambda s: _score_seat(s, low, high)[0],
    )[:4]
    unavailable = sorted({s["status"] for s in seats if s["status"] not in {"available", "open", "vacant", ""}})

    return {
        "mode": "layout",
        "label": "Seat-map based recommendation",
        "screen": layout.get("screen"),
        "total_seats": len(seats),
        "available_seats": len(available),
        "best": best,
        "second_best": second,
        "avoid": [{**s, "reasons": _score_seat(s, low, high)[1]} for s in avoid],
        "depth_note": depth_note,
        "notes": [
            "Scored from the supplied seat map geometry: horizontal distance from the screen centre, "
            "viewing depth for this format, and side-edge penalties.",
            f"Seat statuses present in the map: {', '.join(unavailable) if unavailable else 'available only'}.",
        ],
        "disclaimer": "Coordinates come from the supplied layout. Verify seat labels on the booking page before paying.",
        "unavailable_statuses": unavailable,
    }


def heuristic_recommendation(shows: Iterable[dict[str, Any]], theatre_id: str) -> dict[str, Any] | None:
    shows = [s for s in shows if s.get("availability", {}).get("areas")]
    if not shows:
        return None

    def show_rank(show: dict[str, Any]) -> tuple[int, int]:
        avail = show["availability"].get("available_seats")
        return (0 if (avail or 0) > 0 else 1, show["start_iso"])

    show = sorted(shows, key=show_rank)[0]
    low, high, depth_note = format_depth_guidance(show["format"]["key"])
    areas = show["availability"]["areas"]

    def comfort_rank(area: dict[str, Any]) -> float:
        """Rank areas by published label. Depth is NOT published, so this is a hint."""
        label = (area.get("label") or "").upper()
        if "RECLINER" in label:
            return 0.95
        if any(word in label for word in ("PREMIUM", "LUXE", "PLUSH")):
            return 0.85
        if any(word in label for word in ("EXECUTIVE", "CLUB", "GOLD")):
            return 0.65
        if "BALCONY" in label:
            return 0.55
        if any(word in label for word in ("CLASSIC", "NORMAL", "SILVER", "REGULAR")):
            return 0.45
        return 0.5

    def area_score(area: dict[str, Any]) -> float:
        total = area.get("total_seats") or 0
        available = area.get("available_seats") or 0
        if total and available <= 0:
            return -1.0
        if not total and area.get("status") == "sold_out":
            return -1.0
        ratio = (available / total) if total else 0.5
        return round(0.6 * comfort_rank(area) + 0.4 * min(1.0, ratio * 1.4), 3)

    ranked_areas = sorted(areas, key=area_score, reverse=True)
    bookable_areas = [a for a in ranked_areas if (a.get("available_seats") or 0) > 0]
    sold_out = [a for a in areas if a.get("status") == "sold_out"]

    def describe(area: dict[str, Any]) -> dict[str, Any]:
        total = area.get("total_seats") or 0
        available = area.get("available_seats") or 0
        ratio = round((available / total) * 100) if total else None
        return {
            "area": area.get("label"),
            "price": area.get("price"),
            "available_seats": available,
            "total_seats": total,
            "fill_percent": ratio,
            "status": area.get("status"),
        }

    best = [describe(a) for a in bookable_areas[:2]]
    second = [describe(a) for a in bookable_areas[2:4]]
    avoid = [
        {
            "area": a.get("label"),
            "price": a.get("price"),
            "reason": "reported sold out by the source" if a.get("status") == "sold_out"
            else "no seats currently reported available",
        }
        for a in sold_out
    ]

    if not avoid:
        avoid.append({
            "area": "Extreme front rows and far-left/far-right seats",
            "reason": "neck strain, distorted geometry and off-axis audio regardless of auditorium",
        })

    return {
        "mode": "heuristic",
        "label": "Zone recommendation (heuristic, no seat map published)",
        "theatre_id": theatre_id,
        "show_id": show["id"],
        "show_start": show["start"],
        "show_date": show["date"],
        "screen": show.get("screen"),
        "format": show["format"]["label"],
        "best": best,
        "second_best": second,
        "avoid": avoid,
        "target_zone": {
            "horizontal": "middle 40% of the row, centred on the screen's horizontal midpoint",
            "depth_percent": [round(low * 100), round(high * 100)],
            "depth_note": depth_note,
        },
        "notes": [
            "District publishes auditorium areas and seat counts, not individual seat numbers, "
            "so this is a zone recommendation based on real published data.",
            "Pick the centre of the recommended area a little behind its middle row.",
            "Area names come from the source and do not publish row depth; recliner/premium blocks "
            "are usually towards the rear in Indian multiplexes, but confirm on the booking layout.",
        ],
        "disclaimer": "Heuristic only: no seat numbers are claimed because no public seat map was available.",
    }


def build_recommendation(
    theatre_id: str,
    shows: list[dict[str, Any]],
    layout_dir: Path | None,
    screen: str | None = None,
) -> dict[str, Any] | None:
    """Prefer a real layout when one exists for this theatre/screen."""
    if layout_dir:
        candidates = sorted(layout_dir.glob(f"{theatre_id}*.json"))
        for path in candidates:
            layout = load_layout(path)
            if not layout:
                continue
            if screen and layout.get("screen") and str(layout["screen"]).lower() != screen.lower():
                continue
            chosen = shows[0] if shows else {"format": {"key": "unknown"}}
            rec = recommend_from_layout(layout, chosen.get("format", {}).get("key", "unknown"))
            rec["layout_file"] = str(path.name)
            return rec
    return heuristic_recommendation(shows, theatre_id)
