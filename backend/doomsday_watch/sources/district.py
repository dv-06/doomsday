"""District (district.in, by Zomato) adapter.

District server-renders its Bengaluru movie page with a ``__NEXT_DATA__`` blob
that already contains the cinema list, per-session screen format, screen name,
area-wise seat counts, prices and a booking deep link. We parse that public page
once per run (single request for the whole city, not one request per theatre).

This module never calls an undocumented private API and never renders around a
challenge page.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode

from ..config import IST, AppConfig, MovieConfig, TheatreConfig, iso_ist
from ..http import FetchResult, HttpClient
from ..models import SourceResult, TheatreObservation, make_show
from .base import SourceError, SourceUnavailable

CINEMA_URL_RE = re.compile(r'href="(?:https?://www\.district\.in)?(/movies/[a-z0-9-]+?(?:-c/|-CD)(\d+))"')


def _next_data(html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        raise SourceError("District page has no __NEXT_DATA__ payload (layout may have changed)")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceError(f"District __NEXT_DATA__ is not valid JSON: {exc}") from exc


def _find_session_groups(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Find the cinema/session groups regardless of where District nests them."""
    found: list[dict[str, Any]] = []
    if depth > 8:
        return found
    if isinstance(node, dict):
        groups = node.get("arrangedSessions")
        if isinstance(groups, list) and groups:
            found.extend(g for g in groups if isinstance(g, dict))
        for value in node.values():
            found.extend(_find_session_groups(value, depth + 1))
    elif isinstance(node, list):
        for value in node:
            found.extend(_find_session_groups(value, depth + 1))
    return found


def _movie_meta(state: dict[str, Any], content_id: str) -> dict[str, Any]:
    movie_data = (state.get("mdpV2") or {}).get("movieData") or {}
    entry = movie_data.get(content_id) or {}
    movie = entry.get("movie") or {}
    if not movie and isinstance(movie_data, dict):
        for candidate in movie_data.values():
            if isinstance(candidate, dict) and candidate.get("movie"):
                movie = candidate["movie"]
                break
    return {
        "content_id": str(movie.get("content_id") or content_id),
        "title": movie.get("name"),
        "release_date": movie.get("release_date"),
        "duration_minutes": movie.get("duration"),
        "censor": movie.get("censor"),
        "languages": movie.get("languages") or [],
        "poster": movie.get("poster") or movie.get("horizontal_poster"),
    }


def _session_areas(session: dict[str, Any]) -> list[dict[str, Any]]:
    areas = session.get("areas")
    return [a for a in areas if isinstance(a, dict)] if isinstance(areas, list) else []


def _booking_url(base_url: str, session: dict[str, Any], content_id: str) -> str | None:
    mcd = session.get("mcd")
    enc = session.get("encSessionId")
    if not mcd or not enc:
        return None
    query = urlencode({
        "encsessionid": enc,
        "freeseating": "false",
        "fromsessions": "true",
        "type": "MOVIES",
        "contentid": content_id,
    })
    return f"{base_url}/movies/seat-layout/{quote(str(mcd))}?{query}"


def _cinema_in_group(group: dict[str, Any], theatre: TheatreConfig) -> bool:
    data = group.get("data") or {}
    ids = {
        str(data.get("id") or ""),
        str(group.get("entityCode") or ""),
        str(group.get("entityDataCode") or ""),
    }
    return bool(theatre.district_id) and theatre.district_id in ids


def _registry_cache_path(cache_dir: Path | None) -> Path | None:
    return (cache_dir / "district_registry.json") if cache_dir else None


def load_registry(cache_dir: Path | None) -> tuple[dict[str, Any], float]:
    path = _registry_cache_path(cache_dir)
    if not path or not path.exists():
        return {}, 0.0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("cinemas", {}), float(payload.get("fetched_at", 0))
    except (OSError, ValueError):
        return {}, 0.0


def save_registry(cache_dir: Path | None, cinemas: dict[str, Any]) -> None:
    path = _registry_cache_path(cache_dir)
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": datetime.now().timestamp(), "cinemas": cinemas}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def fetch_registry(client: HttpClient, base_url: str, path: str) -> dict[str, Any]:
    """Public cinema directory page -> {district_id: {name, url, area}}."""
    result = client.get(f"{base_url}{path}")
    if not result.ok:
        return {}
    html = result.text
    cinemas: dict[str, Any] = {}
    for match in re.finditer(r'href="(?:https?://www\.district\.in)?(/movies/[a-z0-9-]+?(?:-c/|-CD)(\d+))"', html):
        url, cid = match.group(1), match.group(2)
        window = html[match.start(): match.start() + 4000]
        name_match = re.search(r'class="[^"]*dds-text-lg[^"]*"[^>]*>([^<]{3,120})</span>', window)
        address_match = re.search(r'class="[^"]*dds-text-quaternary[^"]*"[^>]*>([^<]{3,160})</span>', window)
        cinemas[cid] = {
            "name": (name_match.group(1).strip() if name_match else ""),
            "url": f"https://www.district.in{url}",
            "amenities": (address_match.group(1).strip() if address_match else ""),
        }
    return cinemas


