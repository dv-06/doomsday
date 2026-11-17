"""Free notification channels: Telegram bot, ntfy.sh, generic webhook.

All credentials come from environment variables / GitHub Actions secrets.
Browser notifications are handled by the frontend; this module handles the
"computer is switched off" case.
"""

from __future__ import annotations

import html
import os
from typing import Any

import httpx

from .config import AppConfig, iso_ist

TYPE_ICONS = {
    "theatre_listed": "🎬",
    "first_show": "🎟️",
    "show_added": "🕒",
    "format_added": "✨",
    "booking_opened": "✅",
    "sold_out": "⛔",
    "seats_dropped": "📉",
    "price_changed": "💸",
    "show_removed": "➖",
    "date_added": "📅",
    "source_blocked": "🚫",
    "source_recovered": "🔁",
}


def _format_lines(events: list[dict[str, Any]], site_url: str | None = None) -> list[str]:
    lines = []
    for event in events:
        icon = TYPE_ICONS.get(event["type"], "•")
        lines.append(f"{icon} {event['message']}")
    if site_url:
        lines.append(f"\nDashboard: {site_url}")
    return lines


class Notifier:
    def __init__(self, config: AppConfig, *, dry_run: bool = False, timeout: float = 12.0) -> None:
        self.config = config
        self.dry_run = dry_run
        self.timeout = timeout
        self.secrets = config.notifications.credentials()
        self.site_url = os.environ.get("DASHBOARD_URL")

    def enabled_channels(self) -> list[str]:
        channels = []
        cfg = self.config.notifications.raw
        if cfg.get("telegram", {}).get("enabled") and self.secrets.get("TELEGRAM_BOT_TOKEN") and self.secrets.get("TELEGRAM_CHAT_ID"):
            channels.append("telegram")
        if cfg.get("ntfy", {}).get("enabled") and self.secrets.get("NTFY_TOPIC"):
            channels.append("ntfy")
        if cfg.get("webhook", {}).get("enabled") and self.secrets.get("NOTIFY_WEBHOOK_URL"):
            channels.append("webhook")
        return channels

    def select(self, events: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
        notify_on = set(self.config.notifications.notify_on)
        notified = state.get("notified", {}) or {}
        selected = [
            e for e in events
            if (not notify_on or e["type"] in notify_on) and e["id"] not in notified
        ]
        priority = {"high": 0, "medium": 1, "low": 2}
        selected.sort(key=lambda e: (priority.get(e["severity"], 3), e["created_at"]))
        return selected

    def dispatch(self, events: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        selected = self.select(events, state)
        result: dict[str, Any] = {
            "checked_at": iso_ist(),
            "channels": self.enabled_channels(),
            "candidates": len(selected),
            "sent": [],
            "skipped": [],
            "errors": [],
        }
        if not selected:
            return result
        if self.dry_run:
            result["skipped"].append({"reason": "dry run"})
            return result
        if not result["channels"]:
            result["skipped"].append({"reason": "no notification credentials configured"})
            return result

        cap = int(self.config.notifications.raw.get("max_events_per_message", 8))
        batch = selected[:cap]
        header = f"Avengers: Doomsday — {len(batch)} update(s)"
        lines = _format_lines(batch, self.site_url)
        body = "\n".join(lines)
        more = len(selected) - len(batch)
        if more > 0:
            body += f"\n…and {more} more change(s) on the dashboard."

        with httpx.Client(timeout=self.timeout, headers={"User-Agent": "DoomsdayWatch/1.0"}) as client:
            for channel in result["channels"]:
                try:
                    if channel == "telegram":
                        self._telegram(client, header, body)
                    elif channel == "ntfy":
                        self._ntfy(client, header, body)
                    elif channel == "webhook":
                        self._webhook(client, header, body)
                    result["sent"].append({"channel": channel, "events": [e["id"] for e in batch]})
                except Exception as exc:  # noqa: BLE001 - never let alerts break monitoring
                    result["errors"].append({"channel": channel, "error": f"{type(exc).__name__}: {exc}"})

        if result["sent"]:
            notified = state.setdefault("notified", {})
            stamp = iso_ist()
            for event in batch:
                notified[event["id"]] = stamp
        return result

    # ---------- channels ----------
    def _telegram(self, client: httpx.Client, header: str, body: str) -> None:
        token = self.secrets["TELEGRAM_BOT_TOKEN"]
        chat_id = self.secrets["TELEGRAM_CHAT_ID"]
        text = f"<b>{html.escape(header)}</b>\n{html.escape(body)}"
        response = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram rejected the message: {payload.get('description')}")

    def _ntfy(self, client: httpx.Client, header: str, body: str) -> None:
        server = (self.config.notifications.raw.get("ntfy", {}) or {}).get("server", "https://ntfy.sh").rstrip("/")
        topic = self.secrets["NTFY_TOPIC"]
        response = client.post(
            f"{server}/{topic}",
            content=body.encode("utf-8"),
            headers={
                "Title": header.encode("ascii", "ignore").decode("ascii") or "Doomsday Watch",
                "Tags": "movie_camera,ticket",
                "Priority": "high",
            },
        )
        response.raise_for_status()

    def _webhook(self, client: httpx.Client, header: str, body: str) -> None:
        url = self.secrets["NOTIFY_WEBHOOK_URL"]
        response = client.post(url, json={"content": f"**{header}**\n{body}", "text": f"{header}\n{body}"})
        response.raise_for_status()


def prune_notified(state: dict[str, Any], keep_days: int = 30) -> None:
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    notified = state.get("notified", {})
    for key, stamp in list(notified.items()):
        try:
            when = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            notified.pop(key, None)
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            notified.pop(key, None)
