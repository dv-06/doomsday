"""Configuration loading and validation.

Configuration lives in config/monitor.json (committed to the repo) so that the
GitHub Actions schedule and local runs behave identically, and so the Settings
page can hand you a ready-to-commit JSON blob without needing a writable backend.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class ConfigError(ValueError):
    """Raised when config/monitor.json is invalid."""


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def iso_ist(dt: datetime | None = None) -> str:
    """ISO-8601 timestamp in IST with an explicit offset (never naive)."""
    return (dt or now_ist()).astimezone(IST).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


@dataclass(frozen=True)
class TheatreConfig:
    id: str
    name: str
    area: str
    aliases: tuple[str, ...]
    notes: str = ""
    district_id: str | None = None

    @property
    def display(self) -> str:
        return f"{self.name} ({self.area})"


@dataclass(frozen=True)
class MonitoringConfig:
    interval_minutes: int = 60
    timezone: str = "Asia/Kolkata"
    request_timeout_seconds: float = 25.0
    max_retries: int = 3
    retry_backoff_seconds: float = 2.5
    user_agent: str = "DoomsdayWatch/1.0"

    @property
    def interval_delta(self) -> timedelta:
        return timedelta(minutes=self.interval_minutes)


@dataclass(frozen=True)
class RetentionConfig:
    hourly_snapshots: int = 72
    daily_snapshots: int = 90


@dataclass(frozen=True)
class NotificationConfig:
    raw: dict[str, Any] = field(default_factory=dict)
    notify_on: tuple[str, ...] = ()

    def credentials(self) -> dict[str, str]:
        """Read secrets from the environment only; never from the repo."""
        names: set[str] = set()

        def collect(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key.endswith("_env") and isinstance(value, str):
                        names.add(value)
                    elif key == "secret_env" and isinstance(value, dict):
                        names.update(v for v in value.values() if isinstance(v, str))
                    elif key == "topic_env" and isinstance(value, str):
                        names.add(value)
                    else:
                        collect(value)
            elif isinstance(node, list):
                for item in node:
                    collect(item)

        collect(self.raw)
        return {name: os.environ[name] for name in sorted(names) if os.environ.get(name)}


@dataclass(frozen=True)
class MovieConfig:
    """One tracked film. Theatres are shared; dates and formats are not."""

    id: str
    title: str
    release_date: str
    district_content_id: str
    district_slug: str
    district_city: str
    target_dates: tuple[str, ...]
    required_format_keys: tuple[str, ...] = ()
    notes: str = ""

    @property
    def district_url(self) -> str | None:
        if not self.district_slug:
            return None
        return f"https://www.district.in/movies/{self.district_slug}"


@dataclass(frozen=True)
class AppConfig:
    movies: tuple[MovieConfig, ...]
    monitoring: MonitoringConfig
    retention: RetentionConfig
    notifications: NotificationConfig
    theatres: tuple[TheatreConfig, ...]
    excluded_lookalikes: tuple[dict[str, Any], ...]
    sources: dict[str, Any]
    raw: dict[str, Any]
    bookmyshow_movie_code: str | None = None

    @property
    def primary_movie(self) -> MovieConfig:
        return self.movies[0]

    # Backward-compatible accessors used by older adapters and the Settings page.
    @property
    def title(self) -> str:
        return self.primary_movie.title

    @property
    def release_date(self) -> str:
        return self.primary_movie.release_date

    @property
    def district_content_id(self) -> str:
        return self.primary_movie.district_content_id

    @property
    def district_slug(self) -> str:
        return self.primary_movie.district_slug

    @property
    def district_city(self) -> str:
        return self.primary_movie.district_city

    @property
    def target_dates(self) -> tuple[str, ...]:
        return self.primary_movie.target_dates

    def movie(self, movie_id: str) -> MovieConfig:
        for movie in self.movies:
            if movie.id == movie_id:
                return movie
        raise ConfigError(f"unknown movie id {movie_id!r}")


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{where}: missing required key '{key}'")
    return mapping[key]


def load_config(path: str | Path | None = None) -> AppConfig:
    path = Path(path or os.environ.get("DOOMSDAY_CONFIG") or "config/monitor.json")
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from exc

    movie_entries = raw.get("movies")
    if movie_entries is None:
        # Legacy single-movie config. Keep reading it forever so old inbox
        # payloads and checkouts do not break during a rollout.
        legacy_movie = _require(raw, "movie", "config")
        dates = [str(d) for d in _require(raw, "target_dates", "config")]
        movie_entries = [{
            **legacy_movie,
            "id": "avengers-doomsday",
            "target_dates": dates,
        }]
        legacy = True
    else:
        legacy = False
        if not isinstance(movie_entries, list) or not movie_entries:
            raise ConfigError("config: movies must be a non-empty list")

    movies: list[MovieConfig] = []
    seen_movies: set[str] = set()
    for index, item in enumerate(movie_entries):
        if not isinstance(item, dict):
            raise ConfigError(f"config: movies[{index}] is not an object")
        mid = str(item.get("id") or "").strip()
        if not mid:
            raise ConfigError(f"config: movies[{index}].id is required")
        if mid in seen_movies:
            raise ConfigError(f"config: duplicate movie id {mid!r}")
        seen_movies.add(mid)
        dates = [str(d) for d in item.get("target_dates", [])]
        if not dates:
            raise ConfigError(f"config: movie {mid!r} has no target_dates")
        for d in dates:
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError as exc:
                raise ConfigError(f"config: movie {mid!r} has invalid date {d!r}") from exc
        district = item.get("district", {})
        content_id = str(district.get("content_id") or "")
        if not content_id:
            raise ConfigError(f"config: movie {mid!r} has no district.content_id")
        required = item.get("required_format_keys", [])
        if not isinstance(required, list):
            raise ConfigError(f"config: movie {mid!r} required_format_keys must be a list")
        movies.append(MovieConfig(
            id=mid,
            title=str(item.get("title") or mid).strip(),
            release_date=str(item.get("release_date") or dates[0]),
            district_content_id=content_id,
            district_slug=str(district.get("slug") or ""),
            district_city=str(district.get("city") or "bengaluru"),
            target_dates=tuple(sorted(set(dates))),
            required_format_keys=tuple(str(k) for k in required),
            notes=str(item.get("notes") or ""),
        ))

    seen: set[str] = set()
    theatres: list[TheatreConfig] = []
    for item in _require(raw, "theatres", "config"):
        tid = str(item["id"]).strip()
        if not tid:
            raise ConfigError("config: theatre id must not be empty")
        if tid in seen:
            raise ConfigError(f"config: duplicate theatre id {tid!r}")
        seen.add(tid)
        district_id = (item.get("platform_ids") or {}).get("district")
        theatres.append(
            TheatreConfig(
                id=tid,
                name=str(item["name"]).strip(),
                area=str(item.get("area", "")).strip(),
                aliases=tuple(str(a) for a in item.get("aliases", [])),
                notes=str(item.get("notes", "")),
                district_id=str(district_id) if district_id else None,
            )
        )

    monitoring_raw = raw.get("monitoring", {})
    monitoring = MonitoringConfig(
        interval_minutes=int(monitoring_raw.get("interval_minutes", 60)),
        timezone=str(monitoring_raw.get("timezone", "Asia/Kolkata")),
        request_timeout_seconds=float(monitoring_raw.get("request_timeout_seconds", 25)),
        max_retries=int(monitoring_raw.get("max_retries", 3)),
        retry_backoff_seconds=float(monitoring_raw.get("retry_backoff_seconds", 2.5)),
        user_agent=str(monitoring_raw.get("user_agent", "DoomsdayWatch/1.0")),
    )
    if monitoring.interval_minutes < 5:
        raise ConfigError("config: monitoring.interval_minutes must be >= 5")
    if monitoring.max_retries < 0:
        raise ConfigError("config: monitoring.max_retries must be >= 0")

    retention_raw = raw.get("retention", {})
    retention = RetentionConfig(
        hourly_snapshots=int(retention_raw.get("hourly_snapshots", 72)),
        daily_snapshots=int(retention_raw.get("daily_snapshots", 90)),
    )
    notify_raw = raw.get("notifications", {})
    notifications = NotificationConfig(
        raw=notify_raw,
        notify_on=tuple(notify_raw.get("notify_on", [])),
    )

    bms = (movie_entries[0].get("bookmyshow") or {}) if movie_entries else {}
    return AppConfig(
        movies=tuple(movies),
        bookmyshow_movie_code=(str(bms["movie_code"]) if bms.get("movie_code") else None),
        monitoring=monitoring,
        retention=retention,
        notifications=notifications,
        theatres=tuple(theatres),
        excluded_lookalikes=tuple(raw.get("excluded_lookalikes", [])),
        sources=dict(raw.get("sources", {})),
        raw=raw,
    )
