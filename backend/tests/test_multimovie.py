"""Multi-movie config, 4DX 3D matching, date boundaries and duplicate ingest."""

import json
from pathlib import Path

from doomsday_watch.cli import main
from doomsday_watch.config import iso_ist
from doomsday_watch.sources import district

from test_district import _payload_from_fixture

RAMAYANA_MOVIE = {
    "content_id": "176276",
    "title": "Ramayana",
    "release_date": "2026-11-05",
    "duration_minutes": 195,
    "primary_language": "Hindi",
    "languages": ["Hindi", "Telugu", "Tamil"],
    "poster": "https://example.test/ramayana.jpg",
}


def _session(sid: str, show_time: str, fmt: str = "4DX-3D", avail: int = 30) -> dict:
    return {
        "sid": sid,
        "showTime": show_time,
        "audi": "AUDI 04",
        "scrnFmt": fmt,
        "total": 100,
        "avail": avail,
        "seatStatus": "Available",
        "areas": [{"label": "4DX", "price": 900, "sTotal": 100, "sAvail": avail, "seatStatus": "Available"}],
        "tags": ["4dx"],
    }


def _ramayana_group() -> dict:
    return {
        "data": {"id": "1022299", "name": "PVR Orion Mall, Dr Rajkumar Road, Bengaluru"},
        "entityUrl": "/movies/pvr-orion-mall-dr-rajkumar-road-bengaluru-c/1022299",
        "sessions": [
            # Naive UTC 06:10 -> 11:40 IST. Explicit 4DX-3D only.
            _session("rx-1", "2026-11-19T06:10:00"),
            # Same screen, plain 3D: must never be counted as 4DX 3D.
            _session("rx-2", "2026-11-19T07:10:00", fmt="3D"),
            # UTC date is Nov 18 but the IST show is Nov 19 00:00.
            _session("rx-3", "2026-11-18T18:30:00"),
            # Not in Ramayana's target window: excluded after IST conversion.
            _session("rx-4", "2026-12-01T06:10:00"),
        ],
    }


def _ramayana_payload(collected_at: str) -> dict:
    return {
        "schema_version": 2,
        "source": "district",
        "collected_at": collected_at,
        "collector": {"name": "test", "version": "2.0.0", "egress": "IN"},
        "movies": [
            {
                "id": "ramayana",
                "status": "ok",
                "content_id": "176276",
                "movie_url": "https://www.district.in/movies/ramayana-movie-tickets-in-bengaluru-MV176276",
                "movie": RAMAYANA_MOVIE,
                "groups": [_ramayana_group()],
            }
        ],
    }


def _combined_payload(fixture_html: str, collected_at: str) -> dict:
    avengers = _payload_from_fixture(fixture_html, collected_at)
    avengers_entry = {
        "id": "avengers-doomsday",
        "status": "ok",
        "content_id": avengers["content_id"],
        "movie_url": avengers["movie_url"],
        "movie": avengers["movie"],
        "groups": avengers["groups"],
    }
    ramayana = _ramayana_payload(collected_at)["movies"][0]
    return {
        "schema_version": 2,
        "source": "district",
        "collected_at": collected_at,
        "collector": {"name": "test", "version": "2.0.0", "egress": "IN"},
        "movies": [avengers_entry, ramayana],
    }


def test_config_tracks_two_movies_with_separate_dates(config):
    assert [m.id for m in config.movies] == ["avengers-doomsday", "ramayana"]
    ramayana = config.movie("ramayana")
    assert ramayana.district_content_id == "176276"
    assert ramayana.required_format_keys == ("4dx_3d",)
    assert len(ramayana.target_dates) == 21
    assert "2026-11-18" in ramayana.target_dates
    assert "2026-11-30" in ramayana.target_dates
    assert "2026-12-05" in ramayana.target_dates
    assert "2026-12-01" not in ramayana.target_dates


def test_ramayana_keeps_only_explicit_4dx_3d_in_ist(config):
    movie = config.movie("ramayana")
    payload = _ramayana_payload(iso_ist())
    result = district.result_from_payload(
        config, {**payload["movies"][0], "source": "district",
                 "collected_at": payload["collected_at"]}, movie=movie,
    )
    assert result.movie_id == "ramayana"
    orion = result.observations["orion-mall"]
    assert len(orion.shows) == 2, "plain 3D and non-target dates must be dropped"
    assert all(show["format"]["key"] == "4dx_3d" for show in orion.shows)
    assert [show["start"] for show in orion.shows] == ["11:40", "00:00"]
    assert [show["date"] for show in orion.shows] == ["2026-11-19", "2026-11-19"]
    assert orion.shows[0]["source_time"] == "2026-11-19T06:10:00"
    assert orion.shows[0]["start_iso"].startswith("2026-11-19T11:40:00+05:30")
    assert orion.raw_show_count == 4


def test_combined_ingest_is_separate_and_duplicate_safe(config, fixture_html, tmp_path, repo_root):
    inbox = tmp_path / "district.json"
    data = tmp_path / "data"
    inbox.write_text(json.dumps(_combined_payload(fixture_html, iso_ist())), encoding="utf-8")
    args = [
        "--config", str(repo_root / "config/monitor.json"),
        "--data", str(data),
        "ingest", "--file", str(inbox), "--skip-notifications",
    ]
    assert main(args) == 0
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["schema_version"] == 2
    assert [m["movie"]["id"] for m in latest["movies"]] == ["avengers-doomsday", "ramayana"]
    avengers, ramayana = latest["movies"]
    assert avengers["totals"]["shows_total"] > 0
    assert ramayana["totals"]["shows_total"] == 2
    assert ramayana["totals"]["shows_4dx_3d"] == 2
    assert latest["totals"]["movies_tracked"] == 2
    assert latest["totals"]["shows_total"] == avengers["totals"]["shows_total"] + 2

    av_ids = {s["id"] for t in avengers["theatres"] for s in t["shows"]}
    ram_ids = {s["id"] for t in ramayana["theatres"] for s in t["shows"]}
    assert av_ids.isdisjoint(ram_ids), "the two movies must not share session identities"
    assert latest["events"]
    assert {e["movie_id"] for e in latest["events"]} == {"avengers-doomsday", "ramayana"}

    runs = (data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert main(args) == 0
    assert len((data / "history/runs.jsonl").read_text(encoding="utf-8").splitlines()) == len(runs)
    repaired = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert len(repaired["movies"]) == 2
    ids = [s["id"] for m in repaired["movies"] for t in m["theatres"] for s in t["shows"]]
    assert len(ids) == len(set(ids)), "re-ingest must not duplicate sessions"
