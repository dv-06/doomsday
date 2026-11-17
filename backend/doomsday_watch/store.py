"""Persistent, git-friendly storage.

GitHub Actions has no durable disk between runs, so the repository *is* the
database: every run commits JSON under data/. This keeps the project at ₹0,
works from a phone, and gives you a browsable audit trail in git history.

Layout
------
data/latest.json                  newest snapshot + everything the UI needs
data/state.json                   stable IDs, first-seen timestamps, notified hashes
data/meta.json                    run + source health summary
data/snapshots/YYYY/MM/<ts>.json  hourly snapshots (pruned by policy)
data/history/events.jsonl         append-only change log (never pruned)
data/history/runs.jsonl           append-only run log
data/sources.json                 source accessibility report
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import iso_ist


class Store:
    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.history = self.root / "history"
        self.snapshots = self.root / "snapshots"
        self.cache = self.root / "cache"

    # ---------- low level ----------
    def ensure(self) -> None:
        for path in (self.root, self.history, self.snapshots, self.cache):
            path.mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _append_jsonl(self, path: Path, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    # ---------- typed accessors ----------
    def load_latest(self) -> dict[str, Any]:
        return self._read_json(self.root / "latest.json", {})

    def load_state(self) -> dict[str, Any]:
        return self._read_json(self.root / "state.json", {})

    def load_meta(self) -> dict[str, Any]:
        return self._read_json(self.root / "meta.json", {})

    def load_sources(self) -> dict[str, Any]:
        return self._read_json(self.root / "sources.json", {})

    def events(self) -> list[dict[str, Any]]:
        return self.read_jsonl(self.history / "events.jsonl")

    def runs(self) -> list[dict[str, Any]]:
        return self.read_jsonl(self.history / "runs.jsonl")

    # ---------- writes ----------
    def write_run(
        self,
        *,
        snapshot: dict[str, Any],
        state: dict[str, Any],
        meta: dict[str, Any],
        events: list[dict[str, Any]],
        sources: dict[str, Any],
        retention: tuple[int, int],
    ) -> Path:
        self.ensure()
        checked = snapshot.get("checked_at") or iso_ist()
        stamp = datetime.fromisoformat(checked).astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        snapshot_path = self.snapshots / stamp[:4] / stamp[5:7] / f"{stamp}.json"
        self._write_json(snapshot_path, snapshot)
        self._write_json(self.root / "latest.json", snapshot)
        self._write_json(self.root / "state.json", state)
        self._write_json(self.root / "meta.json", meta)
        self._write_json(self.root / "sources.json", sources)
        self._append_jsonl(self.history / "events.jsonl", events)
        self._append_jsonl(self.history / "runs.jsonl", [{
            key: snapshot.get(key)
            for key in ("run_id", "checked_at", "status", "totals", "duration_ms")
        } | {"sources": {name: s.get("status") for name, s in sources.get("sources", {}).items()}}])
        self.prune(*retention)
        return snapshot_path

    def prune(self, hourly_keep: int, daily_keep: int) -> int:
        files = sorted(self.snapshots.glob("*/*/*.json"), reverse=True)
        keep: set[Path] = set(files[:hourly_keep])
        seen_days: set[str] = set()
        for path in files[hourly_keep:]:
            day = path.name[:10]
            if day not in seen_days and len(seen_days) < daily_keep:
                keep.add(path)
                seen_days.add(day)
        removed = 0
        for path in files:
            if path not in keep:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
