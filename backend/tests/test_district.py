from doomsday_watch.http import FetchResult
from doomsday_watch.sources import district

REGISTRY_HTML = """
<html><body>
<a href="/movies/cinepolis-lulu-global-mall-bengaluru-bengaluru-c/56450" class="x">
  <span class="dds-text-lg dds-font-semibold">Cinepolis Lulu Global Mall, Bengaluru, Bengaluru</span>
  <span class="dds-text-quaternary">11.1 km away</span></a>
<a href="/movies/pvr-orion-mall-dr-rajkumar-road-bengaluru-c/1022299" class="x">
  <span class="dds-text-lg dds-font-semibold">PVR Orion Mall, Dr Rajkumar Road, Bengaluru</span>
  <span class="dds-text-quaternary">12.1 km away</span></a>
<a href="/movies/pvr-gt-world-mall-magadi-road-bengaluru-c/1022303" class="x">
  <span class="dds-text-lg dds-font-semibold">PVR GT World Mall, Magadi Road, Bengaluru</span>
  <span class="dds-text-quaternary">13.3 km away</span></a>
<a href="/movies/cinepolis-orion-avenue-mall-banaswadi-bengaluru-c/925" class="x">
  <span class="dds-text-lg dds-font-semibold">Cinepolis Orion Avenue Mall, Banaswadi, Bengaluru</span>
  <span class="dds-text-quaternary">1.1 km away</span></a>
<a href="/movies/inox-mantri-square-malleshwaram-bengaluru-c/1020725" class="x">
  <span class="dds-text-lg dds-font-semibold">INOX Mantri Square, Malleshwaram, Bengaluru</span>
  <span class="dds-text-quaternary">9.7 km away</span></a>
<a href="/movies/miraj-cinemas-tgn-lotus-elite-sunkadakatte-c/52080" class="x">
  <span class="dds-text-lg dds-font-semibold">Miraj Cinemas: TGN Lotus Elite, Sunkadakatte</span>
  <span class="dds-text-quaternary">20 km away</span></a>
<a href="/movies/pvr-global-mall-mysore-road-bengaluru-c/1022307" class="x">
  <span class="dds-text-lg dds-font-semibold">PVR Global Mall, Mysore Road, Bengaluru</span>
  <span class="dds-text-quaternary">14 km away</span></a>
</body></html>
"""


class FakeClient:
    def __init__(self, fixture_html: str, movie_url: str = "https://www.district.in/movies/avengers-doomsday-movie-tickets-in-bengaluru-MV176735"):
        self.fixture_html = fixture_html
        self.movie_url = movie_url
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        if "doomsday" in url:
            return FetchResult(url=url, status="ok", http_status=200, text=self.fixture_html)
        if "cinemas-in-bengaluru" in url:
            return FetchResult(url=url, status="ok", http_status=200, text=REGISTRY_HTML)
        return FetchResult(url=url, status="http_error", http_status=404, error="HTTP 404")


def test_district_parses_real_page(config, fixture_html, tmp_path):
    result = district.fetch(config, FakeClient(fixture_html), tmp_path)
    assert result.status == "ok"
    assert result.movie["title"] == "Avengers: Doomsday"
    assert result.movie["content_id"] == "176735"
    assert len(result.observations) == len(config.theatres)


def test_target_theatres_resolved_by_id(config, fixture_html, tmp_path):
    result = district.fetch(config, FakeClient(fixture_html), tmp_path)
    lulu = result.observations["lulu-global-mall"]
    orion = result.observations["orion-mall"]
    gt = result.observations["gt-world-mall"]
    mantri = result.observations["mantri-square-mall"]

    assert lulu.status == "ok" and lulu.listed
    assert lulu.venue["id"] == "56450"
    assert orion.venue["id"] == "1022299"
    assert gt.venue["id"] == "1022303"
    assert "PVR Orion Mall" in orion.venue["name"]

    # Lookalike Orion Avenue Mall must never be mapped onto Orion Mall.
    assert "Banaswadi" not in orion.venue["name"]

    # Cinema exists in the public directory but has no sessions in this fixture.
    assert mantri.status == "not_listed"
    assert mantri.listed is False
    assert mantri.venue["verified_name"] is True


def test_shows_are_real_and_dated(config, fixture_html, tmp_path):
    result = district.fetch(config, FakeClient(fixture_html), tmp_path)
    shows = result.observations["lulu-global-mall"].shows
    assert shows, "expected sessions on the target date"
    first = shows[0]
    assert first["date"] in config.target_dates
    assert first["start"] == "01:00"
    assert first["screen"] == "MACRO XE"
    assert first["format"]["key"] == "infinity_vision_3d"
    assert first["format"]["label"] == "Infinity Vision 3D"
    assert first["price"]["min"] and first["price"]["currency"] == "INR"
    assert "seat-layout" in first["booking_url"]
    assert first["availability"]["total_seats"] > 0
    assert isinstance(first["availability"]["areas"], list) and first["availability"]["areas"]
    for show in shows:
        assert show["date"] != "2026-12-18", "fixture has no Dec 18 sessions; parser must not invent them"


def test_id_mismatch_is_reported_not_guessed(config, fixture_html, tmp_path, monkeypatch):
    import copy

    broken = copy.deepcopy(config)
    # Point Lulu at a bogus id; adapter must not find it and must not guess.
    theatre = broken.theatres[0]
    object.__setattr__(theatre, "district_id", "999999")
    result = district.fetch(broken, FakeClient(fixture_html), tmp_path)
    obs = result.observations[theatre.id]
    assert obs.status == "not_listed"
    assert obs.listed is False
    assert obs.shows == []
