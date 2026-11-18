from pathlib import Path

from doomsday_watch.config import iso_ist
from doomsday_watch.diff import diff_snapshot
from doomsday_watch.models import SourceResult, TheatreObservation, make_show
from doomsday_watch.monitor import build_snapshot


def _show(start: str, date: str = "2026-12-17", *, available: int = 50, total: int = 100, area="CLASSIC ROWS"):
    return make_show(
        platform="district",
        theatre_id="lulu-global-mall",
        date=date,
        start=start,
        screen="AUDI 01",
        raw_format="MS INFINITY VISION 3D",
        areas=[{"label": area, "price": 900, "sTotal": total, "sAvail": available, "seatStatus": "Available"}],
        total=total,
        available=available,
        raw_status="Available",
        booking_url="https://example.test/book",
        source_show_id=start.replace(":", ""),
    )


def _source(config, shows, status="ok", source="district"):
    observations = {}
    for theatre in config.theatres:
        observations[theatre.id] = TheatreObservation(
            platform=source,
            theatre_id=theatre.id,
            status="ok" if theatre.id == "lulu-global-mall" else "not_listed",
            listed=theatre.id == "lulu-global-mall",
            venue={"id": theatre.district_id if source == "district" else "x",
                   "name": theatre.name, "url": f"https://example.test/{theatre.id}"},
            shows=[s for s in shows if s["theatre_id"] == theatre.id],
        )
    return SourceResult(
        source=source, status=status, message="test", movie_id=config.primary_movie.id,
        observations=observations,
    )


def _snapshot(config, previous, sources):
    snap, _, _ = build_snapshot(
        config.primary_movie, config, sources, previous, iso_ist(), 10, "test-run",
    )
    return snap


def test_first_run_emits_discovery_events_once(config):
    snap = _snapshot(config, {}, [_source(config, [_show("10:00"), _show("14:00")])])
    events, state = diff_snapshot({}, snap["theatres"], config, snap["sources"], movie=config.primary_movie)
    types = [e["type"] for e in events]
    assert all(e["time_basis"] == "ist" for e in events)
    assert "theatre_listed" in types
    assert "format_added" in types
    assert types.count("theatre_listed") == 1, "only the first released show is a theatre listing"
    assert state["theatres"]["lulu-global-mall"]["platforms"]["district"]["shows"]

    # A second identical run must not repeat the same alerts.
    snap2 = _snapshot(config, snap, [_source(config, [_show("10:00"), _show("14:00")])])
    events2, _ = diff_snapshot(state, snap2["theatres"], config, snap2["sources"])
    assert [e for e in events2 if e["type"] in {"theatre_listed", "show_added", "format_added"}] == []


def test_new_show_and_first_show_on_second_date(config):
    first = _snapshot(config, {}, [_source(config, [_show("10:00")])])
    _, state = diff_snapshot({}, first["theatres"], config, first["sources"], movie=config.primary_movie)

    second = _snapshot(config, first, [_source(config, [_show("10:00"), _show("18:00"), _show("09:00", "2026-12-18")])])
    events, _ = diff_snapshot(state, second["theatres"], config, second["sources"], movie=config.primary_movie)
    types = [e["type"] for e in events]
    assert "show_added" in types
    assert "first_show" in types
    first_show = next(e for e in events if e["type"] == "first_show")
    assert first_show["date"] == "2026-12-18"


def test_blocked_source_preserves_last_snapshot(config):
    first = _snapshot(config, {}, [_source(config, [_show("10:00")])])
    blocked = SourceResult(
        source="district",
        status="blocked",
        message="challenge",
        observations={
            t.id: TheatreObservation(platform="district", theatre_id=t.id, status="blocked", listed=None,
                                     error="HTTP 403 challenge")
            for t in config.theatres
        },
    )
    snap = _snapshot(config, first, [blocked])
    lulu = next(t for t in snap["theatres"] if t["id"] == "lulu-global-mall")
    district_obs = lulu["platforms"]["district"]
    assert district_obs["status"] == "stale"
    assert district_obs["stale"] is True
    assert district_obs["data_age_minutes"] is not None
    assert len(district_obs["shows"]) == 1, "last good shows must be preserved"
    assert snap["status"] == "degraded"

    events, _ = diff_snapshot({}, snap["theatres"], config, snap["sources"], movie=config.primary_movie)
    assert "show_removed" not in [e["type"] for e in events]
    assert "source_blocked" in [e["type"] for e in events]


def test_sold_out_and_seat_drop_are_availability_not_sales(config):
    first = _snapshot(config, {}, [_source(config, [_show("10:00", available=50)])])
    _, state = diff_snapshot({}, first["theatres"], config, first["sources"], movie=config.primary_movie)
    second = _snapshot(config, first, [_source(config, [_show("10:00", available=0)])])
    events, _ = diff_snapshot(state, second["theatres"], config, second["sources"], movie=config.primary_movie)
    sold = [e for e in events if e["type"] == "sold_out"]
    assert sold, "status change to sold out must be detected"
    assert "sold" not in sold[0]["message"].replace("sold out", ""), "never claim confirmed ticket sales"


def test_totals_and_format_separation(config):
    snap = _snapshot(config, {}, [_source(config, [_show("10:00")])])
    totals = snap["totals"]
    assert totals["theatres_monitored"] == 6
    assert totals["theatres_with_listings"] == 1
    assert totals["shows_3d"] == 1
    assert totals["shows_infinity_vision_3d"] == 1
    assert totals["shows_imax_3d"] == 0


def test_layout_dir_used_for_seat_recommendation(config, tmp_path: Path):
    import json

    layout = {"screen": "AUDI 01", "rows": [
        {"row": "A", "seats": [{"number": "1", "x": 0.5, "y": 0.5, "status": "available"}]},
    ]}
    (tmp_path / "lulu-global-mall.json").write_text(json.dumps(layout), encoding="utf-8")
    snap, _, _ = build_snapshot(
        config.primary_movie, config, [_source(config, [_show("10:00")])], {}, iso_ist(), 5, "run",
        layout_dir=tmp_path,
    )
    lulu = next(t for t in snap["theatres"] if t["id"] == "lulu-global-mall")
    assert lulu["best_seats"]["mode"] == "layout"
