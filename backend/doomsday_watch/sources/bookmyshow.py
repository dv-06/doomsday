"""BookMyShow adapter.

Verified behaviour (2026-11-17, hourly-friendly single requests):

* ``/explore/movies-bengaluru``  -> 200 (intermittently 403 challenge)
* ``/movies/avengers-doomsday/ET00439706`` -> 200, confirms release date
* every showtimes URL (``/buytickets/...``) -> 403 Cloudflare interstitial

So BookMyShow currently gives us a *listing* signal but not showtimes. The
adapter says exactly that: it confirms the movie page, discovers the event code
from the public movie list, then reports the showtimes page as blocked instead
of faking data or trying to evade the challenge.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import AppConfig
from ..http import HttpClient
from ..models import SourceResult, TheatreObservation, make_show
from .base import SourceError


def _blocked(config: AppConfig, message: str, evidence: dict[str, Any], *, movie: dict[str, Any] | None = None) -> SourceResult:
    return SourceResult(
        source="bookmyshow",
        status="blocked" if not movie else "partial",
        message=message,
        evidence=evidence,
        movie=movie or {},
        observations={
            theatre.id: TheatreObservation(
                platform="bookmyshow",
                theatre_id=theatre.id,
                status="blocked",
                listed=None,
                error=message,
                notes=[
                    "BookMyShow showtimes are behind an anti-bot challenge; no show or seat data "
                    "is invented. The previous snapshot (if any) is preserved."
                ],
            )
            for theatre in config.theatres
        },
    )


def _json_ld(html: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        blocks.extend(payload if isinstance(payload, list) else [payload])
    return blocks


def _discover_from_list(html: str, title: str) -> tuple[str, str] | None:
    """Find (event_code, url) for the movie in BookMyShow's public movie list."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    for block in _json_ld(html):
        if block.get("@type") != "ItemList":
            continue
        for item in block.get("itemListElement", []):
            url = str(item.get("url") or "")
            name = str(item.get("name") or "")
            match = re.search(r"/movies/[a-z0-9-]+/(ET\d+)", url)
            if match and (slug in url or slug in name.lower()):
                return match.group(1), url
    match = re.search(rf"/movies/{re.escape(slug)}/(ET\d+)", html)
    if match:
        return match.group(1), f"https://in.bookmyshow.com/movies/{slug}/{match.group(1)}"
    return None


def _movie_metadata(html: str) -> dict[str, Any]:
    for block in _json_ld(html):
        if block.get("@type") == "Movie":
            return {
                "title": block.get("name"),
                "release_date": block.get("datePublished"),
                "duration_iso": block.get("duration"),
                "description": (block.get("description") or "")[:400],
                "url": block.get("url"),
            }
    return {}


def _screening_events(html: str) -> list[dict[str, Any]]:
    return [b for b in _json_ld(html) if b.get("@type") == "ScreeningEvent"]


def _walk_sessions(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if depth > 8:
        return found
    if isinstance(node, dict):
        if {"ShowTime", "EventCode"} <= set(node) or {"showTime", "eventCode"} <= set(node):
            found.append(node)
        for value in node.values():
            found.extend(_walk_sessions(value, depth + 1))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_sessions(value, depth + 1))
    return found


def _theatre_for_location(config: AppConfig, name: str):
    lowered = name.lower()
    for theatre in config.theatres:
        if any(alias.lower() in lowered for alias in theatre.aliases):
            return theatre
    return None


