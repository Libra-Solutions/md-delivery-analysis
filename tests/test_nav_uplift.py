from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_section():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## AI uplift dashboard" in text
    assert "cohort set" in text
    assert "backfill --days 450" in text
    assert "/uplift" in text
