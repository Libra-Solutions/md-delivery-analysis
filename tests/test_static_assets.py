import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "delivery_analysis" / "app" / "static"
PAGE_FILES = sorted(p for p in STATIC.glob("*.html") if p.name != "index.html")
NAV_LABELS = ["Dashboard", "Rankings", "People", "Selection", "Teams", "Sources", "Settings", "Ask", "QA"]
API_ROOTS = {"teams", "metrics", "people", "repos", "sources", "refresh", "settings", "identities", "health", "tickets", "person", "qa"}
OWN_FILES = [p for p in STATIC.rglob("*") if p.suffix in (".html", ".js", ".css") and "vendor" not in p.parts]


def references(html):
    return re.findall(r'(?:src|href)="([^"]+)"', html)


def test_chart_js_is_vendored():
    vendored = (STATIC / "vendor" / "chart.umd.js").read_text(encoding="utf-8", errors="replace")
    assert "Chart.js v4" in vendored[:400]


@pytest.mark.parametrize("page", PAGE_FILES, ids=lambda p: p.name)
def test_every_page_has_the_nav_shared_assets_and_only_local_references(page):
    html = page.read_text(encoding="utf-8")
    for label in NAV_LABELS:
        assert f">{label}</a>" in html
    for needed in ('id="header"', 'id="content"', "/static/style.css", "/static/app.js"):
        assert needed in html
    script = f"/static/pages/{page.stem}.js"
    assert script in html
    for ref in references(html):
        assert ref.startswith("/"), ref
        if ref.startswith("/static/"):
            assert (STATIC / ref[len("/static/"):]).is_file(), ref


@pytest.mark.parametrize("page", PAGE_FILES, ids=lambda p: p.name)
def test_page_scripts_only_use_ids_their_page_has(page):
    html = page.read_text(encoding="utf-8")
    script = (STATIC / "pages" / f"{page.stem}.js").read_text(encoding="utf-8")
    for element_id in re.findall(r'getElementById\("([^"]+)"\)', script):
        assert f'id="{element_id}"' in html, f"{page.stem}.js uses #{element_id}"


@pytest.mark.parametrize("path", OWN_FILES, ids=lambda p: p.name)
def test_no_file_reaches_the_internet_and_api_calls_match_the_contract(path):
    text = path.read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    for root in re.findall(r'"/api/([a-z_]+)', text):
        assert root in API_ROOTS, f"{path.name} calls /api/{root}"


def test_charts_pages_load_chart_js_before_app_scripts():
    for name in ("dashboard.html", "person.html"):
        html = (STATIC / name).read_text(encoding="utf-8")
        assert html.index("/static/vendor/chart.umd.js") < html.index("/static/charts.js")


def read(*parts):
    return STATIC.joinpath(*parts).read_text(encoding="utf-8")


def test_series_two_and_three_exist_in_both_colour_modes_with_the_reference_palette():
    light, _, dark = read("style.css").partition("@media (prefers-color-scheme: dark)")
    for name, value in (("--series-2", "#eb6834"), ("--series-3", "#1baf7a")):
        assert f"{name}: {value};" in light
    for name, value in (("--series-2", "#d95926"), ("--series-3", "#199e70")):
        assert f"{name}: {value};" in dark
    assert ".chart.small" in read("style.css")


def test_charts_js_exposes_series_and_scatter_with_legend_and_axis_titles():
    text = read("charts.js")
    assert "series: function" in text and "scatter: function" in text
    assert "datasets.length > 1" in text  # a legend only when there are two or more series
    assert 'token("--series-" + ' in text
    assert "title: { display: true" in text  # scatter axes are labelled
    assert "yAxisID" not in text and 'position: "right"' not in text  # no dual axis


def test_dashboard_cards_come_in_the_planned_order():
    script = read("pages", "dashboard.js")
    render = script[script.index("DA.page("):]
    calls = ["impact(cards)", "whereItWent(cards)", "howFast(cards)", "evidence(cards)", "impactPerToken(cards)",
             "costVsPoints(cards)", "askVsGenerate(cards)", "throughput(cards)", "timeToMerge(cards)",
             "breakdown(cards)"]
    positions = [render.index(call) for call in calls]
    assert positions == sorted(positions)
    assert render.index('"review_load"') > positions[-1]


