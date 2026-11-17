from doomsday_watch.store import Store


def _snapshot(checked_at: str, shows: int = 0):
    return {
        "schema_version": 1,
        "run_id": checked_at,
        "checked_at": checked_at,
        "status": "ok",
        "totals": {"shows_total": shows},
        "theatres": [],
        "sources": [],
    }


def test_round_trip_and_history(tmp_path):
    store = Store(tmp_path)
    store.write_run(
        snapshot=_snapshot("2026-11-17T10:00:00+05:30", 3),
        state={"version": 1, "theatres": {}},
        meta={"run_status": "ok"},
        events=[{"id": "e1", "type": "first_show", "message": "hi"}],
        sources={"sources": {"district": {"status": "ok"}}},
        retention=(72, 90),
    )
    assert store.load_latest()["totals"]["shows_total"] == 3
    assert store.load_state()["version"] == 1
    assert len(store.events()) == 1
    assert len(store.runs()) == 1
    assert store.runs()[0]["sources"]["district"] == "ok"


def test_append_only_history_accumulates(tmp_path):
    store = Store(tmp_path)
    for hour in ("10", "11", "12"):
        store.write_run(
            snapshot=_snapshot(f"2026-11-17T{hour}:00:00+05:30"),
            state={}, meta={}, events=[{"id": hour, "type": "show_added", "message": hour}],
            sources={"sources": {}}, retention=(72, 90),
        )
    assert len(store.events()) == 3
    assert len(store.runs()) == 3
    latest = store.load_latest()
    assert latest["checked_at"].startswith("2026-11-17T12")


def test_prune_keeps_hourly_and_daily(tmp_path):
    store = Store(tmp_path)
    for hour in range(0, 23, 2):
        store.write_run(
            snapshot=_snapshot(f"2026-11-17T{hour:02d}:00:00+05:30"),
            state={}, meta={}, events=[], sources={"sources": {}}, retention=(2, 1),
        )
    files = sorted(store.snapshots.glob("*/*/*.json"))
    # retention (2 hourly, 1 daily): newest 2 hourly snapshots exist
    # (22:00 IST == 16:30 UTC, the filename stamp)
    assert len(files) >= 2
    assert any("16-30-00Z" in f.name for f in files)