def fetch(config: AppConfig, client: HttpClient, cache_dir: Any = None) -> SourceResult:
    bms = config.sources.get("bookmyshow", {})
    base = bms.get("base_url", "https://in.bookmyshow.com")
    explore_url = f"{base}{bms.get('probe_path', '/explore/movies-bengaluru')}"

    explore = client.get(explore_url)
    evidence: dict[str, Any] = {**explore.evidence(), "explore_url": explore_url}

    if explore.status == "robots_disallowed":
        return _blocked(config, "BookMyShow robots.txt disallows this path for our client.", evidence)
    if explore.status == "blocked":
        return _blocked(
            config,
            "BookMyShow refused automated access to its movie list with an anti-bot challenge "
            f"(HTTP {explore.http_status}). Not bypassed.",
            evidence,
        )
    if not explore.ok:
        return SourceResult(
            source="bookmyshow",
            status="error",
            message=f"BookMyShow unreachable: {explore.error}",
            evidence=evidence,
            observations={
                theatre.id: TheatreObservation(
                    platform="bookmyshow", theatre_id=theatre.id, status="error", listed=None,
                    error=explore.error,
                )
                for theatre in config.theatres
            },
        )

    discovered = _discover_from_list(explore.text, config.title)
    code = config.bookmyshow_movie_code or (discovered[0] if discovered else None)
    movie_url = discovered[1] if discovered else (
        f"{base}/movies/{config.title.lower().replace(' ', '-')}/{code}" if code else None
    )
    evidence.update({"movie_code": code, "movie_code_source": "config" if config.bookmyshow_movie_code else "auto-discovered"})

    if not code or not movie_url:
        return SourceResult(
            source="bookmyshow",
            status="ok",
            message="Avengers: Doomsday is not listed on BookMyShow's Bengaluru movie list yet.",
            evidence={**evidence, "movie_url": None},
            observations={
                theatre.id: TheatreObservation(
                    platform="bookmyshow", theatre_id=theatre.id, status="not_listed", listed=False,
                    notes=["Movie absent from BookMyShow's public Bengaluru movie list at check time."],
                )
                for theatre in config.theatres
            },
        )

    movie_page = client.get(movie_url)
    evidence["movie_page_http"] = movie_page.http_status
    if movie_page.status == "blocked":
        return _blocked(config, "BookMyShow movie page is behind an anti-bot challenge.", evidence)
    movie_meta = _movie_metadata(movie_page.text) if movie_page.ok else {}
    evidence["movie_url"] = movie_url

    slug = re.search(r"/movies/([a-z0-9-]+)/ET\d+", movie_url)
    slug_text = slug.group(1) if slug else config.title.lower().replace(" ", "-")
    showtimes_url = f"{base}/buytickets/{slug_text}-{config.district_city}/movie-beng-{code}"
    showtimes = client.get(showtimes_url)
    evidence.update({"showtimes_url": showtimes_url, "showtimes_http": showtimes.http_status})

    if showtimes.status == "blocked":
        return _blocked(
            config,
            "BookMyShow movie page is live, but the showtimes/seat pages are behind a Cloudflare "
            f"challenge (HTTP {showtimes.http_status}). No showtimes were read, nothing was bypassed.",
            evidence,
            movie={**movie_meta, "event_code": code, "url": movie_url},
        )
    if not showtimes.ok:
        return SourceResult(
            source="bookmyshow",
            status="error",
            message=f"BookMyShow showtimes page returned HTTP {showtimes.http_status}.",
            evidence=evidence,
            movie={**movie_meta, "event_code": code, "url": movie_url},
            observations={
                theatre.id: TheatreObservation(
                    platform="bookmyshow", theatre_id=theatre.id, status="error", listed=None,
                    error=f"HTTP {showtimes.http_status}",
                )
                for theatre in config.theatres
            },
        )

    events = _screening_events(showtimes.text)
    sessions = _walk_sessions(showtimes.text)
    if not events and not sessions:
        # The showtimes page is client-rendered: it can return 200 with a shell
        # and no session data. We report that instead of scraping a private API.
        message = (
            "BookMyShow showtimes page returned no server-rendered sessions "
            "(client-rendered page). Showtime monitoring is unavailable without a "
            "browser rendering path; nothing was invented and no challenge was bypassed."
        )
        return SourceResult(
            source="bookmyshow",
            status="partial",
            message=message,
            evidence={**evidence, "sessions_in_html": 0},
            movie={**movie_meta, "event_code": code, "url": movie_url},
            observations={
                theatre.id: TheatreObservation(
                    platform="bookmyshow", theatre_id=theatre.id, status="unavailable",
                    listed=None, error=message,
                )
                for theatre in config.theatres
            },
        )

    shows: list[dict[str, Any]] = []
    for event in events:
        start = str(event.get("startDate") or "")
        if len(start) < 16:
            continue
        day, clock = start[:10], start[11:16]
        if day not in config.target_dates:
            continue
        location = event.get("location") or {}
        theatre = _theatre_for_location(config, str(location.get("name") or ""))
        if not theatre:
            continue
        offers = event.get("offers") or {}
        price = offers.get("price") if isinstance(offers, dict) else None
        url = offers.get("url") if isinstance(offers, dict) else None
        shows.append(make_show(
            platform="bookmyshow",
            theatre_id=theatre.id,
            date=day,
            start=clock,
            screen=str(location.get("name") or ""),
            raw_format=str(event.get("videoFormat") or ""),
            total=None,
            available=None,
            raw_status="available" if offers.get("availability") else None,
            booking_url=url,
            languages=[str(event.get("inLanguage") or "")] if event.get("inLanguage") else [],
        ))

    observations: dict[str, TheatreObservation] = {}
    for theatre in config.theatres:
        theatre_shows = [s for s in shows if s["theatre_id"] == theatre.id]
        observations[theatre.id] = TheatreObservation(
            platform="bookmyshow",
            theatre_id=theatre.id,
            status="ok" if theatre_shows else "not_listed",
            listed=bool(theatre_shows),
            shows=theatre_shows,
            notes=["Parsed from BookMyShow public JSON-LD ScreeningEvent data."] if theatre_shows else [],
        )
    return SourceResult(
        source="bookmyshow",
        status="ok",
        message=f"BookMyShow parsed {len(shows)} target-date shows from public JSON-LD.",
        evidence=evidence,
        movie={**movie_meta, "event_code": code, "url": movie_url},
        observations=observations,
        notes=["BookMyShow does not expose seat counts without login; availability is status-only."],
    )

def blocked_result(config: AppConfig, message: str, evidence: dict[str, Any] | None = None) -> SourceResult:
    """A BookMyShow result for ingestion paths that deliberately do not fetch.

    The NAS collector only handles District. BookMyShow remains an explicitly
    blocked source so the UI never implies it was checked successfully.
    """
    return _blocked(config, message, evidence or {})
