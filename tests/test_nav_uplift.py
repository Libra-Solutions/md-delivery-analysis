from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "delivery_analysis" / "app" / "static"

PAGES = [
    "dashboard.html",
    "people.html",
    "person.html",
    "rankings.html",
    "ask.html",
    "selection.html",
    "teams.html",
    "sources.html",
    "settings.html",
]

PEOPLE_LINK = '    <a href="/person">People</a>'
UPLIFT_LINK = '    <a href="/uplift">AI uplift</a>'


@pytest.mark.parametrize("page", PAGES)
def test_nav_link(page):
    lines = (STATIC / page).read_text(encoding="utf-8").splitlines()
    index = lines.index(PEOPLE_LINK)
    assert lines[index + 1] == UPLIFT_LINK


def test_readme_section():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## AI uplift dashboard" in text
    assert "cohort set" in text
    assert "backfill --days 450" in text
    assert "/uplift" in text