def test_dashboard_reads_every_impact_metric_by_name():
    script = read("pages", "dashboard.js")
    for name in ("story_points_weekly", "story_points_done", "points_by_type", "cycle_time_weekly", "cycle_time_summary",
                 "prs_linked_weekly", "prs_with_issue_link", "story_points_per_dollar",
                 "ask_generate_ratio", "issues_done_weekly", "prs_merged_weekly"):
        assert f'"{name}"' in script, name


def test_the_impact_tile_reads_the_servers_trend_and_computes_nothing_in_the_browser():
    script = read("pages", "dashboard.js")
    assert 'sum(weekly.rows, "issues")' in script and 'sum(weekly.rows, "unpointed")' in script
    assert "done.team.trend" in script and "done.team.previous" in script
    block = script[script.index("function impact"):]
    block = block[: block.index("function whereItWent")]
    assert "before" not in block and ".previous ||" not in block and "mapped" not in block
    assert "Median to first PR merge" in script and "pr_median" in script and "credited to the authors" in script


def test_the_waiting_list_skips_metrics_that_already_have_a_card():
    script = read("pages", "dashboard.js")
    assert "ON_CARDS" in script and "ON_CARDS.indexOf(m.name)" in script


def test_cost_based_cards_use_the_friendly_waiting_message():
    app = read("app.js")
    assert "Claude usage" in app and "DA.sourceLabel" in app
    assert "points_per_usd" in app


def test_the_ask_card_is_context_not_a_ranking():
    script = read("pages", "dashboard.js")
    assert "Context only" in script
    block = script[script.index("function askVsGenerate"):]
    block = block[: block.index("function throughput")]
    assert "rank" not in block


def test_person_page_has_points_cycle_time_and_completed_issues():
    script = read("pages", "person.js")
    html = read("person.html")
    for name in ("story_points_done", "cycle_time", "issues_done"):
        assert f'"{name}"' in script, name
    assert "d.issues_done" in script and "i.basis" in script and "i.share" in script
    assert 'id="person-issues"' in html and 'id="person-issues-card"' in html
    assert "hidden" in html.split('id="person-issues-card"')[0].split("<section")[-1]


def test_formats_know_the_ratio_to_usd_units():
    app = read("app.js")
    assert 'unit === "points_per_usd"' in app and 'unit === "multiple"' in app


def test_rankings_shows_confidence_and_the_unranked_reason():
    script = read("pages", "rankings.js")
    assert '"Confidence"' in script and "row.confidence" in script
    assert "row.unranked_reason" in script and "(unranked: " in script


def test_person_page_lists_tickets_with_claude_cost_from_the_api():
    script = read("pages", "person.js")
    html = read("person.html")
    assert 'id="person-tickets"' in html
    assert '"/api/tickets"' in script and "t.cost_weekly" in script and "x.points_per_usd" in script
    assert '"cost_spent"' in script and '"story_points_per_dollar"' in script


def test_dashboard_impact_per_token_cards_read_the_api_and_compute_nothing():
    script = read("pages", "dashboard.js")
    for name in ("story_points_per_dollar_weekly", "story_points_per_dollar_all_in", "unattributed_cost_share",
                 "cost_by_purpose_weekly"):
        assert f'"{name}"' in script, name
        assert f'"{name}"' in script[: script.index("function waiting")] and name in script[script.index("ON_CARDS"):script.index("function load")]
    assert "x.denominator" in script and "x.numerator" in script and "confidence" in script
    block = script[script.index("function impactPerToken"):script.index("function throughput")]
    assert "reduce(" not in block and " / " not in block and "sum(" not in block
    assert 'type: "line"' in block and "stacked: true" in block


def test_people_page_has_the_expected_ids_and_scripts():
    html = read("people.html")
    assert "<title>People · Delivery Analytics</title>" in html
    assert "<h2>People</h2>" in html
    assert 'id="include-inactive"' in html and 'id="people-matrix"' in html
    assert "/static/pages/people.js" in html and "chart.umd.js" not in html
    assert ("Impact is story points of completed tickets, split between the people whose code delivered them "
            "(Delivery) and whose reviews helped (Participation). Click a column to sort; click a name for the "
            "work behind the numbers.") in html


