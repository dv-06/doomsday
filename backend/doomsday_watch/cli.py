"""Command line entry points.

    python -m doomsday_watch run            # one monitoring pass (used by Actions)
    python -m doomsday_watch probe          # source accessibility report only
    python -m doomsday_watch notify-test    # send a test alert to configured channels
    python -m doomsday_watch validate       # validate config + data files
    python -m doomsday_watch serve          # local FastAPI backend
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ConfigError, iso_ist, load_config
from .http import HttpClient
from .monitor import ADAPTERS, run_monitor
from .notify import Notifier
from .store import Store


def _summarise(result: dict) -> str:
    totals = result["totals"]
    return (
        f"status={result['status']} shows={totals['shows_total']} "
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
        print("WARNING: every source failed; last known snapshot preserved.", file=sys.stderr)
        return 2
    return 0


def _write_step_summary(result: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    totals = result["totals"]
    lines = [
        f"## Doomsday Watch — {result['status']}",
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
        lines += [f"- **{e['type']}** — {e['message']}" for e in result["events"][:25]]
    else:
        lines.append("- No changes detected.")
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
                print(f"  {channel}: FAILED — {type(exc).__name__}: {exc}")
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
    run.add_argument("--dry-run", action="store_true", help="skip sending notifications")
    run.add_argument("--skip-notifications", action="store_true")
    run.add_argument("--trigger", default="manual")
    run.add_argument("--github-summary", action="store_true")
    run.set_defaults(func=cmd_run)

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
