"""Command line entry points.

    python -m doomsday_watch run            # one monitoring pass (used by Actions)
    python -m doomsday_watch run --dry-run  # fetch + diff only; writes nothing
    python -m doomsday_watch probe          # source accessibility report only
    python -m doomsday_watch notify-test    # send a test alert to configured channels
    python -m doomsday_watch validate       # validate config + data files
    python -m doomsday_watch serve          # local FastAPI backend
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from .config import ConfigError, iso_ist, load_config, now_ist, parse_iso
from .http import HttpClient
from .models import SourceResult
from .monitor import ADAPTERS, run_monitor
from .notify import Notifier
from .sources import district
from .store import Store

# Bump when the meaning/shape of a normally-identical inbox payload changes.
# Snapshot provenance records it so a one-time re-ingest can repair old data
# without weakening duplicate protection for every future run.
PAYLOAD_NORMALIZER_VERSION = 4


def _summarise(result: dict) -> str:
    totals = result["totals"]
    return (
        f"status={result['status']} movies={totals.get('movies_tracked', 1)} shows={totals['shows_total']} "
        f"3D={totals['shows_3d']} InfinityVision3D={totals['shows_infinity_vision_3d']} "
        f"theatres_with_listings={totals['theatres_with_listings']}/{totals['theatres_monitored']} "
        f"events={len(result['events'])} sources={result['sources']}"
    )


def cmd_run(args: argparse.Namespace) -> int:
    result = run_monitor(
        args.config,
        args.data,
        dry_run=args.dry_run,
        skip_notifications=args.skip_notifications,
        trigger=args.trigger,
    )
    print(_summarise(result))
    for event in result["events"]:
        print(f"  [{event['severity']}] {event['type']}: {event['message']}")
    if args.github_summary:
        _write_step_summary(result)
    if result["status"] == "degraded":
        # Exit 3 tells the workflow "external block, not a code failure": preserve
        # the previous shows, record a degraded snapshot, and keep deploying.
        print(
            "WARNING: every source was blocked or failed; previous listings preserved "
            "and this run is stored as degraded.",
            file=sys.stderr,
        )
        return 3
    return 0


def _write_step_summary(result: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    totals = result["totals"]
    lines = [
        f"## Doomsday Watch â€” {result['status']}",
        "",
        f"- Theatres with listings: **{totals['theatres_with_listings']}/{totals['theatres_monitored']}**",
        f"- Shows: **{totals['shows_total']}** (3D: {totals['shows_3d']}, Infinity Vision 3D: {totals['shows_infinity_vision_3d']})",
        f"- Bookable shows: **{totals['bookable_shows']}**",
        f"- Sources: `{json.dumps(result['sources'])}`",
        f"- Notifications sent: {len(result['notifications'].get('sent', []))}",
        "",
        "### Changes this run",
    ]
    if result["events"]:
        lines += [f"- **{e['type']}** â€” {e['message']}" for e in result["events"][:25]]
    else:
        lines.append("- No changes detected.")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _payload_digest(payload: dict) -> str:
    """Stable hash of the source data, excluding collection timestamps."""
    if int(payload.get("schema_version", 0)) >= 2:
        canonical = {
            "movies": [
                {
                    "id": entry.get("id"),
                    "status": entry.get("status"),
                    "content_id": entry.get("content_id"),
                    "error": entry.get("error"),
                    "movie": entry.get("movie"),
                    "show_dates": entry.get("show_dates"),
                    "groups": entry.get("groups"),
                }
                for entry in payload.get("movies", [])
                if isinstance(entry, dict)
            ]
        }
    else:
        canonical = {
            "content_id": payload.get("content_id"),
            "movie": payload.get("movie"),
            "groups": payload.get("groups"),
        }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _movie_entries(payload: dict, config) -> list[tuple[object, dict]]:
    """Return (movie config, entry payload) pairs for schema 1 or 2."""
    version = int(payload.get("schema_version", 0))
    if version == 1:
        return [(config.primary_movie, payload)]
    if version != 2:
        raise ValueError(f"unsupported payload schema_version {payload.get('schema_version')!r}")
    raw_movies = payload.get("movies")
    if not isinstance(raw_movies, list) or not raw_movies:
        raise ValueError("payload has no movies list")
    entries = {
        str(entry.get("id") or ""): entry
        for entry in raw_movies if isinstance(entry, dict)
    }
    missing = [movie.id for movie in config.movies if movie.id not in entries]
    if missing:
        raise ValueError(f"payload is missing configured movie(s): {', '.join(missing)}")
    return [(movie, entries[movie.id]) for movie in config.movies]


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest the NAS collector's District inbox without making network calls."""
    try:
        config = load_config(args.config)
        path = Path(args.file)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        version = int(payload.get("schema_version", 0))
        if version not in (1, 2):
            raise ValueError(f"unsupported payload schema_version {payload.get('schema_version')!r}")

        collected = parse_iso(str(payload.get("collected_at") or ""))
        now = now_ist()
        if collected - now > timedelta(minutes=10):
            raise ValueError("payload collection timestamp is in the future")
        if now - collected > timedelta(hours=3):
            raise ValueError("payload is more than 3 hours old; refusing to overwrite newer data")

        entries = _movie_entries(payload, config)
        covered = {movie.id for movie, _ in entries}
        source_results = []
        for movie in config.movies:
            if movie.id in covered:
                continue
            source_results.append(SourceResult(
                source="district",
                status="partial",
                movie_id=movie.id,
                message=f"{movie.title} is not present in this collector payload",
                checked_at=payload.get("collected_at") or iso_ist(),
                evidence={"transport": "nas_inbox", "movie_id": movie.id},
            ))
        for movie, entry in entries:
            status = str(entry.get("status") or "ok")
            if status in {"unavailable", "error"}:
                source_results.append(SourceResult(
                    source="district",
                    status="error",
                    movie_id=movie.id,
                    message=str(entry.get("error") or f"District page unavailable for {movie.title}"),
                    checked_at=payload.get("collected_at") or iso_ist(),
                    evidence={"transport": "nas_inbox", "movie_id": movie.id},
                ))
                continue
            entry_payload = {
                **entry,
                "source": "district",
                "collected_at": payload.get("collected_at"),
                "content_id": entry.get("content_id") or movie.district_content_id,
            }
            source_results.append(district.result_from_payload(
                config,
                entry_payload,
                movie=movie,
                source_url=entry.get("movie_url"),
            ))
        digest = _payload_digest(payload)

        store = Store(args.data)
        latest = store.load_latest()
        previous_prov = latest.get("provenance") or {}
        previous_collected = previous_prov.get("collected_at")
        if previous_collected:
            try:
                previous_dt = parse_iso(str(previous_collected))
            except ValueError:
                previous_dt = None
            if previous_dt is not None and collected < previous_dt:
                raise ValueError(
                    f"payload is older than the current snapshot ({previous_collected})"
                )
        same_payload = (
            previous_prov.get("content_sha256") == digest
            and previous_prov.get("normalizer_version") == PAYLOAD_NORMALIZER_VERSION
        )
        if same_payload:
            print(f"District inbox unchanged (sha256={digest[:12]}â€¦); no data written.")
            if args.github_summary:
                _write_ingest_summary(None, digest, unchanged=True)
            return 0

        provenance = {
            "collector": payload.get("collector") or {},
            "transport": "nas_inbox",
            "collected_at": payload.get("collected_at"),
            "ingested_at": iso_ist(),
            "content_sha256": digest,
            "payload_schema_version": payload.get("schema_version"),
            "normalizer_version": PAYLOAD_NORMALIZER_VERSION,
            "movies": [movie.id for movie, _ in entries],
        }
        result = run_monitor(
            args.config,
            args.data,
            dry_run=args.dry_run,
            skip_notifications=args.skip_notifications,
            trigger=args.trigger,
            prefetched_results=source_results,
            provenance=provenance,
        )
        print(_summarise(result))
        for event in result["events"]:
            print(f"  [{event['severity']}] {event.get('movie_title', '')} {event['type']}: {event['message']}")
        if args.github_summary:
            _write_ingest_summary(result, digest, unchanged=False)
        return 0
    except Exception as exc:  # noqa: BLE001 - validation failures must exit non-zero
        print(f"ingest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def _write_ingest_summary(result: dict | None, digest: str, *, unchanged: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    if unchanged or result is None:
        lines = [
            "## Doomsday Watch â€” NAS ingest",
            "",
            f"- District payload SHA-256: `{digest}`",
            "- Content unchanged; no data files were written.",
        ]
    else:
        totals = result["totals"]
        lines = [
            f"## Doomsday Watch â€” NAS ingest ({result['status']})",
            "",
            f"- District payload SHA-256: `{digest}`",
            f"- Theatres with listings: **{totals['theatres_with_listings']}/{totals['theatres_monitored']}**",
            f"- Shows: **{totals['shows_total']}** (3D: {totals['shows_3d']}, Infinity Vision 3D: {totals['shows_infinity_vision_3d']})",
            f"- Events: **{len(result['events'])}**",
            f"- Sources: `{json.dumps(result['sources'])}`",
        ]
        if result["events"]:
            lines += ["", "### Changes"] + [f"- **{e['type']}** â€” {e['message']}" for e in result["events"][:25]]
        else:
            lines += ["", "No change events detected."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_probe(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(args.data)
    store.ensure()
    report = []
    with HttpClient(
        user_agent=config.monitoring.user_agent,
        timeout_seconds=config.monitoring.request_timeout_seconds,
        max_retries=config.monitoring.max_retries,
        backoff_seconds=config.monitoring.retry_backoff_seconds,
        cache_dir=store.cache,
    ) as client:
        for name, adapter in ADAPTERS.items():
            if not config.sources.get(name, {}).get("enabled", False):
                report.append({"source": name, "status": "disabled"})
                continue
            try:
                result = adapter(config, client, store.cache)
                report.append({
                    "source": name, "status": result.status, "message": result.message,
                    "evidence": result.evidence, "movie": result.movie,
                    "theatres_with_shows": sum(1 for o in result.observations.values() if o.shows),
                })
            except Exception as exc:  # noqa: BLE001
                report.append({"source": name, "status": "error", "message": f"{type(exc).__name__}: {exc}"})
    payload = {"checked_at": iso_ist(), "checks": report}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.write:
        path = Path(args.data) / "sources-probe.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


def cmd_notify_test(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    notifier = Notifier(config, dry_run=False)
    channels = notifier.enabled_channels()
    print(f"Configured channels: {channels or 'none (set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, NTFY_TOPIC or NOTIFY_WEBHOOK_URL)'}")
    if not channels:
        return 1
    with __import__("httpx").Client(timeout=12.0) as client:
        errors = []
        for channel in channels:
            try:
                if channel == "telegram":
                    notifier._telegram(client, "Doomsday Watch test", "Test alert from Doomsday Watch.")
                elif channel == "ntfy":
                    notifier._ntfy(client, "Doomsday Watch test", "Test alert from Doomsday Watch.")
                elif channel == "webhook":
                    notifier._webhook(client, "Doomsday Watch test", "Test alert from Doomsday Watch.")
                print(f"  {channel}: ok")
            except Exception as exc:  # noqa: BLE001
                errors.append(channel)
                print(f"  {channel}: FAILED â€” {type(exc).__name__}: {exc}")
    return 1 if errors else 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"invalid config: {exc}", file=sys.stderr)
        return 1
    print(f"config ok: {len(config.theatres)} theatres, dates={config.target_dates}, "
          f"interval={config.monitoring.interval_minutes}m")
    latest = Store(args.data).load_latest()
    if latest:
        required = {"schema_version", "checked_at", "totals", "theatres", "sources"}
        missing = required - set(latest)
        if missing:
            print(f"invalid data/latest.json: missing {sorted(missing)}", file=sys.stderr)
            return 1
        ids = {t["id"] for t in latest["theatres"]}
        unknown = ids - {t.id for t in config.theatres}
        if unknown:
            print(f"warning: snapshot has theatres not in config: {sorted(unknown)}")
        print(f"latest.json ok: {latest['checked_at']} ({latest['status']})")
    else:
        print("no snapshot yet (run `python -m doomsday_watch run`)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    os.environ.setdefault("DOOMSDAY_DATA", str(args.data))
    uvicorn.run("doomsday_watch.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="doomsday_watch", description="Avengers: Doomsday ticket monitor")
    parser.add_argument("--config", default=None, help="path to config/monitor.json")
    parser.add_argument("--data", default="data", help="data directory (default: data)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one monitoring pass")
    run.add_argument("--dry-run", action="store_true", help="check sources and report changes without writing data or sending alerts")
    run.add_argument("--skip-notifications", action="store_true")
    run.add_argument("--trigger", default="manual")
    run.add_argument("--github-summary", action="store_true")
    run.set_defaults(func=cmd_run)

    ingest = sub.add_parser("ingest", help="ingest the NAS collector's District inbox (no network)")
    ingest.add_argument("--file", default="data/inbox/district.json", help="inbox JSON path")
    ingest.add_argument("--dry-run", action="store_true", help="validate and diff without writing data or sending alerts")
    ingest.add_argument("--skip-notifications", action="store_true")
    ingest.add_argument("--trigger", default="nas")
    ingest.add_argument("--github-summary", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    probe = sub.add_parser("probe", help="probe booking platforms and print a report")
    probe.add_argument("--write", action="store_true", help="write data/sources-probe.json")
    probe.set_defaults(func=cmd_probe)

    notify = sub.add_parser("notify-test", help="send a test notification")
    notify.set_defaults(func=cmd_notify_test)

    validate = sub.add_parser("validate", help="validate config and latest snapshot")
    validate.set_defaults(func=cmd_validate)

    serve = sub.add_parser("serve", help="serve the optional FastAPI backend")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