NAV = (
    '<a href="/">Dashboard</a>\n    <a href="/person">People</a>\n    <a href="/rankings">Rankings</a>\n'
    '    <a href="/qa">QA</a>\n'
    '    <a href="/ask">Ask</a>\n    <h2 class="nav-group">Set up</h2>\n    <a href="/selection">Selection</a>\n'
    '    <a href="/teams">Teams</a>\n    <a href="/sources">Sources</a>\n    <a href="/settings">Settings</a>'
)


def test_every_nav_leads_with_the_analysis_pages_and_groups_the_setup_pages():
    for page in PAGE_FILES:
        assert NAV in page.read_text(encoding="utf-8"), page.name


def test_the_person_page_lights_up_people_in_the_nav():
    script = read("app.js")
    assert 'base === "/person" && window.location.pathname === "/people"' in script  # the matrix is part of People
    assert 'base === "/rankings"' not in script


def test_the_person_page_has_a_dropdown_to_change_the_person():
    html, script, css = read("person.html"), read("pages", "person.js"), read("style.css")
    assert 'for="person-picker">Person</label>' in html and 'id="person-picker"' in html
    assert 'href="/people"' in html.split('id="person-picker"')[1].split("</div>")[0]  # a way back to everyone
    assert '"/api/people"' in script and "person-picker" in script
    assert '"/person" + DA.query({ id:' in script  # picking someone opens their page, keeping team and window
    assert ".nav-group" in css


def test_people_js_reads_only_fields_from_the_contract():
    script = read("pages", "people.js")
    assert '"/api/people-matrix"' in script and "DA.page(" in script
    allowed = {"window", "columns", "rows", "notes", "person_id", "name", "cells", "label", "unit", "better",
               "description", "needs", "status", "missing", "value", "sample", "ranked", "rank", "confidence",
               "start", "end", "days", "length", "sort", "dir", "inactive", "id", "team", "group", "reason"}
    for field in re.findall(r"\b(?:r|data|row|c|col|column|cell)\.([a-z_]+)", script):
        assert field in allowed or field in {"push", "map", "filter", "slice", "sort", "forEach", "find", "join",
                                             "reverse", "checked", "value", "textContent", "appendChild"}, field
    for field in ("status", "ranked", "better", "description", "sample", "missing", "person_id", "cells"):
        assert field in script


def test_people_js_computes_no_numbers():
    script = read("pages", "people.js")
    for banned in ("reduce(", "sum(", "Math.", "average", "mean(", "+="):
        assert banned not in script, banned


def test_people_js_defaults_to_impact_points_descending():
    script = read("pages", "people.js")
    assert 'params.get("sort") || "impact_points"' in script


def test_people_js_renders_a_grouped_header_with_impact_delivery_participation():
    script = read("pages", "people.js")
    for label in ('"Impact"', '"Delivery"', '"Participation"'):
        assert label in script, label
    assert "colspan" in script and "group" in script
    assert "group-start" in script and "group-impact" in script
    css = read("style.css")
    assert ".group-impact" in css and ".group-start" in css


def test_people_js_explains_blank_cells_and_shows_the_claude_cost_column():
    script, css = read("pages", "people.js"), read("style.css")
    assert "cell.reason" in script and "cell-reason" in script and "title:" in script
    assert '"cost_spent"' in script and "col.group" in script  # the group comes from the API, with a fallback
    assert '"impact_per_dollar"' in script  # fallback group mapping keeps the cost column inside Impact
    assert ".cell-reason" in css


def test_rankings_defaults_to_impact_points_and_groups_the_picker():
    script = read("pages", "rankings.js")
    assert 's.metric || "impact_points"' in script and '"prs_merged"' not in script
    assert "optgroup" in script and '"Activity (context)"' in script
    order = [script.index(label) for label in ('"Impact"', '"Delivery"', '"Participation"', '"Activity (context)"')]
    assert order == sorted(order)


def test_person_page_keeps_the_work_section_for_the_raw_lists():
    assert "The work behind the numbers" in read("person.html")


PERSON_CHARTS = ["impact", "impact_per_dollar", "split", "delivery", "delivery_speed", "durability",
                 "participation", "prs_reviewed", "review_value"]


