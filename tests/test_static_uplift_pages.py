import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "delivery_analysis" / "app" / "static"
PAGES = {"uplift.html": "uplift.js", "uplift-person.html": "uplift-person.js"}


def test_pages_reference_scripts():
    for html, script in PAGES.items():
        text = (STATIC / html).read_text(encoding="utf-8")
        for src in ("vendor/chart.umd.js", "app.js", "uplift-charts.js", "pages/" + script):
            assert "/static/" + src in text, (html, src)
        assert (STATIC / "pages" / script).exists()


def test_cohort_page_does_not_count_blocks():
    text = (STATIC / "pages" / "uplift.js").read_text(encoding="utf-8")
    assert "atOrAbove" not in text
    assert "at_or_above_median" in text


def test_text_content_only():
    for script in PAGES.values():
        text = (STATIC / "pages" / script).read_text(encoding="utf-8")
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", text), script


def test_pages_use_the_shared_legend():
    for script in PAGES.values():
        assert "DA.upliftLegend" in (STATIC / "pages" / script).read_text(encoding="utf-8"), script
    assert 'id="uplift-legend"' in (STATIC / "uplift-person.html").read_text(encoding="utf-8")
    assert "LEGEND" not in (STATIC / "pages" / "uplift.js").read_text(encoding="utf-8")


def test_pages_offer_a_custom_people_checklist():
    for html, script in PAGES.items():
        text = (STATIC / "pages" / script).read_text(encoding="utf-8")
        assert '"/api/people"' in text and "DA.upliftPeoplePicker" in text, script
        assert 'CUSTOM = "people:"' in text and "CUSTOM + ids.join" in text, script
        assert 'id="uplift-people"' in (STATIC / html).read_text(encoding="utf-8"), html
    helper = (STATIC / "uplift-charts.js").read_text(encoding="utf-8")
    assert "DA.upliftPeoplePicker" in helper and "Select all" in helper and "Pick at least 2 people" in helper
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", helper)


def test_pages_request_compare_options_and_pass_compare():
    for script in PAGES.values():
        text = (STATIC / "pages" / script).read_text(encoding="utf-8")
        assert "/api/uplift/compare-options" in text, script
        assert 'DA.setParam("compare"' in text, script
        assert "DA.query({ compare: compare() })" in text, script
        assert 'DA.upliftLegend(document.getElementById("uplift-legend"), label)' in text, script
    for html in PAGES:
        assert 'id="uplift-compare"' in (STATIC / html).read_text(encoding="utf-8"), html
    # the cohort-to-person link and the back link keep the choice
    assert "id: p.person_id, compare: compare()" in (STATIC / "pages" / "uplift.js").read_text(encoding="utf-8")
    assert '"/uplift" + DA.query({ compare: compare() })' in (STATIC / "pages" / "uplift-person.js").read_text(encoding="utf-8")