def discover_movie_url(client: HttpClient, config: AppConfig, movie: MovieConfig) -> str | None:
    """Find the Bengaluru movie page slug when the configured one is stale."""
    base = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    registry_path = config.sources.get("district", {}).get("cinema_registry_path", "/movies/cinemas-in-bengaluru")
    result = client.get(f"{base}{registry_path}")
    if not result.ok:
        return None
    token = re.sub(r"[^a-z0-9]+", "-", movie.title.lower()).strip("-")
    pattern = re.compile(r'href="(?:https?://www\.district\.in)?(/movies/[a-z0-9-]*' + re.escape(token) + r'[a-z0-9-]*)"')
    for href in sorted(set(pattern.findall(result.text))):
        if "movie-tickets" in href:
            return f"{base}{href}"
    return None


def _movie_page_url(movie: MovieConfig, config: AppConfig, override: str | None = None) -> str:
    base = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    if override:
        return override
    if movie.district_slug:
        return f"{base}/movies/{movie.district_slug}"
    slug = re.sub(r"[^a-z0-9]+", "-", movie.title.lower()).strip("-")
    return f"{base}/movies/{slug}-movie-tickets-in-{movie.district_city}"


def _parse_date(value: str) -> str | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _valid_session(session: dict[str, Any]) -> bool:
    show_time = session.get("showTime")
    return isinstance(show_time, str) and len(show_time) >= 16 and "T" in show_time


