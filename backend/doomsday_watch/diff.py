"""Change detection between hourly snapshots.

Rules:
* a show disappearing from a *healthy* source is a removal;
* a source that is blocked/erroring never removes shows (we keep the last good data);
* unavailable seats are reported as unavailable/sold-out exactly as the source said,
  and are never described as "tickets sold".
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from .config import AppConfig, iso_ist

SEVERITY = {
    "theatre_listed": "high",
    "first_show": "high",
    "show_added": "medium",
    "show_removed": "medium",
    "format_added": "high",
    "booking_opened": "high",
    "sold_out": "medium",
    "seats_dropped": "low",
    "price_changed": "low",
    "date_added": "medium",
    "source_blocked": "high",
    "source_recovered": "medium",
}


def _event_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _make_event(
    event_type: str,
    *,
    theatre_id: str,
    theatre_name: str,
    platform: str,
    message: str,
    date: str | None = None,
    start: str | None = None,
    screen: str | None = None,
    data: dict[str, Any] | None = None,
    dedupe: Iterable[Any] = (),
) -> dict[str, Any]:
    return {
        "id": _event_id(event_type, theatre_id, platform, date, start, screen, *dedupe),
        "type": event_type,
        "severity": SEVERITY.get(event_type, "low"),
        "theatre_id": theatre_id,
        "theatre_name": theatre_name,
        "platform": platform,
        "date": date,
        "start": start,
        "screen": screen,
        "message": message,
        "data": data or {},
        "time_basis": "ist",
        "created_at": iso_ist(),
    }


def _format_phrase(show: dict[str, Any]) -> str:
    return show["format"]["label"]


def diff_snapshot(
    previous: dict[str, Any],
    theatres: list[dict[str, Any]],
    config: AppConfig,
    sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    prev_theatres = previous.get("theatres", {}) or {}
    state_theatres: dict[str, Any] = {}
    names = {t.id: t.name for t in config.theatres}

    for theatre in theatres:
        tid = theatre["id"]
        name = names.get(tid, theatre.get("name", tid))
        prev_t = prev_theatres.get(tid, {}) or {}
        state_platforms: dict[str, Any] = {}

        for platform, obs in (theatre.get("platforms") or {}).items():
            prev_p = (prev_t.get("platforms") or {}).get(platform, {}) or {}
            prev_shows: dict[str, Any] = prev_p.get("shows", {}) or {}
            prev_dates = set(prev_p.get("dates") or [])
            prev_available_dates = set(prev_p.get("available_dates") or [])
            source_healthy = obs.get("status") in {"ok", "not_listed"}
            shows = [s for s in (obs.get("shows") or []) if isinstance(s, dict)]

            current_shows: dict[str, Any] = {}
            matched_prev_keys: set[str] = set()
            prev_by_source = {
                str(prev.get("source_show_id")): (key, prev)
                for key, prev in prev_shows.items()
                if isinstance(prev, dict) and prev.get("source_show_id")
            }
            first_listing = not prev_p.get("listed") and obs.get("listed") and source_healthy
            for show in shows:
                show_key = show["id"]
                prev_show = prev_shows.get(show_key)
                prev_key = show_key if prev_show else None
                if not prev_show and show.get("source_show_id"):
                    match = prev_by_source.get(str(show["source_show_id"]))
                    if match:
                        prev_key, prev_show = match

                # One-time migration for snapshots written before District's
                # raw UTC clock was converted to IST. The stable source id is
                # preferred; the raw clock fallback keeps seat comparisons and
                # first-seen timestamps continuous across the correction.
                if not prev_show and show.get("source_time"):
                    raw_time = str(show["source_time"])
                    for key, candidate in prev_shows.items():
                        if key in matched_prev_keys or not isinstance(candidate, dict):
                            continue
                        if (
                            candidate.get("start") == raw_time[11:16]
                            and candidate.get("date") == raw_time[:10]
                            and candidate.get("screen") == show.get("screen")
                            and candidate.get("format_key") == show["format"]["key"]
                        ):
                            prev_key, prev_show = key, candidate
                            break
                if prev_key:
                    matched_prev_keys.add(prev_key)

                current_shows[show_key] = {
                    "first_seen_at": (prev_show or {}).get("first_seen_at") or iso_ist(),
                    "last_seen_at": iso_ist(),
                    "date": show["date"],
                    "start": show["start"],
                    "start_iso": show.get("start_iso"),
                    "source_show_id": show.get("source_show_id"),
                    "source_time": show.get("source_time"),
                    "screen": show.get("screen"),
                    "format_key": show["format"]["key"],
                    "format_label": show["format"]["label"],
                    "status": show["availability"]["status"],
                    "available_seats": show["availability"]["available_seats"],
                    "total_seats": show["availability"]["total_seats"],
                    "price_min": show["price"]["min"],
                    "price_max": show["price"]["max"],
                }
                if not prev_show:
                    if first_listing:
                        first_listing = False
                        events.append(_make_event(
                            "theatre_listed", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=(
                                f"{name}: first show released on {platform} — "
                                f"{show['start']} on {show['date']} ({_format_phrase(show)})"
                            ),
                            data={"format": show["format"]["label"], "booking_url": show.get("booking_url")},
                        ))
                    elif prev_p.get("listed") and show["date"] not in prev_dates:
                        events.append(_make_event(
                            "first_show", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=(
                                f"{name}: first show on {show['date']} — "
                                f"{show['start']} ({_format_phrase(show)}) via {platform}"
                            ),
                            data={"format": show["format"]["label"], "booking_url": show.get("booking_url")},
                        ))
                    else:
                        events.append(_make_event(
                            "show_added", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=f"{name}: new show {show['start']} on {show['date']} ({_format_phrase(show)})",
                            data={"format": show["format"]["label"], "booking_url": show.get("booking_url")},
                        ))
                else:
                    prev_status = prev_show.get("status")
                    new_status = show["availability"]["status"]
                    if prev_status in {"sold_out", "unknown", None} and new_status in {"bookable", "few_left", "filling_fast"}:
                        events.append(_make_event(
                            "booking_opened", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=f"{name}: booking open for {show['start']} on {show['date']} ({_format_phrase(show)})",
                            data={"booking_url": show.get("booking_url")},
                        ))
                    elif prev_status in {"bookable", "few_left", "filling_fast"} and new_status == "sold_out":
                        events.append(_make_event(
                            "sold_out", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=f"{name}: source now reports {show['start']} on {show['date']} as sold out/unavailable",
                        ))
                    prev_avail = prev_show.get("available_seats")
                    new_avail = show["availability"]["available_seats"]
                    if isinstance(prev_avail, int) and isinstance(new_avail, int) and new_avail < prev_avail:
                        events.append(_make_event(
                            "seats_dropped", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=(
                                f"{name}: available seats for {show['start']} on {show['date']} "
                                f"fell from {prev_avail} to {new_avail} (availability, not confirmed sales)"
                            ),
                            data={"before": prev_avail, "after": new_avail},
                            dedupe=(prev_avail, new_avail),
                        ))
                    prev_price = prev_show.get("price_min")
                    new_price = show["price"]["min"]
                    if isinstance(prev_price, (int, float)) and isinstance(new_price, (int, float)) and prev_price != new_price:
                        events.append(_make_event(
                            "price_changed", theatre_id=tid, theatre_name=name, platform=platform,
                            date=show["date"], start=show["start"], screen=show.get("screen"),
                            message=f"{name}: {show['start']} on {show['date']} price changed ₹{prev_price} → ₹{new_price}",
                            data={"before": prev_price, "after": new_price},
                            dedupe=(prev_price, new_price),
                        ))

            prev_formats = {
                s.get("format_key") for s in prev_shows.values() if isinstance(s, dict)
            }
            for show in shows:
                key = show["format"]["key"]
                if key not in prev_formats and key != "unknown":
                    label = show["format"]["label"]
                    events.append(_make_event(
                        "format_added", theatre_id=tid, theatre_name=name, platform=platform,
                        date=show["date"], start=show["start"], screen=show.get("screen"),
                        message=f"{name}: {label} now available ({show['date']} {show['start']})",
                        data={"format_key": key, "format": label},
                        dedupe=(key,),
                    ))
                    prev_formats.add(key)

            if source_healthy:
                for show_key, prev_show in prev_shows.items():
                    if show_key in current_shows or show_key in matched_prev_keys or not isinstance(prev_show, dict):
                        continue
                    events.append(_make_event(
                        "show_removed", theatre_id=tid, theatre_name=name, platform=platform,
                        date=prev_show.get("date"), start=prev_show.get("start"),
                        screen=prev_show.get("screen"),
                        message=(
                            f"{name}: show {prev_show.get('start')} on {prev_show.get('date')} "
                            f"is no longer listed on {platform}"
                        ),
                    ))

            observed_dates = sorted({
                *[str(d) for d in (obs.get("available_dates") or [])],
                *[d for d in (obs.get("dates") or {}).keys()],
            })
            for new_date in sorted(set(observed_dates) - prev_available_dates):
                if prev_available_dates and new_date not in config.target_dates:
                    events.append(_make_event(
                        "date_added", theatre_id=tid, theatre_name=name, platform=platform,
                        date=new_date,
                        message=f"{name}: {platform} now lists sessions for {new_date}",
                    ))

            state_platforms[platform] = {
                "listed": obs.get("listed"),
                "available_dates": observed_dates,
                "status": obs.get("status"),
                "venue_name": (obs.get("venue") or {}).get("name"),
                "venue_id": (obs.get("venue") or {}).get("id"),
                "last_success_at": iso_ist() if source_healthy else prev_p.get("last_success_at"),
                "first_seen_at": (prev_p.get("first_seen_at") or (iso_ist() if obs.get("listed") else None)),
                "shows": current_shows,
                "dates": sorted({s["date"] for s in shows}),
            }

        state_theatres[tid] = {
            "id": tid,
            "name": name,
            "first_seen_at": (prev_t.get("first_seen_at") or (iso_ist() if any(
                (p.get("listed") for p in state_platforms.values()) if state_platforms else []
            ) else None)),
            "platforms": state_platforms,
        }

    prev_sources = previous.get("sources", {}) or {}
    for source in sources:
        name = source["source"]
        prev_status = (prev_sources.get(name) or {}).get("status")
        if source["status"] == "blocked" and prev_status != "blocked":
            events.append(_make_event(
                "source_blocked", theatre_id="-", theatre_name=name.title(), platform=name,
                message=f"{name}: automated access blocked — {source.get('message', '')}",
            ))
        elif source["status"] in {"ok", "partial"} and prev_status == "blocked":
            events.append(_make_event(
                "source_recovered", theatre_id="-", theatre_name=name.title(), platform=name,
                message=f"{name}: access recovered, monitoring resumed",
            ))

    # Keep notified/alert bookkeeping that other modules own.
    new_state = {
        "version": 1,
        "updated_at": iso_ist(),
        "theatres": state_theatres,
        "sources": {
            s["source"]: {"status": s["status"], "checked_at": s.get("checked_at")}
            for s in sources
        },
        "notified": previous.get("notified", {}),
        "extra_dates": sorted({
            d for t in theatres for p in (t.get("platforms") or {}).values()
            for d in (p.get("dates") or [])
        }),
    }
    return events, new_state
