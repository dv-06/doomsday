"""NAS inbox ingestion: no network, strict validation, no duplicate writes."""

import copy
import json
from pathlib import Path

import pytest

from doomsday_watch.cli import main
from doomsday_watch.config import iso_ist
from doomsday_watch.sources import district

from test_district import _payload_from_fixture


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "district.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ingest_updates_existing_schema_without_network(
    config, fixture_html, tmp_path, repo_root
):
    payload = _payload_from_fixture(fixture_html, iso_ist())
    inbox = _write_payload(tmp_path, payload)
    data = tmp_path / "data"
    code = main([
        "--config", str(repo_root / "config/monitor.json"),
        "--data", str(data),
        "ingest", "--file", str(inbox), "--skip-notifications",
    ])
    assert code == 0
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["status"] == "partial"
    assert latest["provenance"]["transport"] == "nas_inbox"
    assert latest["provenance"]["content_sha256"]
    district_src = next(s for s in latest["sources"] if s["source"] == "district")
    assert district_src["status"] == "partial"
    assert district_src["checked_at"] == payload["collected_at"]
    assert latest["totals"]["shows_total"] > 0
    assert {m["movie"]["id"] for m in latest["movies"]} == {
        "avengers-doomsday", "ramayana",
    }
    # Existing dashboard schema is preserved.
    assert {"schema_version", "checked_at", "totals", "theatres", "sources"} <= set(latest)


def test_duplicate_payload_does_not_append_another_run(
    config, fixture_html, tmp_path, repo_root
):
    payload = _payload_from_fixture(fixture_html, iso_ist())
    inbox = _write_payload(tmp_path, payload)
    data = tmp_path / "data"
    args = [
        "--config", str(repo_root / "config/monitor.json"),
        "--data", str(data),
        "ingest", "--file", str(inbox), "--skip-notifications",
    ]
    assert main(args) == 0
    runs = (data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert main(args) == 0
    assert len((data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines()) == len(runs)


def test_stale_or_malformed_payload_preserves_current_snapshot(
    config, fixture_html, tmp_path, repo_root
):
    payload = _payload_from_fixture(fixture_html, iso_ist())
    inbox = _write_payload(tmp_path, payload)
    data = tmp_path / "data"
    base = ["--config", str(repo_root / "config/monitor.json"), "--data", str(data), "ingest"]
    assert main(base + ["--file", str(inbox), "--skip-notifications"]) == 0
    before = (data / "latest.json").read_bytes()

    stale = copy.deepcopy(payload)
    stale["collected_at"] = "2026-11-17T10:00:00+05:30"
    _write_payload(tmp_path, stale)
    assert main(base + ["--file", str(inbox), "--skip-notifications"]) == 2
    assert (data / "latest.json").read_bytes() == before

    bad = copy.deepcopy(payload)
    bad.pop("movie")
    _write_payload(tmp_path, bad)
    assert main(base + ["--file", str(inbox), "--skip-notifications"]) == 2
    assert (data / "latest.json").read_bytes() == before


def test_payload_mapping_is_pure_and_does_not_fetch(config, fixture_html, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("payload import must not make network calls")

    monkeypatch.setattr(district, "fetch", explode)
    result = district.result_from_payload(config, _payload_from_fixture(fixture_html))
    assert result.status == "ok"


def test_legacy_provenance_is_reingested_once_without_duplicate_sessions(
    config, fixture_html, tmp_path, repo_root
):
    payload = _payload_from_fixture(fixture_html, iso_ist())
    inbox = _write_payload(tmp_path, payload)
    data = tmp_path / "data"
    args = [
        "--config", str(repo_root / "config/monitor.json"),
        "--data", str(data),
        "ingest", "--file", str(inbox), "--skip-notifications",
    ]
    assert main(args) == 0
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    latest["provenance"].pop("normalizer_version", None)
    (data / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    runs_before = len((data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines())

    assert main(args) == 0
    repaired = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert repaired["provenance"]["normalizer_version"] == 6
    assert len((data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines()) == runs_before + 1
    ids = [s["id"] for t in repaired["theatres"] for s in t["shows"]]
    assert len(ids) == len(set(ids)), "re-ingestion must not duplicate sessions"

    assert main(args) == 0
    assert len((data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines()) == runs_before + 1