def display_datetime(value: str) -> datetime:
    """District sends naive UTC clocks (``06:15`` for a 11:45 IST show).

    Its own time-of-day tags confirm the semantics: a 06:15 raw session is
    tagged ``8_am_to_12_pm``. Convert exactly once here; explicit offsets are
    honoured rather than shifted twice. The raw string is retained separately.
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def _observations_from_groups(
    movie_cfg: MovieConfig,
    config: AppConfig,
    groups: list[dict[str, Any]],
    movie: dict[str, Any],
    content_id: str,
    base_url: str,
    registry: dict[str, Any],
) -> tuple[dict[str, TheatreObservation], set[str]]:
    """Map District cinema/session groups onto the configured theatres.

    Shared by the live HTTP adapter and the NAS inbox importer so both paths
    cannot drift apart. Groups may carry an optional ``available_dates`` list
    (the NAS collector filters target-date sessions but still reports the dates
    District listed), which keeps ``listed`` accurate without inventing shows.
    """
    observations: dict[str, TheatreObservation] = {}
    observed_dates: set[str] = set()

    for theatre in config.theatres:
        group = next((g for g in groups if _cinema_in_group(g, theatre)), None)
        if group is None:
            registry_entry = registry.get(theatre.district_id or "", {})
            observations[theatre.id] = TheatreObservation(
                platform="district",
                theatre_id=theatre.id,
                status="not_listed",
                listed=False,
                venue={
                    "id": theatre.district_id,
                    "name": registry_entry.get("name") or theatre.name,
                    "url": registry_entry.get("url"),
                    "verified_name": bool(registry_entry.get("name")),
                },
                notes=[
                    "The cinema exists on District's Bengaluru directory but is not part of this movie's session list yet."
                    if registry_entry else
                    "Cinema not present in District's session list for this movie."
                ],
            )
            continue

        data_blob = group.get("data") or {}
        entity_url = group.get("entityUrl")
        venue_name = data_blob.get("name") or group.get("entityName") or theatre.name
        registry_entry = registry.get(theatre.district_id or "", {})
        shows: list[dict[str, Any]] = []
        session_dates: set[str] = set()
        raw_show_count = 0

        for session in group.get("sessions") or []:
            if not _valid_session(session):
                continue
            raw_time = str(session["showTime"])
            try:
                local = display_datetime(raw_time)
            except ValueError:
                continue
            day = local.strftime("%Y-%m-%d")
            start = local.strftime("%H:%M")
            raw_show_count += 1
            session_dates.add(day)
            if day not in movie_cfg.target_dates:
                continue
            areas = _session_areas(session)
            show = make_show(
                platform="district",
                theatre_id=theatre.id,
                date=day,
                start=start,
                screen=str(session.get("audi") or ""),
                raw_format=str(session.get("scrnFmt") or ""),
                areas=areas,
                total=session.get("total"),
                available=session.get("avail"),
                raw_status=session.get("seatStatus"),
                booking_url=_booking_url(base_url, session, content_id),
                source_show_id=str(session.get("sid") or ""),
                source_time=raw_time,
                languages=[str(movie.get("primary_language") or "")] if movie.get("primary_language") else [],
                tags=[str(t) for t in (session.get("tags") or [])],
            )
            if movie_cfg.required_format_keys and show["format"]["key"] not in movie_cfg.required_format_keys:
                continue
            shows.append(show)

        observed_dates.update(session_dates)
        observations[theatre.id] = TheatreObservation(
            platform="district",
            theatre_id=theatre.id,
            status="ok",
            listed=bool(shows),
            venue={
                "id": str(data_blob.get("id") or theatre.district_id),
                "name": venue_name,
                "url": registry_entry.get("url") or (
                    f"{base_url}/movies{entity_url}" if entity_url else None
                ),
                "verified_name": True,
                "address": data_blob.get("address"),
                "distance_km": round(float(data_blob["distanceFromUser"]), 1)
                if isinstance(data_blob.get("distanceFromUser"), (int, float)) else None,
            },
            shows=shows,
            available_dates=sorted(session_dates),
            raw_show_count=raw_show_count,
            required_format_keys=list(movie_cfg.required_format_keys),
            notes=(
                [] if shows else
                [
                    "Cinema is listed for this movie, but the source has no matching "
                    + (", ".join(movie_cfg.required_format_keys) or "target-date")
                    + " sessions yet."
                ] if raw_show_count else [
                    "Cinema is listed for this movie, but has no sessions on the target dates yet."
                ]
            ),
        )

    return observations, observed_dates


def fetch(
    config: AppConfig,
    client: HttpClient,
    cache_dir: Path | None = None,
    *,
    movie: MovieConfig | None = None,
) -> SourceResult:
    movie = movie or config.primary_movie
    base_url = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    url = _movie_page_url(movie, config)
    result = client.get(url)

    if result.status == "robots_disallowed":
        return SourceResult(
            source="district", status="blocked",
            message="District robots.txt disallows this path for our client; monitoring skipped.",
            evidence=result.evidence(),
        )
    if result.status == "blocked":
        return SourceResult(
            source="district", status="blocked",
            message=result.blocked_reason or "District refused automated access.",
            evidence=result.evidence(),
        )
    if not result.ok:
        if result.http_status in (404, 410):
            discovered = discover_movie_url(client, config, movie)
            if discovered:
                url = discovered
                result = client.get(url)
        if not result.ok:
            raise SourceUnavailable(
                f"District movie page unavailable ({result.error or result.status}) at {url}"
            )

    data = _next_data(result.text)
    page_props = ((data.get("props") or {}).get("pageProps") or {})
    state = page_props.get("initialState") or {}
    content_id = str(page_props.get("data", {}).get("contentId") or movie.district_content_id)
    movie_meta = _movie_meta(state, content_id)
    if not movie_meta.get("title"):
        raise SourceError("District page parsed but no movie metadata was found")

    groups = _find_session_groups(state)
    if not groups:
        groups = _find_session_groups(page_props)

    # Public cinema directory: used for name verification and to spot cinemas
    # that exist but have no sessions yet.
    registry, fetched_at = load_registry(cache_dir)
    ttl = float(config.sources.get("district", {}).get("registry_cache_hours", 24)) * 3600
    if not registry or datetime.now().timestamp() - fetched_at > ttl:
        fresh = fetch_registry(
            client, base_url,
            config.sources.get("district", {}).get("cinema_registry_path", "/movies/cinemas-in-bengaluru"),
        )
        if fresh:
            registry = fresh
            save_registry(cache_dir, fresh)

    observations, observed_dates = _observations_from_groups(
        movie, config, groups, movie_meta, content_id, base_url, registry,
    )
    all_dates = set(observed_dates)
    message = (
        f"{len(groups)} Bengaluru cinemas listed for this movie; "
        f"target-date shows found at {sum(1 for o in observations.values() if o.shows)} of "
        f"{len(config.theatres)} monitored theatres."
    )
    return SourceResult(
        source="district",
        status="ok",
        message=message,
        evidence={
            **result.evidence(),
            "movie_url": result.url,
            "session_groups": len(groups),
            "registry_size": len(registry),
            "dates_with_sessions": sorted(all_dates),
        },
        movie={
            **movie_meta,
            "url": result.url,
            "show_dates": sorted(all_dates),
        },
        movie_id=movie.id,
        observations=observations,
        notes=[
            "Area-wise seat counts are published by District; individual seat numbers are not, "
            "so seat suggestions are marked as heuristics unless a public layout is supplied.",
        ],
    )


def result_from_payload(
    config: AppConfig,
    payload: dict[str, Any],
    *,
    movie: MovieConfig | None = None,
    source_url: str | None = None,
) -> SourceResult:
    """Build a District result from the NAS collector's compact inbox payload.

    This path performs no network access. The payload is validated strictly
    before any snapshot is written: a malformed or incomplete message must
    never replace the last good snapshot.
    """
    movie_cfg = movie or config.primary_movie
    if not isinstance(payload, dict):
        raise SourceError("District inbox payload is not a JSON object")
    if str(payload.get("source") or "") != "district":
        raise SourceError("District inbox payload has an unexpected source")
    content_id = str(payload.get("content_id") or "")
    if not content_id:
        raise SourceError("District inbox payload is missing content_id")
    if movie_cfg.district_content_id and content_id != movie_cfg.district_content_id:
        raise SourceError(
            f"District inbox content_id {content_id!r} does not match configured "
            f"{movie_cfg.district_content_id!r} for {movie_cfg.id}"
        )

    movie_meta = payload.get("movie")
    if not isinstance(movie_meta, dict) or not movie_meta.get("title"):
        raise SourceError("District inbox payload has no movie metadata")
    if movie_cfg.title and str(movie_meta["title"]).strip() != movie_cfg.title:
        raise SourceError(
            f"District inbox movie title {movie_meta['title']!r} does not match configured {movie_cfg.title!r}"
        )

    collected_at = payload.get("collected_at")
    if not isinstance(collected_at, str):
        raise SourceError("District inbox payload is missing collected_at")
    try:
        datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceError(f"District inbox collected_at is invalid: {exc}") from exc

    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise SourceError("District inbox payload has no cinema groups list")
    groups = [g for g in groups if isinstance(g, dict)]

    valid_ids = {t.district_id for t in config.theatres if t.district_id}
    seen_ids: set[str] = set()
    for group in groups:
        data_blob = group.get("data") or {}
        group_id = str(data_blob.get("id") or "")
        if group_id in seen_ids:
            raise SourceError(f"District inbox payload repeats cinema {group_id!r}")
        seen_ids.add(group_id)
        sessions = group.get("sessions") or []
        if not isinstance(sessions, list):
            raise SourceError(f"District inbox cinema {group_id!r} has non-list sessions")
        for session in sessions:
            if not isinstance(session, dict) or not _valid_session(session):
                raise SourceError(f"District inbox cinema {group_id!r} has an invalid session")
            try:
                local = display_datetime(str(session["showTime"]))
            except ValueError as exc:
                raise SourceError(
                    f"District inbox cinema {group_id!r} has an invalid showTime"
                ) from exc
            day = local.strftime("%Y-%m-%d")
            if day not in movie_cfg.target_dates:
                # The collector may include adjacent UTC dates so IST midnight
                # sessions are not lost. Non-target local dates are filtered.
                continue
        for raw_date in group.get("available_dates") or []:
            if not _parse_date(str(raw_date)):
                raise SourceError(f"District inbox cinema {group_id!r} has an invalid available_date")

    # Unknown cinemas are not mapped into configured theatres, but flag an
    # entirely mismatched payload instead of silently reporting everything absent.
    matched = {
        str((g.get("data") or {}).get("id") or "")
        for g in groups
        if str((g.get("data") or {}).get("id") or "") in valid_ids
    }
    if groups and valid_ids and not matched:
        raise SourceError("District inbox payload contains none of the configured cinema IDs")

    base_url = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    observations, observed_dates = _observations_from_groups(
        movie_cfg, config, groups, movie_meta, content_id, base_url, {},
    )
    collector = payload.get("collector") if isinstance(payload.get("collector"), dict) else {}
    movie_url = source_url or payload.get("movie_url") or (
        f"{base_url}/movies/{movie_cfg.district_slug}" if movie_cfg.district_slug else None
    )
    return SourceResult(
        source="district",
        status="ok",
        message=(
            f"{len(groups)} cinema group(s) supplied by the NAS collector; target-date shows "
            f"found at {sum(1 for o in observations.values() if o.shows)} of "
            f"{len(config.theatres)} monitored theatres."
        ),
        checked_at=collected_at,
        evidence={
            "transport": "nas_inbox",
            "movie_url": movie_url,
            "session_groups": len(groups),
            "matches_configured_cinemas": len(matched),
            "dates_with_sessions": sorted(observed_dates),
            "collector": collector,
        },
        movie={
            **movie_meta,
            "url": movie_url,
            "show_dates": sorted(observed_dates),
        },
        movie_id=movie_cfg.id,
        observations=observations,
        notes=[
            "Collected by the Indian-egress NAS collector and ingested without a network fetch.",
            "Area-wise seat counts are published by District; individual seat numbers are not "
            "invented. Missing data stays missing.",
        ],
    )
