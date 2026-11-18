"""Monitoring engine: fetch every source, merge, diff, notify, persist."""

from __future__ import annotations

import os
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .config import AppConfig, TheatreConfig, iso_ist, load_config
from .diff import diff_snapshot
from .http import HttpClient
from .models import SourceResult, TheatreObservation, summarise_shows
from .notify import Notifier, prune_notified
from .seats import build_recommendation
from .sources import bookmyshow, district
from .store import Store

ADAPTERS: dict[str, Callable[..., SourceResult]] = {
    "district": district.fetch,
    "bookmyshow": bookmyshow.fetch,
}


def _normalise(text: str) -> str:
    return " ".join(
        "".join(ch.lower() if (ch.isalnum() or ch.isspace()) else " " for ch in text).split()
    )


def verify_venue(config: AppConfig, theatre: Any, venue: dict[str, Any]) -> dict[str, Any]:
    source_name = str(venue.get("name") or "")
    source_id = str(venue.get("id") or "")
    configured = _normalise(theatre.name)
    candidates = [_normalise(a) for a in theatre.aliases] + [configured]
    src = _normalise(source_name)
    matched_alias = next((a for a in candidates if a and a in src), None)
    id_match = bool(theatre.district_id and source_id == theatre.district_id)
    status = "verified" if (id_match and matched_alias) else ("id_matched" if id_match else "unverified")
    return {
        "status": status,
        "source_name": source_name or None,
        "source_id": source_id or None,
        "configured_id": theatre.district_id,
        "matched_alias": matched_alias,
        "note": (
            "Cinema ID and name both confirmed on the platform's public Bengaluru directory."
            if status == "verified" else
            "Cinema ID matched but the public name differs; check the booking link before trusting it."
            if status == "id_matched" else
            "No matching venue was returned by the source this run."
        ),
    }


