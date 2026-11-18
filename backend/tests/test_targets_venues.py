"""Date-rule, venue-separation and date-state regressions."""

import copy

import pytest

from doomsday_watch.config import iso_ist
from doomsday_watch.models import SourceResult, TheatreObservation
from doomsday_watch.monitor import build_snapshot
from doomsday_watch.sources import district

from test_multimovie import RAMAYANA_MOVIE, _ramayana_group, _ramayana_payload, _session

EXPECTED = (
    [f"2026-11-{day:02d}" for day in range(19, 31)]
    + ["2026-12-05", "2026-12-06", "2026-12-12", "2026-12-13",
       "2026-12-19", "2026-12-20", "2026-12-26", "2026-12-27"]
)


def test_ramayana_target_dates_are_exact_and_unique(config):
    dates = list(config.movie("ramayana").target_dates)
    assert dates == EXPECTED
    assert len(dates) == len(set(dates)) == 20
    assert "2026-11-18" not in dates


def test_movies_have_separate_venue_lists(config):
    avengers = config.theatres_for(config.movie("avengers-doomsday"))
    ramayana = config.theatres_for(config.movie("ramayana"))
    assert {t.district_id for t in avengers} == {
        "56450", "1022299", "1020725", "1022303", "52080", "1022307",
    }
    assert {t.district_id for t in ramayana} == {
        "7508", "1020740", "1022298", "1022307", "1022297",
        "1022299", "1022305", "1022309",
    }
    assert len(ramayana) == 8
    assert len(avengers) == 6


def _ram_entry(groups):
    payload = _ramayana_payload(iso_ist())
    entry = payload["movies"][0]
    entry["groups"] = groups
    return payload["collected_at"], entry


def test_unknown_explicit_4dx_venue_is_discovered(config):
    new_group = {
        "data": {"id": "999999", "name": "New 4DX Bengaluru Multiplex"},
        "entityUrl": "/movies/new-4dx-bengaluru-CD999999",
        "sessions": [_session("new-1", "2026-11-19T06:10:00")],
    }
    collected, entry = _ram_entry([_ramayana_group(), new_group])
    result = district.result_from_payload(
        config, {**entry, "source": "district", "collected_at": collected},
        movie=config.movie("ramayana"),
    )
    discovered = result.observations["district-999999"]
    assert discovered.status == "ok"
    assert len(discovered.shows) == 1
    assert discovered.shows[0]["format"]["key"] == "4dx_3d"


def test_missing_or_invalid_timestamp_is_rejected(config):
    for session in (
        {**_session("bad-1", "2026-11-19T06:10:00"), "showTime": None},
        {**_session("bad-2", "2026-11-19T06:10:00"), "showTime": "not-a-time"},
    ):
        group = {**_ramayana_group(), "sessions": [session]}
        collected, entry = _ram_entry([group])
        with pytest.raises(district.SourceError):
            district.result_from_payload(
                config, {**entry, "source": "district", "collected_at": collected},
                movie=config.movie("ramayana"),
            )


def test_november_december_boundary_and_midnight(config):
    group = {
        **_ramayana_group(),
        "sessions": [
            _session("b-1", "2026-11-30T18:29:00"),  # 23:59 IST Nov 30
            _session("b-2", "2026-11-30T18:30:00"),  # 00:00 IST Dec 1 -> excluded
            _session("b-3", "2026-12-04T18:30:00"),  # 00:00 IST Dec 5 -> included
        ],
    }
    collected, entry = _ram_entry([group])
    result = district.result_from_payload(
        config, {**entry, "source": "district", "collected_at": collected},
        movie=config.movie("ramayana"),
    )
    shows = result.observations["orion-mall"].shows
    assert [(s["date"], s["start"]) for s in shows] == [
        ("2026-11-30", "23:59"), ("2026-12-05", "00:00"),
    ]
    assert shows[0]["source_time"] == "2026-11-30T18:29:00"
    assert shows[1]["source_time"] == "2026-12-04T18:30:00"


def _source(config, movie, *, status="ok", shows=None, observation_status="ok"):
    observations = {
        theatre.id: TheatreObservation(
            platform="district",
            theatre_id=theatre.id,
            status=observation_status,
            listed=bool(shows) if observation_status == "ok" else None,
            venue={"id": theatre.district_id, "name": theatre.name},
            shows=shows or [],
            error=None if observation_status == "ok" else "request failed",
        )
        for theatre in config.theatres_for(movie)
    }
    return SourceResult(
        source="district", status=status, message="test", movie_id=movie.id,
        checked_at=iso_ist(), observations=observations,
    )


def _snapshot(config, movie, source):
    snap, _, _ = build_snapshot(
        movie, config, [source], {}, iso_ist(), 1, "date-state-test",
    )
    return snap


def test_failed_request_is_not_reported_as_unpublished(config):
    movie = config.movie("ramayana")
    snap = _snapshot(config, movie, _source(config, movie, status="blocked", observation_status="error"))
    assert all(day["state"] == "source_failed" for day in snap["totals"]["dates"].values())


def test_healthy_empty_dates_are_unpublished_not_failed(config):
    movie = config.movie("ramayana")
    snap = _snapshot(config, movie, _source(config, movie))
    assert all(day["state"] == "unpublished" for day in snap["totals"]["dates"].values())
    assert snap["totals"]["theatres_monitored"] == 8


def test_every_unpublished_date_is_retained(config):
    movie = config.movie("ramayana")
    snap = _snapshot(config, movie, _source(config, movie))
    assert list(snap["totals"]["dates"]) == list(movie.target_dates)