def test_person_page_loads_the_shared_chart_script_into_a_mount_point():
    html, script = read("person.html"), read("pages", "person.js")
    assert 'id="person-charts"' in html
    assert html.index("/static/charts.js") < html.index("/static/person-charts.js") < html.index("/static/pages/person.js")
    assert "PersonCharts.mount(" in script and "PersonCharts.load(" in script
    assert "new window.Chart" not in script and "borderDash" not in script  # chart code lives only in person-charts.js
    assert "<summary>Show the tickets and PRs</summary>" in html and 'id="person-top"' not in html


def test_person_charts_script_builds_a_canvas_per_chart_and_the_controls():
    script = read("person-charts.js")
    assert "window.PersonCharts" in script
    for name in ("mount", "load", "clear", "csvUrl"):
        assert f"{name}: {name}" in script
    for key in PERSON_CHARTS:
        assert f'"{key}"' in script, key
    assert '"chart-" + key' in script and '"empty-" + key' in script
    assert '"/api/person/"' in script and "/series?" in script
    assert 'id: "person-window"' in script and "window_days" in script
    assert "Loading…" in script
    assert "Download CSV" in script and 'id: "download-csv"' in script and "export.csv" in script
    assert "Waiting for Claude usage data" in script and "No data yet" in script
    assert "borderDash" in script  # the team median is dashed
    assert "fan-in" not in script.lower()


def test_person_charts_script_has_a_title_and_one_caption_per_chart():
    script = read("person-charts.js")
    cards = re.findall(r'\["([a-z_]+)", "([^"]+)", "([^"]+)"\]', script[: script.index("const KEYS")])
    assert [key for key, _, _ in cards] == PERSON_CHARTS
    assert all(title.strip() and caption.strip().endswith(".") for _, title, caption in cards)


def test_person_charts_script_applies_the_team_choice_as_soon_as_a_box_is_ticked():
    script, css = read("person-charts.js"), read("style.css")
    assert '"/api/teams/"' in script and "/comparison" in script and 'method: "PUT"' in script
    assert 'id: "compare-group"' in script and 'type: "checkbox"' in script
    assert 'addEventListener("change"' in script and "setTimeout(" in script  # applies on tick, debounced
    assert "Updating the median in a moment" in script  # feedback while the pause runs
    assert "GROUP_DELAY_MS = 1000" in script and "}, GROUP_DELAY_MS);" in script  # one update per second at most
    for label in ("Select all", "Clear", "Who counts as the team?"):
        assert label in script, label
    assert '"Save"' not in script and "Use the whole team" not in script  # nothing to remember to click
    assert "person_ids: ids" in script and "ids.length === all.length ? null : ids" in script  # all ticked: whole team
    assert "Everyone's median" in script and "Selected people's median" in script
    assert ".compare-group" in css and ".compare-people" in css


def test_people_in_the_nav_opens_the_person_view_on_someone_by_default():
    script, html = read("pages", "person.js"), read("person.html")
    assert 'window.location.replace("/person" + DA.query({ id:' in script  # no id: jump to a person
    assert "localStorage" in script and "da.person" in script  # the last person viewed comes first
    assert 'id="all-people" href="/people"' in html  # the matrix is one click away


def test_person_page_shows_a_headline_strip_and_explains_a_blank_impact_per_dollar():
    script, css = read("person-charts.js"), read("style.css")
    assert 'id: "series-summary"' in script and "d.summary" in script and "window_days" in script
    assert "Last " in script and "Claude cost" in script and "team median" in script
    assert "impact_per_dollar" in script and "team_median_impact_per_dollar" in script and "claude_cost" in script
    assert "No Claude cost is linked to this person yet, so Impact per dollar is blank." in script
    assert "link their Claude email on the" in script and 'href: "/teams"' in script and "Teams screen" in script
    assert "Waiting for Claude usage data." in script
    assert "Loading…" in script.split("function load(")[1]
    assert ".series-summary" in css


def test_the_qa_page_loads_charts_and_shows_no_people():
    html, script = read("qa.html"), read("pages", "qa.js")
    assert "<title>QA · Delivery Analytics</title>" in html and "<h2>QA</h2>" in html
    assert html.index("/static/vendor/chart.umd.js") < html.index("/static/charts.js") < html.index("/static/pages/qa.js")
    assert '"/api/qa"' in script and "person" not in script
