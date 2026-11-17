"""Optional FastAPI backend.

The production dashboard is static (GitHub Pages reads data/*.json committed by
the hourly workflow), so this API is *not* required for the ₹0 setup. It exists
for local development, for a self-hosted deployment, and to trigger a run on
demand.

Run locally:
    uvicorn doomsday_watch.api:app --reload --app-dir backend
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import iso_ist, load_config
from .monitor import run_monitor
from .store import Store

DATA_DIR = Path(os.environ.get("DOOMSDAY_DATA", "data"))
CONFIG_PATH = os.environ.get("DOOMSDAY_CONFIG")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(
    title="Doomsday Watch API",
    version=__version__,
    description="Read-only snapshot/history API plus a token-protected manual run trigger.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _store() -> Store:
    return Store(DATA_DIR)


@app.get("/api/health")
def health() -> dict[str, Any]:
    latest = _store().load_latest()
    return {
        "status": "ok",
        "version": __version__,
        "checked_at": iso_ist(),
        "has_snapshot": bool(latest),
        "snapshot_age_minutes": latest.get("checked_at"),
        "data_dir": str(DATA_DIR.resolve()),
    }


@app.get("/api/latest")
def latest() -> JSONResponse:
    payload = _store().load_latest()
    if not payload:
        raise HTTPException(status_code=404, detail="No snapshot yet. Run `python -m doomsday_watch run` first.")
    return JSONResponse(payload, headers={"Cache-Control": "public, max-age=60"})


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    store = _store()
    return {
        "meta": store.load_meta(),
        "state": store.load_state(),
        "config": {
            "theatres": [
                {"id": t.id, "name": t.name, "area": t.area, "aliases": list(t.aliases)}
                for t in load_config(CONFIG_PATH).theatres
            ],
            "target_dates": list(load_config(CONFIG_PATH).target_dates),
            "interval_minutes": load_config(CONFIG_PATH).monitoring.interval_minutes,
        },
    }


@app.get("/api/history/events")
def history_events(limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    rows = _store().events()
    return {"count": len(rows), "events": rows[-limit:][::-1]}


@app.get("/api/history/runs")
def history_runs(limit: int = Query(168, ge=1, le=5000)) -> dict[str, Any]:
    rows = _store().runs()
    return {"count": len(rows), "runs": rows[-limit:]}


@app.get("/api/theatres")
def theatres() -> dict[str, Any]:
    payload = _store().load_latest()
    return {"theatres": payload.get("theatres", []), "checked_at": payload.get("checked_at")}


@app.get("/api/theatres/{theatre_id}")
def theatre(theatre_id: str) -> dict[str, Any]:
    payload = _store().load_latest()
    for item in payload.get("theatres", []):
        if item.get("id") == theatre_id:
            return item
    raise HTTPException(status_code=404, detail=f"Unknown theatre {theatre_id!r}")


@app.post("/api/monitor/run")
def trigger_run(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    skip_notifications: bool = False,
) -> dict[str, Any]:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Manual runs are disabled (set ADMIN_TOKEN to enable).")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token.")
    result = run_monitor(CONFIG_PATH, DATA_DIR, skip_notifications=skip_notifications, trigger="api")
    return {
        "run_id": result["run_id"],
        "status": result["status"],
        "totals": result["totals"],
        "events": len(result["events"]),
        "sources": result["sources"],
    }
