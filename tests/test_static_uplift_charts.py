import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delivery_analysis.app.server import create_app

SOURCE = Path(__file__).resolve().parent.parent / "delivery_analysis" / "app" / "static" / "uplift-charts.js"
NODE = shutil.which("node")

GRAPH = {
    "metric": "story_points_done",
    "blocks": [
        {"index": -1, "start": "2026-08-20", "days": 30, "partial": False, "value": 10.0, "median": 12.0, "average": 13.0},
        {"index": 0, "start": "2026-09-19", "days": 30, "partial": False, "value": 46.0, "median": 24.0, "average": 31.0},
        {"index": 1, "start": "2026-10-19", "days": 17, "partial": True, "value": 5.0, "median": 9.0, "average": 11.0},
        {"index": 2, "start": "2026-11-18", "days": 0, "partial": True, "value": None, "median": None, "average": None},
    ],
    "person": {"before": {"median": 10.0, "average": 10.5}, "after": {"median": 25.0, "average": 25.5}},
    "everyone": {"before": {"median": 12.0, "average": 13.0}, "after": {"median": 15.0, "average": 16.0}},
    "short_baseline": False,
}

HARNESS = """
const fs = require("fs");
global.window = { DA: {}, Chart: function (canvas, config) { this.config = config; this.destroy = function () {}; } };
global.document = { body: {} };
global.getComputedStyle = function () { return { getPropertyValue: function () { return ""; } }; };
eval(fs.readFileSync(process.argv[1], "utf8"));
const input = JSON.parse(process.argv[2]);
const canvas = { setAttribute: function () {}, parentNode: {} };
const chart = window.DA.upliftChart(canvas, input.graph, input.options);
const calls = [];
const ctx = new Proxy({}, { get: function (t, k) {
  return (k === "save" || k === "restore") ? function () {} : function (...a) { calls.push([k, a]); };
}, set: function () { return true; } });
const scales = { x: { getPixelForValue: function (i) { return 100 + 50 * i; } } };
const plugin = chart.config.plugins[0];
plugin.beforeDatasetsDraw({ scales: scales, chartArea: { top: 0, bottom: 100, left: 75, right: 325 }, ctx: ctx },
  {}, chart.config.options.plugins.upliftDayZero);
console.log(JSON.stringify({ datasets: chart.config.data.datasets, labels: chart.config.data.labels, calls: calls }));
"""


def run(graph, options):
    out = subprocess.run([NODE, "-e", HARNESS, str(SOURCE), json.dumps({"graph": graph, "options": options})],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_served(tmp_path):
    client = TestClient(create_app(tmp_path / "d.sqlite"), base_url="http://127.0.0.1")
    response = client.get("/static/uplift-charts.js")
    assert response.status_code == 200
    assert "DA.upliftChart" in response.text


def test_no_math_on_values():
    text = SOURCE.read_text(encoding="utf-8")
    assert "reduce(" not in text
    assert "Math." not in text


def test_text_is_drawn_not_injected():
    assert "innerHTML" not in SOURCE.read_text(encoding="utf-8")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_datasets_and_colours():
    out = run(GRAPH, {"threshold": 0.7})
    sets = out["datasets"]
    assert [d["label"] for d in sets] == ["person", "median", "average", "before median", "before average",
                                          "after median", "after average", "threshold"]
    assert sets[0]["backgroundColor"] == ["#9a998f", "#1baf7a", "#2a78d6", "#2a78d6"]
    assert sets[0]["data"] == [10.0, 46.0, 5.0, None]
    assert sets[3]["data"] == [10.0, None, None, None]
    assert sets[5]["data"] == [None, 25.0, 25.0, 25.0]
    assert sets[7]["data"] == [0.7] * 4
    assert out["labels"][2] == "2026-10-19 (running)"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_threshold_is_optional_and_empty_graph_draws():
    assert len(run(GRAPH, {})["datasets"]) == 7
    empty = run({"blocks": [], "person": {}}, None)
    assert empty["labels"] == [] and empty["calls"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_day_zero_line_sits_between_the_last_before_block_and_block_zero():
    calls = run(GRAPH, {})["calls"]
    assert [a for k, a in calls if k == "moveTo"] == [[125, 0]]  # block 0 is at x=150, half a 50px step left
    assert [a[0] for k, a in calls if k == "fillText"] == ["Days 1-30", "Days 31-60", "Days 61-90", "Day 0"]


def test_median_colour_comes_from_the_theme_for_line_and_legend_key():
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count('"#111111"') == 1  # only the fallback inside token(...)
    assert 'token("--text-primary", "#111111")' in text
    assert 'line("median", blocks.map(function (b) { return b.median; }), medianInk(),' in text
    assert "(key.line || medianInk())" in text


def test_chart_legend_is_off_and_shared_legend_exists():
    text = SOURCE.read_text(encoding="utf-8")
    assert "legend: { display: false }" in text
    assert "DA.upliftLegend" in text


LEGEND_HARNESS = """
const fs = require("fs");
function mk(tag) { return { tag: tag, children: [], attrs: {}, classes: [], textContent: "",
  setAttribute: function (k, v) { this.attrs[k] = v; }, appendChild: function (c) { this.children.push(c); },
  classList: { add: function (c) { box.classes.push(c); } } }; }
global.window = { DA: {} };
global.document = { body: {} };
global.getComputedStyle = function () { return { getPropertyValue: function () { return ""; } }; };
const box = mk("p");
box.classList = { add: function (c) { box.classes.push(c); } };
window.DA.el = function (tag, attrs, children) {
  const n = mk(tag); Object.keys(attrs || {}).forEach(function (k) { if (k === "text") { n.textContent = attrs[k]; } else { n.attrs[k] = attrs[k]; } });
  (children || []).forEach(function (c) { n.children.push(c); }); return n; };
eval(fs.readFileSync(process.argv[1], "utf8"));
const names = function () { return box.children.map(function (c) { return c.children[1].textContent; }); };
window.DA.upliftLegend(box);
const plain = names();
box.children = [];
window.DA.upliftLegend(box, "Core");
console.log(JSON.stringify({ classes: box.classes, labels: plain, named: names() }));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_shared_legend_has_eight_items():
    out = subprocess.run([NODE, "-e", LEGEND_HARNESS, str(SOURCE)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert len(data["labels"]) == 8 and data["labels"][0] == "Person, before Day 0"
    assert "uplift-legend" in data["classes"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_shared_legend_names_the_comparison_group():
    out = subprocess.run([NODE, "-e", LEGEND_HARNESS, str(SOURCE)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert "Median of everyone that month" in data["labels"] and "Average of everyone that month" in data["labels"]
    assert "Median of Core that month" in data["named"] and "Average of Core that month" in data["named"]