def _age_minutes(iso_value: str | None) -> int | None:
    if not iso_value:
        return None
    try:
        when = datetime.fromisoformat(iso_value)
    except ValueError:
        return None
    now = datetime.fromisoformat(iso_ist())
    return max(0, int((now - when).total_seconds() // 60))


def _stale_observation(prev_platform: dict[str, Any], theatre_id: str, platform: str, reason: str) -> dict[str, Any]:
    """Reuse the last good snapshot for one blocked platform, clearly marked stale."""
    last_success = prev_platform.get("last_success_at") or prev_platform.get("checked_at")
    age = _age_minutes(last_success)
    return {
        "platform": platform,
        "theatre_id": theatre_id,
        "status": "stale",
        "listed": prev_platform.get("listed"),
        "venue": prev_platform.get("venue") or {"name": (prev_platform.get("venue") or {}).get("name")},
        "shows": prev_platform.get("shows") or [],
        "dates": prev_platform.get("dates") or {},
        "error": reason,
        "checked_at": iso_ist(),
        "notes": [
            f"Showing the last successful snapshot from {last_success or 'unknown time'}"
            + (f" ({age} minutes old)." if age is not None else ".")
        ],
        "stale": True,
        "data_age_minutes": age,
        "last_success_at": last_success,
    }


def _merge_shows(platforms: dict[str, Any]) -> list[dict[str, Any]]:
    """Dedupe the same physical show across platforms, preferring seat-rich data."""
    merged: dict[str, dict[str, Any]] = {}
    for platform, obs in platforms.items():
        for show in obs.get("shows") or []:
            key = "|".join([
                show["date"], show["start"], str(show.get("screen") or ""), show["format"]["key"],
            ])
            existing = merged.get(key)
            if existing is None:
                merged[key] = {**show, "platforms": [platform]}
            else:
                existing["platforms"].append(platform)
                if (
                    existing["availability"].get("source_exposes_seat_count") is not True
                    and show["availability"].get("source_exposes_seat_count") is True
                ):
                    platforms_list = existing["platforms"]
                    merged[key] = {**show, "platforms": platforms_list}
    return sorted(merged.values(), key=lambda s: s["start_iso"])


def build_snapshot(
    movie: Any,
    config: AppConfig,
    source_results: list[SourceResult],
    previous: dict[str, Any],
    started_at: str,
    duration_ms: int,
    run_id: str,
    layout_dir: Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    prev_by_theatre: dict[str, Any] = {}
    for theatre in previous.get("theatres", []) or []:
        prev_by_theatre[theatre.get("id")] = theatre

    theatre_cfgs = list(config.theatres_for(movie))
    known_theatre_ids = {t.id for t in theatre_cfgs}
    for result in source_results:
        for theatre_id, observation in result.observations.items():
            if theatre_id in known_theatre_ids:
                continue
            if not observation.shows:
                continue
            venue = observation.venue or {}
            theatre_cfgs.append(TheatreConfig(
                id=theatre_id,
                name=str(venue.get("name") or f"District cinema {venue.get('id') or ''}").strip(),
                area="Bengaluru (newly discovered)",
                aliases=(),
                notes="Discovered from an explicit eligible source session.",
                district_id=str(venue.get("id") or "") or None,
            ))
            known_theatre_ids.add(theatre_id)

    source_failed = not source_results or any(r.status in {"blocked", "error"} for r in source_results)
    source_incomplete = source_failed or any(r.status == "partial" for r in source_results)

    theatres: list[dict[str, Any]] = []
    theatre_errors: list[dict[str, Any]] = []

    for theatre_cfg in theatre_cfgs:
        try:
            platforms: dict[str, Any] = {}
            prev_t = prev_by_theatre.get(theatre_cfg.id, {}) or {}
            for platform, result in ((r.source, r) for r in source_results):
                obs = result.observations.get(theatre_cfg.id)
                if obs is None:
                    prev_p = (prev_t.get("platforms") or {}).get(platform) or {}
                    if prev_p.get("shows"):
                        platforms[platform] = _stale_observation(
                            prev_p, theatre_cfg.id, platform,
                            f"No observation returned by {platform} this run.",
                        )
                    else:
                        platforms[platform] = {
                            "platform": platform, "theatre_id": theatre_cfg.id,
                            "status": "error", "listed": None, "venue": {}, "shows": [], "dates": {},
                            "error": f"No observation returned by {platform} this run.",
                            "checked_at": iso_ist(), "notes": [],
                        }
                    continue

                payload = obs.to_dict()
                payload["last_success_at"] = (
                    obs.checked_at if obs.status in {"ok", "not_listed"}
                    else ((prev_t.get("platforms") or {}).get(platform) or {}).get("last_success_at")
                )
                if obs.status in {"blocked", "error"}:
                    prev_p = (prev_t.get("platforms") or {}).get(platform) or {}
                    if prev_p.get("shows"):
                        stale = _stale_observation(
                            prev_p, theatre_cfg.id, platform,
                            f"{platform} unavailable this run: {obs.error or obs.status}",
                        )
                        stale["current_error"] = obs.error
                        payload = stale
                platforms[platform] = payload

            merged_shows = _merge_shows(platforms)
            by_date: dict[str, Any] = {}
            for date in movie.target_dates:
                day_shows = [s for s in merged_shows if s["date"] == date]
                summary = summarise_shows(day_shows)
                by_date[date] = {
                    "listed": bool(day_shows),
                    "state": (
                        "incomplete" if source_incomplete else
                        "published" if day_shows else
                        "unpublished"
                    ) if not (source_failed and not day_shows) else "source_failed",
                    "shows": day_shows,
                    **summary,
                    "first_show": day_shows[0]["start"] if day_shows else None,
                    "last_show": day_shows[-1]["start"] if day_shows else None,
                    "booking_links": [
                        {"platform": s["platform"], "url": s.get("booking_url")}
                        for s in day_shows if s.get("booking_url")
                    ][:6],
                }
            other_dates = sorted({s["date"] for s in merged_shows if s["date"] not in movie.target_dates})

            all_shows = [s for s in merged_shows if s["date"] in movie.target_dates]
            best_seats = build_recommendation(
                theatre_cfg.id,
                [s for s in all_shows if s["availability"]["status"] != "sold_out"] or all_shows,
                layout_dir,
            )
            format_keys = sorted({s["format"]["key"] for s in all_shows})
            tour_platforms = {p for s in all_shows for p in s.get("platforms", [])}

            primary_link = next(
                (s.get("booking_url") for s in all_shows if s.get("booking_url")), None
            )
            source_urls = [
                {"platform": p, "url": (o.get("venue") or {}).get("url")}
                for p, o in platforms.items() if (o.get("venue") or {}).get("url")
            ]

            verification = {}
            for platform, obs in platforms.items():
                if platform == "district" and obs.get("venue"):
                    verification[platform] = verify_venue(config, theatre_cfg, obs["venue"])
                elif obs.get("venue"):
                    verification[platform] = {
                        "status": "unverified", "source_name": obs["venue"].get("name"),
                        "note": "No stable venue ID was available from this source.",
                    }

            health = _theatre_health(platforms)

            theatres.append({
                "id": theatre_cfg.id,
                "name": theatre_cfg.name,
                "area": theatre_cfg.area,
                "notes": theatre_cfg.notes,
                "aliases": list(theatre_cfg.aliases),
                "platforms": platforms,
                "dates": by_date,
                "shows": all_shows,
                "formats": [f for f in _format_list(all_shows)],
                "format_keys": format_keys,
                "required_format_keys": list(movie.required_format_keys),
                "source_show_count": sum(int(p.get("raw_show_count") or 0) for p in platforms.values()),
                "listed": bool(all_shows) or any(p.get("listed") for p in platforms.values()),
                "booking": {
                    "url": primary_link,
                    "source_urls": source_urls,
                    "status": summarise_shows(all_shows)["booking_status"] if all_shows else "unknown",
                    "platforms": sorted(tour_platforms),
                },
                "best_seats": best_seats,
                "verification": verification,
                "health": health,
                "other_dates_seen": other_dates,
            })
        except Exception as exc:  # one theatre must never break the rest
            theatre_errors.append({"theatre_id": theatre_cfg.id, "error": f"{type(exc).__name__}: {exc}"})
            theatres.append({
                "id": theatre_cfg.id, "name": theatre_cfg.name, "area": theatre_cfg.area,
                "platforms": {}, "dates": {}, "shows": [], "formats": [], "format_keys": [],
                "listed": False,
                "booking": {"url": None, "source_urls": [], "status": "unknown", "platforms": []},
                "best_seats": None, "verification": {}, "health": {"status": "error", "age_minutes": None},
                "notes": theatre_cfg.notes,
            })

    all_shows = [s for t in theatres for s in t["shows"]]
    totals = {
        "theatres_monitored": len(theatre_cfgs),
        "theatres_with_listings": sum(1 for t in theatres if t["dates"] and any(d["listed"] for d in t["dates"].values())),
        "shows_total": len(all_shows),
        "shows_3d": sum(1 for s in all_shows if s["format"]["is_3d"]),
        "shows_infinity_vision_3d": sum(1 for s in all_shows if s["format"]["key"].startswith("infinity_vision")),
        "shows_imax_3d": sum(1 for s in all_shows if s["format"]["key"].startswith("imax")),
        "shows_4dx": sum(1 for s in all_shows if "4dx" in s["format"]["key"]),
        "shows_4dx_3d": sum(1 for s in all_shows if s["format"]["key"] == "4dx_3d"),
        "bookable_shows": sum(1 for s in all_shows if s["availability"]["status"] in {"bookable", "few_left"}),
        "seats_available_total": sum(
            s["availability"]["available_seats"] or 0 for s in all_shows
        ),
        "dates": {
            d: {
                "state": (
                    "incomplete" if source_failed and sum(1 for s in all_shows if s["date"] == d)
                    else "source_failed" if source_failed
                    else "incomplete" if source_incomplete
                    else "published" if sum(1 for s in all_shows if s["date"] == d)
                    else "unpublished"
                ),
                "shows": sum(1 for s in all_shows if s["date"] == d),
                "theatres": sum(1 for t in theatres if (t["dates"].get(d) or {}).get("listed")),
                "shows_3d": sum(1 for s in all_shows if s["date"] == d and s["format"]["is_3d"]),
                "shows_infinity_vision_3d": sum(
                    1 for s in all_shows if s["date"] == d and s["format"]["key"].startswith("infinity_vision")
                ),
                "shows_4dx_3d": sum(
                    1 for s in all_shows if s["date"] == d and s["format"]["key"] == "4dx_3d"
                ),
            }
            for d in movie.target_dates
        },
        "theatre_errors": theatre_errors,
    }

    previous_sources = {s["source"]: s for s in previous.get("sources", []) or []}
    sources_payload = []
    for result in source_results:
        entry = result.to_dict()
        prev = previous_sources.get(result.source) or {}
        if result.status in {"blocked", "error"}:
            entry["last_success_at"] = prev.get("last_success_at")
        else:
            entry["last_success_at"] = result.checked_at
        sources_payload.append(entry)

    statuses = [r.status for r in source_results]
    # Only full coverage is "ok". A partial/blocked source means the snapshot is
    # incomplete even when another source succeeded, so say so explicitly.
    if statuses and all(s == "ok" for s in statuses):
        run_status = "ok"
    elif any(s in {"ok", "partial"} for s in statuses):
        run_status = "partial"
    else:
        run_status = "degraded"

    checked_at = iso_ist()
    snapshot = {
        "schema_version": 2,
        "run_id": run_id,
        "checked_at": checked_at,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "status": run_status,
        "movie": {
            "id": movie.id,
            "title": movie.title,
            "release_date": movie.release_date,
            "target_dates": list(movie.target_dates),
            "required_format_keys": list(movie.required_format_keys),
            "district_content_id": movie.district_content_id,
            "district_url": next((r.movie.get("url") for r in source_results if r.movie.get("url")), None),
            "poster": next((r.movie.get("poster") for r in source_results if r.movie.get("poster")), None),
            "duration_minutes": next(
                (r.movie.get("duration_minutes") for r in source_results if r.movie.get("duration_minutes")), None
            ),
        },
        "totals": totals,
        "theatres": theatres,
        "sources": sources_payload,
        "excluded_lookalikes": list(config.excluded_lookalikes),
        "events": [],
    }
    if provenance:
        snapshot["provenance"] = provenance
    return snapshot, previous, []


def _format_list(shows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for show in shows:
        fmt = show["format"]
        entry = seen.setdefault(fmt["key"], {
            "key": fmt["key"], "label": fmt["label"], "is_3d": fmt["is_3d"],
            "is_premium": fmt["is_premium"], "count": 0,
        })
        entry["count"] += 1
    return sorted(seen.values(), key=lambda f: f["label"])


def _theatre_health(platforms: dict[str, Any]) -> dict[str, Any]:
    healthy = [o for o in platforms.values() if o.get("status") in {"ok", "not_listed"}]
    stale = [o for o in platforms.values() if o.get("status") == "stale"]
    ages = [o.get("data_age_minutes") for o in stale if o.get("data_age_minutes") is not None]
    if healthy and not stale:
        status = "live"
    elif healthy and stale:
        status = "partial"
    elif stale:
        status = "stale"
    else:
        status = "unavailable"
    return {
        "status": status,
        "age_minutes": max(ages) if ages else 0,
        "platforms_live": [o["platform"] for o in healthy],
        "platforms_stale": [o["platform"] for o in stale],
    }


def _aggregate_sources(movie_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {"error": 4, "blocked": 3, "partial": 2, "ok": 1}
    merged: dict[str, dict[str, Any]] = {}
    messages: dict[str, list[str]] = {}
    for snap in movie_snapshots:
        for source in snap.get("sources", []) or []:
            name = source["source"]
            current = merged.get(name)
            if current is None or rank.get(source.get("status"), 0) > rank.get(current.get("status"), 0):
                merged[name] = dict(source)
            msg = str(source.get("message") or "").strip()
            if msg and msg not in messages.setdefault(name, []):
                messages[name].append(msg)
    for name, entry in merged.items():
        entry["message"] = " | ".join(messages.get(name, []))
    return list(merged.values())


def _aggregate_totals(movie_snapshots: list[dict[str, Any]], theatre_count: int) -> dict[str, Any]:
    numeric = [
        "theatres_with_listings", "shows_total", "shows_3d",
        "shows_infinity_vision_3d", "shows_imax_3d", "shows_4dx", "shows_4dx_3d",
        "bookable_shows", "seats_available_total",
    ]
    totals: dict[str, Any] = {key: 0 for key in numeric}
    totals["theatres_monitored"] = theatre_count
    totals["movies_tracked"] = len(movie_snapshots)
    totals["dates"] = {}
    totals["theatre_errors"] = []
    for snap in movie_snapshots:
        t = snap.get("totals") or {}
        for key in numeric:
            totals[key] += int(t.get(key) or 0)
        for day, summary in (t.get("dates") or {}).items():
            entry = totals["dates"].setdefault(day, {
                "shows": 0, "theatres": 0, "shows_3d": 0,
                "shows_infinity_vision_3d": 0, "shows_4dx_3d": 0,
            })
            for key in ("shows", "theatres", "shows_3d", "shows_infinity_vision_3d"):
                entry[key] += int(summary.get(key) or 0)
            entry["shows_4dx_3d"] += int((summary or {}).get("shows_4dx_3d") or 0)
        totals["theatre_errors"].extend(t.get("theatre_errors") or [])
    return totals


def run_monitor(
    config_path: str | Path | None = None,
    data_dir: str | Path = "data",
    *,
    dry_run: bool = False,
    skip_notifications: bool = False,
    trigger: str = "manual",
    prefetched_results: list[SourceResult] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    store = Store(data_dir)
    # A dry run must not touch the repository: no data dir creation, no cache
    # files. Use a throwaway cache so robots.txt/session discovery still work.
    temp_cache = tempfile.TemporaryDirectory(prefix="doomsday-dry-") if dry_run else None
    cache_dir = Path(temp_cache.name) if temp_cache else store.cache
    if not dry_run:
        store.ensure()
    previous = store.load_latest()
    previous_state = store.load_state()
    started = time.time()
    started_at = iso_ist()
    run_id = datetime.fromisoformat(started_at).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6]

    by_movie: dict[str, list[SourceResult]] = {movie.id: [] for movie in config.movies}
    if prefetched_results is not None:
        # Ingest path: the NAS already fetched District. No network request is
        # made here, so an import can never bypass a source block or duplicate
        # a fetch.
        for result in prefetched_results:
            movie_id = result.movie_id or config.primary_movie.id
            if movie_id not in by_movie:
                raise ValueError(f"source result references unknown movie {movie_id!r}")
            by_movie[movie_id].append(result)
    else:
        with HttpClient(
            user_agent=config.monitoring.user_agent,
            timeout_seconds=config.monitoring.request_timeout_seconds,
            max_retries=config.monitoring.max_retries,
            backoff_seconds=config.monitoring.retry_backoff_seconds,
            cache_dir=cache_dir,
        ) as client:
            for movie in config.movies:
                for name, adapter in ADAPTERS.items():
                    if not config.sources.get(name, {}).get("enabled", False):
                        continue
                    try:
                        if name == "district":
                            result = adapter(config, client, cache_dir, movie=movie)
                        else:
                            result = adapter(config, client, cache_dir)
                        by_movie[movie.id].append(result)
                    except Exception as exc:  # noqa: BLE001 - isolate source failures
                        by_movie[movie.id].append(SourceResult(
                            source=name,
                            status="error",
                            message=f"{type(exc).__name__}: {exc}",
                            movie_id=movie.id,
                            evidence={"traceback_tail": traceback.format_exc(limit=2)},
                            observations={
                                t.id: TheatreObservation(
                                    platform=name, theatre_id=t.id, status="error", listed=None,
                                    error=f"{type(exc).__name__}: {exc}",
                                )
                                for t in config.theatres_for(movie)
                            },
                        ))

    duration_ms = int((time.time() - started) * 1000)
    previous_movies = {
        (snap.get("movie") or {}).get("id"): snap
        for snap in (previous.get("movies") or [])
        if isinstance(snap, dict)
    }
    movie_snapshots: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    movie_states: dict[str, Any] = {}

    for movie in config.movies:
        previous_movie = previous_movies.get(movie.id)
        if previous_movie is None and movie.id == config.primary_movie.id:
            previous_movie = {
                "theatres": previous.get("theatres", []),
                "sources": previous.get("sources", []),
            }
        snapshot, _, _ = build_snapshot(
            movie, config, by_movie.get(movie.id, []), previous_movie or {},
            started_at, duration_ms, run_id,
            layout_dir=store.root / "seatmaps", provenance=provenance,
        )
        prev_movie_state = (previous_state.get("movies") or {}).get(movie.id)
        if prev_movie_state is None and movie.id == config.primary_movie.id and "theatres" in previous_state:
            prev_movie_state = previous_state
        events, movie_state = diff_snapshot(
            prev_movie_state or {}, snapshot["theatres"], config, snapshot["sources"], movie=movie,
        )
        snapshot["events"] = events
        movie_states[movie.id] = movie_state
        movie_snapshots.append(snapshot)
        all_events.extend(events)

    movie_statuses = [snap["status"] for snap in movie_snapshots]
    if movie_statuses and all(s == "ok" for s in movie_statuses):
        run_status = "ok"
    elif any(s in {"ok", "partial"} for s in movie_statuses):
        run_status = "partial"
    else:
        run_status = "degraded"

    totals = _aggregate_totals(movie_snapshots, sum(
        int((snap.get("totals") or {}).get("theatres_monitored") or 0)
        for snap in movie_snapshots
    ))
    sources_payload = _aggregate_sources(movie_snapshots)
    primary = movie_snapshots[0]
    checked_at = iso_ist()
    snapshot = {
        "schema_version": 2,
        "run_id": run_id,
        "checked_at": checked_at,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "status": run_status,
        "movies": movie_snapshots,
        # Compatibility aliases for older pages / API consumers. New code
        # should read the selected entry from ``movies``.
        "movie": primary["movie"],
        "theatres": primary["theatres"],
        "totals": totals,
        "sources": sources_payload,
        "excluded_lookalikes": list(config.excluded_lookalikes),
        "events": all_events,
    }
    if provenance:
        snapshot["provenance"] = provenance

    new_state = {
        "version": 2,
        "updated_at": iso_ist(),
        "movies": movie_states,
        "notified": previous_state.get("notified", {}),
    }
    prune_notified(new_state)

    notifications: dict[str, Any] = {
        "checked_at": iso_ist(), "channels": [], "candidates": 0,
        "sent": [], "skipped": [], "errors": [],
    }
    if not skip_notifications:
        notifier = Notifier(config, dry_run=dry_run)
        notifications = notifier.dispatch(all_events, new_state)
    snapshot["notifications"] = notifications

    now = datetime.fromisoformat(snapshot["checked_at"])
    next_check = now + config.monitoring.interval_delta
    meta = {
        "schema_version": 2,
        "generated_at": snapshot["checked_at"],
        "run_id": run_id,
        "run_status": snapshot["status"],
        "trigger": trigger,
        "movies": [
            {"id": s["movie"]["id"], "title": s["movie"]["title"], "status": s["status"]}
            for s in movie_snapshots
        ],
        "monitoring": {
            "interval_minutes": config.monitoring.interval_minutes,
            "timezone": config.monitoring.timezone,
            "next_check_at": next_check.isoformat(timespec="seconds"),
            "schedule_note": (
                "Hourly collection by the Indian-egress OpenWrt NAS collector; "
                "GitHub Actions validates, ingests and deploys the snapshot."
                if provenance else
                "Manual GitHub Actions run; the hourly NAS collector is the normal data source."
            ),
        },
        "last_success_at": snapshot["checked_at"] if snapshot["status"] in {"ok", "partial"} else previous.get("checked_at"),
        "counts": totals,
        "events_last_run": len(all_events),
        "event_types_last_run": sorted({e["type"] for e in all_events}),
        "sources": {
            s["source"]: {
                "status": s["status"], "message": s["message"],
                "checked_at": s["checked_at"], "last_success_at": s.get("last_success_at"),
            }
            for s in sources_payload
        },
        "notifications": {
            "channels": notifications.get("channels", []),
            "sent": len(notifications.get("sent", [])),
            "errors": notifications.get("errors", []),
        },
        "host": {
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "server_url": os.environ.get("GITHUB_SERVER_URL"),
        },
        "config_digest": config.raw.get("schema_version"),
    }
    if provenance:
        meta["collector"] = provenance

    state = {**new_state, "last_run": {
        "run_id": run_id, "checked_at": snapshot["checked_at"], "status": snapshot["status"],
    }}
    if dry_run:
        if temp_cache:
            temp_cache.cleanup()
        return {
            "run_id": run_id,
            "status": snapshot["status"],
            "snapshot_path": None,
            "dry_run": True,
            "totals": snapshot["totals"],
            "events": all_events,
            "notifications": notifications,
            "sources": {s["source"]: s["status"] for s in sources_payload},
        }
    snapshot_path = store.write_run(
        snapshot=snapshot,
        state=state,
        meta=meta,
        events=all_events,
        sources={"schema_version": 2, "checked_at": snapshot["checked_at"], "sources": {
            s["source"]: s for s in sources_payload
        }},
        retention=(config.retention.hourly_snapshots, config.retention.daily_snapshots),
    )
    if temp_cache:
        temp_cache.cleanup()
    return {
        "run_id": run_id,
        "status": snapshot["status"],
        "snapshot_path": str(snapshot_path),
        "totals": snapshot["totals"],
        "events": all_events,
        "notifications": notifications,
        "sources": {s["source"]: s["status"] for s in sources_payload},
    }
