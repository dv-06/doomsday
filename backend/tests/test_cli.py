"""CLI parsing and dry-run / persistence behaviour."""

from pathlib import Path

import pytest

from doomsday_watch import monitor
from doomsday_watch.cli import main
from doomsday_watch.models import SourceResult, TheatreObservation, make_show


def _show(theatre_id: str = "lulu-global-mall"):
    return make_show(
        platform="district",
        theatre_id=theatre_id,
        date="2026-12-17",
        start="19:10",
        screen="AUDI 06",
        raw_format="INFINITY VISION 3D",
        areas=[{"label": "PRIME", "price": 780, "sTotal": 100, "sAvail": 42, "seatStatus": "Available"}],
        total=100,
        available=42,
        raw_status="Available",
        booking_url="https://example.test/book",
        source_show_id="1910",
    )


def _fake_district(config, client, cache_dir=None):
    observations = {}
    for theatre in config.theatres:
        listed = theatre.id == "lulu-global-mall"
        observations[theatre.id] = TheatreObservation(
            platform="district",
            theatre_id=theatre.id,
            status="ok" if listed else "not_listed",
            listed=listed,
            venue={"id": theatre.district_id, "name": theatre.name, "url": "https://example.test/venue"},
            shows=[_show(theatre.id)] if listed else [],
        )
    return SourceResult(source="district", status="ok", message="fixture", observations=observations)


def _blocked_district(config, client, cache_dir=None):
    observations = {
        theatre.id: TheatreObservation(
            platform="district", theatre_id=theatre.id, status="blocked",
            listed=None, error="challenge",
        )
        for theatre in config.theatres
    }
    return SourceResult(source="district", status="blocked", message="challenge", observations=observations)


def _empty_bookmyshow(config, client, cache_dir=None):
    observations = {
        theatre.id: TheatreObservation(
            platform="bookmyshow", theatre_id=theatre.id, status="not_listed",
            listed=False, shows=[],
        )
        for theatre in config.theatres
    }
    return SourceResult(source="bookmyshow", status="ok", message="no showtimes", observations=observations)


def test_dry_run_flag_is_a_run_option():
    # Global options belong before the subcommand; --dry-run is a `run` option.
    with pytest.raises(SystemExit) as exc:
        main(["--dry-run", "run"])
    assert exc.value.code == 2


def test_cli_parses_global_and_run_options(monkeypatch, repo_root):
    captured = {}

    def fake_run_monitor(config, data, **kwargs):
        captured.update({"config": str(config), "data": str(data), **kwargs})
        return {
            "run_id": "test",
            "status": "ok",
            "snapshot_path": None,
            "dry_run": True,
            "totals": {"shows_total": 0, "shows_3d": 0, "shows_infinity_vision_3d": 0,
                       "theatres_with_listings": 0, "theatres_monitored": 6},
            "events": [],
            "notifications": {"sent": []},
            "sources": {"district": "ok"},
        }

    monkeypatch.setattr("doomsday_watch.cli.run_monitor", fake_run_monitor)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code = main([
        "--config", str(repo_root / "config" / "monitor.json"),
        "--data", str(repo_root / "data"),
        "run", "--dry-run", "--skip-notifications", "--trigger", "schedule", "--github-summary",
    ])
    assert code == 0
    assert captured["dry_run"] is True
    assert captured["skip_notifications"] is True
    assert captured["trigger"] == "schedule"


def test_dry_run_does_not_write_any_files(config, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(monitor, "ADAPTERS", {"district": _fake_district})

    result = monitor.run_monitor(repo_config(config), data_dir, dry_run=True)

    assert result["dry_run"] is True
    assert result["snapshot_path"] is None
    assert result["totals"]["shows_total"] == 1
    assert not data_dir.exists(), "dry run must not create data files or directories"
    assert not (tmp_path / "cache").exists()


def test_dry_run_never_sends_notifications(config, tmp_path, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "unused-in-dry-run")
    monkeypatch.setattr(monitor, "ADAPTERS", {"district": _fake_district})

    def explode(*args, **kwargs):  # pragma: no cover - only runs if the guard fails
        raise AssertionError("notification must not be delivered during a dry run")

    monkeypatch.setattr(monitor.Notifier, "_ntfy", explode)
    result = monitor.run_monitor(config_path=repo_config(config), data_dir=tmp_path / "data", dry_run=True)

    assert result["notifications"]["sent"] == []
    assert result["notifications"]["skipped"][0]["reason"] == "dry run"
    assert not (tmp_path / "data").exists()


def test_normal_run_persists_snapshot_history_and_state(config, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(monitor, "ADAPTERS", {"district": _fake_district})

    result = monitor.run_monitor(config_path=repo_config(config), data_dir=data_dir, dry_run=False)

    assert result.get("dry_run") is not True
    assert result["status"] == "ok"
    assert result["snapshot_path"]
    for name in ("latest.json", "meta.json", "state.json", "sources.json"):
        assert (data_dir / name).is_file(), name
    assert (data_dir / "history" / "events.jsonl").is_file()
    assert (data_dir / "history" / "runs.jsonl").is_file()
    assert list((data_dir / "snapshots").glob("*/*/*.json"))


def test_partial_source_failure_keeps_previous_listings(config, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(monitor, "ADAPTERS", {"district": _fake_district})
    monitor.run_monitor(config_path=repo_config(config), data_dir=data_dir)

    monkeypatch.setattr(monitor, "ADAPTERS", {
        "district": _blocked_district,
        "bookmyshow": _empty_bookmyshow,
    })
    result = monitor.run_monitor(config_path=repo_config(config), data_dir=data_dir)

    assert result["status"] == "partial"
    latest = monitor.Store(data_dir).load_latest()
    lulu = next(t for t in latest["theatres"] if t["id"] == "lulu-global-mall")
    assert lulu["shows"], "previous listing must survive a blocked source"
    assert lulu["platforms"]["district"]["status"] == "stale"
    assert result["totals"]["shows_total"] >= 1
    assert monitor.Store(data_dir).load_latest()["sources"]


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "monitor.json"


def repo_config(config) -> Path:
    """The monitor under test always uses the repository config."""
    return CONFIG_PATH


def _partial_bookmyshow(config, client, cache_dir=None):
    observations = {
        theatre.id: TheatreObservation(
            platform="bookmyshow", theatre_id=theatre.id, status="not_listed",
            listed=False, shows=[], error="showtimes blocked",
        )
        for theatre in config.theatres
    }
    return SourceResult(
        source="bookmyshow", status="partial", message="movie visible, showtimes blocked",
        observations=observations,
    )


def test_partial_source_is_reported_as_partial_coverage(config, tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "ADAPTERS", {
        "district": _fake_district,
        "bookmyshow": _partial_bookmyshow,
    })
    result = monitor.run_monitor(config_path=repo_config(config), data_dir=tmp_path / "data")
    assert result["status"] == "partial"
    assert result["sources"] == {"district": "ok", "bookmyshow": "partial"}
