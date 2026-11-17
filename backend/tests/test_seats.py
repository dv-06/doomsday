from doomsday_watch.seats import (
    build_recommendation,
    heuristic_recommendation,
    recommend_from_layout,
)

LAYOUT = {
    "screen": "AUDI 01",
    "rows": [
        {"row": row, "seats": [
            {"number": str(n), "x": (n - 1) / 11, "y": index_row / 9, "status": "available"}
            for n in range(1, 13)
        ]}
        for index_row, row in enumerate(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
    ],
}


def test_layout_best_seats_are_central_and_mid_rear():
    rec = recommend_from_layout(LAYOUT, "infinity_vision_3d")
    assert rec["mode"] == "layout"
    best = rec["best"]
    assert len(best) == 6
    for seat in best:
        assert 0.35 <= seat["x"] <= 0.65, "best seats must be near the screen's horizontal centre"
        assert seat["y"] >= 0.55, "best seats must not be in the front rows"
        assert seat["reasons"], "every recommendation needs an explanation"
    assert best[0]["y"] >= 0.55
    assert best[0]["row"] not in {"A", "B"}


def test_layout_avoid_catches_extremes():
    rec = recommend_from_layout(LAYOUT, "imax_3d")
    worst = rec["avoid"][0]
    is_edge_or_front = worst["x"] < 0.2 or worst["x"] > 0.8 or worst["y"] < 0.2
    assert is_edge_or_front


def test_unavailable_seats_never_recommended():
    layout = {
        "rows": [
            {"row": "A", "seats": [{"number": "1", "x": 0.5, "y": 0.6, "status": "sold"}]},
            {"row": "B", "seats": [{"number": "1", "x": 0.5, "y": 0.7, "status": "available"}]},
        ]
    }
    rec = recommend_from_layout(layout, "3d")
    assert [s["row"] for s in rec["best"]] == ["B"]
    assert rec["available_seats"] == 1


def _show(areas):
    return {
        "id": "s1",
        "start_iso": "2026-12-17T10:00:00+05:30",
        "start": "10:00",
        "date": "2026-12-17",
        "screen": "AUDI 03",
        "format": {"key": "infinity_vision_3d", "label": "Infinity Vision 3D"},
        "availability": {"areas": areas, "available_seats": 40, "total_seats": 100, "status": "bookable"},
        "price": {"min": 500, "max": 900},
    }


def test_heuristic_is_labelled_and_uses_real_areas():
    show = _show([
        {"label": "CLASSIC ROWS", "price": 500, "total_seats": 80, "available_seats": 40, "status": "bookable"},
        {"label": "RECLINER ROWS", "price": 900, "total_seats": 20, "available_seats": 5, "status": "few_left"},
        {"label": "PREMIUM PLUS", "price": 700, "total_seats": 30, "available_seats": 0, "status": "sold_out"},
    ])
    rec = heuristic_recommendation([show], "lulu-global-mall")
    assert rec["mode"] == "heuristic"
    assert "heuristic" in rec["disclaimer"].lower()
    assert rec["best"][0]["area"] in {"CLASSIC ROWS", "RECLINER ROWS"}
    assert any(item["area"] == "PREMIUM PLUS" for item in rec["avoid"])
    assert rec["target_zone"]["depth_percent"] == [58, 74]
    # zone recommendation must not invent seat numbers
    assert not any("number" in item for item in rec["best"])


def test_no_areas_means_no_fake_recommendation():
    assert heuristic_recommendation([], "x") is None
    assert heuristic_recommendation([_show([])], "x") is None


def test_build_recommendation_uses_layout_file(tmp_path):
    import json

    (tmp_path / "lulu-global-mall.json").write_text(json.dumps(LAYOUT), encoding="utf-8")
    rec = build_recommendation("lulu-global-mall", [_show([])], tmp_path)
    assert rec["mode"] == "layout"
    assert rec["layout_file"] == "lulu-global-mall.json"
