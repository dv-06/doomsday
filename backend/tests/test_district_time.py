"""District's showTime is a naive UTC clock; IST conversion happens once."""

import copy

from doomsday_watch.diff import diff_snapshot
from doomsday_watch.models import make_show
from doomsday_watch.sources import district

from test_district import _payload_from_fixture

GT_ID = "1022303"


def _gt_group(payload):
    return next(g for g in payload["groups"] if str(g["data"]["id"]) == GT_ID)


def _session(sid, raw_time):
    return {
        "sid": sid,
        "showTime": raw_time,
        "audi": "SCREEN 5",
        "scrnFmt": "MS INFINITY VISION 3D",
        "total": 229,
        "avail": 224,
        "seatStatus": "Available",
        "areas": [],
    }


def _gt_payload(fixture_html, sessions):
    payload = copy.deepcopy(_payload_from_fixture(fixture_html))
    group = _gt_group(payload)
    group["sessions"] = sessions
    group["available_dates"] = sorted({s["showTime"][:10] for s in sessions})
    return payload


def test_district_raw_clock_is_utc_and_converts_once():
    assert district.display_datetime("2026-12-17T06:15").strftime("%H:%M") == "11:45"
    assert district.display_datetime("2026-12-17T06:15Z").strftime("%H:%M") == "11:45"
    # An explicit offset must be honoured, not shifted again.
    assert district.display_datetime("2026-12-17T06:15:00+05:30").strftime("%H:%M") == "06:15"


def test_four_pvr_sessions_are_ist(config, fixture_html):
    sessions = [
        _session("26534", "2026-12-17T06:15"),
        _session("26535", "2026-12-17T09:40"),
        _session("26536", "2026-12-17T13:05"),
        _session("26537", "2026-12-17T16:30"),
    ]
    source = district.result_from_payload(config, _gt_payload(fixture_html, sessions))
    gt = source.observations["gt-world-mall"]
    assert [s["start"] for s in gt.shows] == ["11:45", "15:10", "18:35", "22:00"]
    assert [s["date"] for s in gt.shows] == ["2026-12-17"] * 4
    assert [s["source_time"] for s in gt.shows] == [s["showTime"] for s in sessions]
    assert gt.shows[0]["start_iso"] == "2026-12-17T11:45:00+05:30"


def test_ist_midnight_and_date_boundaries(config, fixture_html):
    sessions = [
        _session("b1", "2026-12-16T18:30"),   # 17 Dec 00:00 IST
        _session("b2", "2026-12-17T18:29"),   # 17 Dec 23:59 IST
        _session("b3", "2026-12-17T18:30"),   # 18 Dec 00:00 IST
        _session("b4", "2026-12-18T18:29"),   # 18 Dec 23:59 IST
        _session("b5", "2026-12-17T05:29"),   # 17 Dec 10:59 IST
        _session("b6", "2026-12-17T05:30"),   # 17 Dec 11:00 IST
        _session("x1", "2026-12-16T18:29"),   # 16 Dec 23:59 IST — excluded
        _session("x2", "2026-12-18T18:30"),   # 19 Dec 00:00 IST — excluded
    ]
    source = district.result_from_payload(config, _gt_payload(fixture_html, sessions))
    gt = source.observations["gt-world-mall"]
    got = {(s["source_show_id"], s["date"], s["start"]) for s in gt.shows}
    assert got == {
        ("b1", "2026-12-17", "00:00"),
        ("b2", "2026-12-17", "23:59"),
        ("b3", "2026-12-18", "00:00"),
        ("b4", "2026-12-18", "23:59"),
        ("b5", "2026-12-17", "10:59"),
        ("b6", "2026-12-17", "11:00"),
    }
    assert {s["date"] for s in gt.shows} == {"2026-12-17", "2026-12-18"}


def test_time_correction_migrates_identity_without_duplicate_events(config):
    show = make_show(
        platform="district",
        theatre_id="gt-world-mall",
        date="2026-12-17",
        start="11:45",
        screen="SCREEN 5",
        raw_format="MS INFINITY VISION 3D",
        areas=[{"label": "CLASSIC ROWS", "price": 750, "sTotal": 30, "sAvail": 29}],
        total=229,
        available=223,
        raw_status="Available",
        source_show_id="26534",
        source_time="2026-12-17T06:15",
    )
    previous = {
        "theatres": {
            "gt-world-mall": {
                "platforms": {
                    "district": {
                        "listed": True,
                        "available_dates": ["2026-12-17"],
                        "dates": ["2026-12-17"],
                        "shows": {
                            "district|gt-world-mall|2026-12-17|06:15|SCREEN 5|infinity_vision_3d|26534": {
                                "first_seen_at": "2026-11-17T23:00:00+05:30",
                                "date": "2026-12-17",
                                "start": "06:15",
                                "screen": "SCREEN 5",
                                "format_key": "infinity_vision_3d",
                                "status": "bookable",
                                "available_seats": 224,
                                "total_seats": 229,
                                "price_min": 750,
                                "price_max": 1100,
                            }
                        },
                    }
                }
            }
        }
    }
    theatre = {
        "id": "gt-world-mall",
        "name": "GT World Mall",
        "platforms": {
            "district": {
                "status": "ok",
                "listed": True,
                "available_dates": ["2026-12-17"],
                "dates": {"2026-12-17": {"listed": True}},
                "shows": [show],
            }
        },
    }
    events, state = diff_snapshot(
        previous,
        [theatre],
        config,
        [{"source": "district", "status": "ok", "checked_at": "2026-11-18T10:00:00+05:30"}],
    )
    types = [e["type"] for e in events]
    assert "show_added" not in types
    assert "show_removed" not in types
    assert "first_show" not in types
    dropped = next(e for e in events if e["type"] == "seats_dropped")
    assert dropped["start"] == "11:45"
    current = state["theatres"]["gt-world-mall"]["platforms"]["district"]["shows"]
    assert show["id"] in current
    assert current[show["id"]]["first_seen_at"] == "2026-11-17T23:00:00+05:30"
