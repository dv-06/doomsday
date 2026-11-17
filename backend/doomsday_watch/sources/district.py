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
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode

from ..config import AppConfig, TheatreConfig, iso_ist
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


def discover_movie_url(client: HttpClient, config: AppConfig) -> str | None:
    """Find the Bengaluru movie page slug when the configured one is stale."""
    base = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    registry_path = config.sources.get("district", {}).get("cinema_registry_path", "/movies/cinemas-in-bengaluru")
    result = client.get(f"{base}{registry_path}")
    if not result.ok:
        return None
    for href in sorted(set(re.findall(r'href="(?:https?://www\.district\.in)?(/movies/[a-z0-9-]*doomsday[a-z0-9-]*)"', result.text))):
        if "movie-tickets" in href:
            return f"{base}{href}"
    return None


def _movie_page_url(config: AppConfig, override: str | None = None) -> str:
    base = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    if override:
        return override
    if config.district_slug:
        return f"{base}/movies/{config.district_slug}"
    return f"{base}/movies/avengers-doomsday-movie-tickets-in-{config.district_city}"


def _parse_date(value: str) -> str | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _valid_session(session: dict[str, Any]) -> bool:
    show_time = session.get("showTime")
    return isinstance(show_time, str) and len(show_time) >= 16 and "T" in show_time


def fetch(config: AppConfig, client: HttpClient, cache_dir: Path | None = None) -> SourceResult:
    base_url = config.sources.get("district", {}).get("base_url", "https://www.district.in")
    url = _movie_page_url(config)
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
            discovered = discover_movie_url(client, config)
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
    content_id = str(page_props.get("data", {}).get("contentId") or config.district_content_id)
    movie = _movie_meta(state, content_id)
    if not movie.get("title"):
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

        for session in group.get("sessions") or []:
            if not _valid_session(session):
                continue
            day = _parse_date(session["showTime"])
            if not day:
                continue
            session_dates.add(day)
            if day not in config.target_dates:
                continue
            start = session["showTime"][11:16]
            areas = _session_areas(session)
            shows.append(make_show(
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
                languages=[str(movie.get("primary_language") or "")] if movie.get("primary_language") else [],
                tags=[str(t) for t in (session.get("tags") or [])],
            ))

        observed_dates.update(session_dates)
        observations[theatre.id] = TheatreObservation(
            platform="district",
            theatre_id=theatre.id,
            status="ok",
            listed=bool(session_dates),
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
            notes=[] if shows else [
                "Cinema is listed for this movie, but has no sessions on the target dates yet."
            ],
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
            **movie,
            "url": result.url,
            "show_dates": sorted(all_dates),
        },
        observations=observations,
        notes=[
            "Area-wise seat counts are published by District; individual seat numbers are not, "
            "so seat suggestions are marked as heuristics unless a public layout is supplied.",
        ],
    )
