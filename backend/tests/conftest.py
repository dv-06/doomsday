import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def config(repo_root: Path):
    from doomsday_watch.config import load_config

    return load_config(repo_root / "config" / "monitor.json")


@pytest.fixture(scope="session")
def fixture_html(repo_root: Path) -> str:
    return (repo_root / "backend" / "tests" / "fixtures" / "district_movie_page.html").read_text(encoding="utf-8")
