/* Shared person chart area: rolling-window selector, CSV link, chart cards and notes.
   Usage: PersonCharts.mount(container); PersonCharts.load(personId); PersonCharts.csvUrl(personId); PersonCharts.clear(). */
(function () {
  "use strict";
  const DA = window.DA;
  const ROWS = [
    ["one", [
      ["weekly_points", "Story points per week", "Plain story points for tickets delivered each calendar week (Dev1/Dev2 credit, no weighting or deductions). The current week is still running."],
    ]],
    ["one", [
      ["impact", "Impact", "Story points of finished tickets, weighted by how central the changed files are; delivery plus reviewing."],
    ]],
    ["two", [
      ["impact_per_dollar", "Impact per dollar", "Impact points for each dollar of Claude usage."],
      ["split", "Delivery and participation", "How the latest window splits between doing the work and helping others get it right, against the team median."],
    ]],
    ["three", [
      ["delivery", "Delivery points", "Points earned as the owner of the pull request, less a small deduction for each review comment that had to be fixed."],
      ["delivery_speed", "Delivery speed", "Hours from a ticket starting to its first pull request merging. Lower is better."],
      ["durability", "Durability", "Share of delivered points on tickets that were never reopened."],
    ]],
    ["three", [
      ["participation", "Participation points", "Points earned when a review comment led to a change in the code."],
      ["prs_reviewed", "PRs reviewed", "Pull requests from other people where a comment was left."],
      ["review_value", "Review value", "Comments left on other people's pull requests, plus half a point for each approval."],
    ]],
  ];
  const KEYS = [];
  ROWS.forEach(function (row) { row[1].forEach(function (card) { KEYS.push(card[0]); }); });

  const charts = {};
  let medianName = "Team median";
  let groupTeam = null;
  let fallbackTeam = null; // promise of the first team's id, used when the Team picker is on "All repositories"
  let groupTimer = 0;
  const GROUP_DELAY_MS = 1000; // wait this long after the last tick before recalculating
  let root = null;
  let personId = "";
  let sequence = 0;

  function token(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  function hasValues(values) { return values.some(function (v) { return v !== null && v !== undefined; }); }

  function empty(key, text) {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
    const note = document.getElementById("empty-" + key);
    note.textContent = text;
    note.classList.toggle("hidden", !text);
    document.getElementById("chart-" + key).parentNode.classList.toggle("hidden", !!text);
    return !!text;
  }

  function draw(key, config) {
    if (empty(key, "")) { return; }
    if (typeof window.Chart === "undefined") { empty(key, "Charts are unavailable because Chart.js did not load."); return; }
    charts[key] = new window.Chart(document.getElementById("chart-" + key), config);
  }

  function axes(stacked, horizontal) {
    const grid = token("--grid");
    const ink = token("--text-secondary");
    return {
      x: { stacked: stacked, beginAtZero: true, grid: { color: horizontal ? grid : "transparent" }, ticks: { color: ink } },
      y: { stacked: stacked, beginAtZero: true, grid: { color: horizontal ? "transparent" : grid }, ticks: { color: ink } },
    };
  }

  function medianLine(values) {
    return { type: "line", label: medianName, data: values, borderColor: token("--text-muted"), backgroundColor: token("--text-muted"),
             borderDash: [6, 4], borderWidth: 2, pointRadius: 0, tension: 0.2, spanGaps: false, order: 0 };
  }

  // Plain weekly story points from /weekly-points, with the group's median and average.
  function weeklyChart(d) {
    if (!d.points.some(function (v) { return v; }) && !d.median.some(function (v) { return v; })) { empty("weekly_points", "No delivered points in these weeks"); return; }
    const labels = d.weeks.map(function (w) { return w === d.running ? w + " (running)" : w; });
    const average = { type: "line", label: medianName.replace("median", "average"), data: d.average, borderColor: token("--series-2"),
                      backgroundColor: token("--series-2"), borderDash: [2, 3], borderWidth: 2, pointRadius: 0, tension: 0.2, order: 0 };
    draw("weekly_points", { type: "bar", data: { labels: labels, datasets: [
      { label: "Story points", data: d.points, backgroundColor: token("--series-1"), borderRadius: 3, order: 1 },
      medianLine(d.median), average,
    ] }, options: options(false, false) });
  }

  function options(stacked, horizontal) {
    return { responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
             plugins: { legend: { display: true, labels: { color: token("--text-secondary") } }, tooltip: { enabled: true } },
             scales: axes(stacked, horizontal) };
  }

  function lineChart(d, key, label, noData) {
    if (!hasValues(d.series[key])) { empty(key, noData || "No data yet"); return; }
    const colour = token("--series-1");
    draw(key, { type: "line", data: { labels: d.dates, datasets: [
      { label: label, data: d.series[key], borderColor: colour, backgroundColor: colour, borderWidth: 2, pointRadius: 2, tension: 0.2, spanGaps: false },
      medianLine(d.team_median[key]),
    ] }, options: options(false, false) });
  }

  function impactChart(d) {
    if (!hasValues(d.series.delivery) && !hasValues(d.series.participation)) { empty("impact", "No data yet"); return; }
    draw("impact", { type: "bar", data: { labels: d.dates, datasets: [
      { label: "Delivery", data: d.series.delivery, backgroundColor: token("--series-1"), borderRadius: 3, stack: "impact" },
      { label: "Participation", data: d.series.participation, backgroundColor: token("--series-3"), borderRadius: 3, stack: "impact" },
      medianLine(d.team_median.impact),
    ] }, options: options(true, false) });
  }

  function splitChart(d) {
    const last = d.dates.length - 1;
    if (last < 0 || (d.series.delivery[last] === null && d.series.participation[last] === null)) { empty("split", "No data yet"); return; }
    draw("split", { type: "bar", data: { labels: ["Delivery", "Participation"], datasets: [
      { label: "This person", data: [d.series.delivery[last], d.series.participation[last]], backgroundColor: token("--series-1"), borderRadius: 3 },
      { label: medianName, data: [d.team_median.delivery[last], d.team_median.participation[last]], backgroundColor: token("--series-2"), borderRadius: 3 },
    ] }, options: options(false, true) });
  }

  // claude_cost is null until Claude usage has synced, 0 when it synced but none is linked to this person.
  function costState(summary) {
    if (!summary || summary.claude_cost === null || summary.claude_cost === undefined) { return "waiting"; }
    return summary.claude_cost === 0 ? "unlinked" : "linked";
  }

  function noCostText() {
    return "No Claude cost is linked to this person yet, so Impact per dollar is blank. If they use Claude, link their Claude email on the ";
  }

  function unlinkedNote() {
    return [noCostText(), DA.el("a", { href: "/teams", text: "Teams screen" }), "."];
  }

  function showSummary(d) {
    const box = document.getElementById("series-summary");
    if (!box) { return; }
    box.textContent = "";
    const s = d.summary;
    if (!s) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const state = costState(s);
    const figure = function (text) { return DA.el("span", { class: "figure", text: text }); };
    const parts = ["Last " + s.window_days + " days: Impact ", figure(DA.fmt(s.impact)), " · Claude cost ",
                   figure(state === "waiting" ? "–" : DA.fmt(s.claude_cost, "usd"))];
    if (state === "linked") {
      parts.push(" · ", figure(DA.fmt(s.impact_per_dollar, "points_per_usd")), " impact per dollar (team median ",
                 DA.fmt(s.team_median_impact_per_dollar, "points_per_usd"), ")");
    }
    box.appendChild(DA.el("p", {}, parts));
    if (state === "unlinked") { box.appendChild(DA.el("p", { class: "explain" }, unlinkedNote())); }
    if (state === "waiting") { box.appendChild(DA.el("p", { class: "explain", text: "Waiting for Claude usage data." })); }
  }

  function perDollarEmpty(d) {
    const state = costState(d.summary);
    return state === "unlinked" ? "No Claude cost is linked to this person yet, so Impact per dollar is blank. Link their Claude email on the Teams screen."
                                : "Waiting for Claude usage data.";
  }

  function nameMedian(d) {
    if (!groupTeam) { return "Everyone's median"; }
    return d.comparison && d.comparison.custom ? "Selected people's median" : "Team median";
  }

  function showSeries(d) {
    medianName = nameMedian(d);
    impactChart(d);
    showSummary(d);
    lineChart(d, "impact_per_dollar", "Impact per dollar", perDollarEmpty(d));
    splitChart(d);
    lineChart(d, "delivery", "Delivery points");
    lineChart(d, "delivery_speed", "Delivery speed (hours)");
    lineChart(d, "durability", "Durability");
    lineChart(d, "participation", "Participation points");
    lineChart(d, "prs_reviewed", "PRs reviewed");
    lineChart(d, "review_value", "Review value");
    const notes = document.getElementById("series-notes");
    notes.textContent = "";
    DA.notes(notes, d.notes);
  }

  function windowDays() {
    const select = document.getElementById("person-window");
    return select ? select.value : "30";
  }

  function csvUrl(id) {
    return "/api/people/" + encodeURIComponent(id) + "/export.csv" + DA.query({ window_days: windowDays() });
  }

  function setLink(id) {
    const link = document.getElementById("download-csv");
    if (!link) { return; }
    if (id) { link.setAttribute("href", csvUrl(id)); } else { link.removeAttribute("href"); }
  }

  function card(item) {
    const key = item[0];
    return DA.el("section", { class: "card" }, [
      DA.el("h3", { text: item[1] }),
      DA.el("p", { class: "subtitle", text: item[2] }),
      DA.el("div", { class: "chart" }, [DA.el("canvas", { id: "chart-" + key, role: "img", "aria-label": item[1] })]),
      DA.el("p", { class: "note hidden", id: "empty-" + key }),
    ]);
  }

  function groupPanel() {
    const button = function (label, handler) { return DA.el("button", { type: "button", text: label, onclick: handler }); };
    return DA.el("details", { id: "compare-group", class: "compare-group hidden" }, [
      DA.el("summary", { id: "compare-summary", text: "Who counts as the team?" }),
      DA.el("p", { class: "note", text: "The dashed median is measured across the people ticked here. Untick anyone who isn't a main contributor; the charts update as you go." }),
      DA.el("div", { class: "form-row" }, [
        button("Select all", function () { setAll(true); applyGroup(); }),
        button("Clear", function () { setAll(false); applyGroup(); }),
      ]),
      DA.el("div", { id: "compare-people", class: "compare-people" }),
      DA.el("p", { id: "compare-message", class: "note" }),
    ]);
  }

  function boxes() { return Array.prototype.slice.call(document.querySelectorAll("#compare-people input")); }

  function setAll(on) { boxes().forEach(function (box) { box.checked = on; }); }

  function groupMessage(text, kind) {
    const node = document.getElementById("compare-message");
    if (node) { node.textContent = text; node.className = kind || "note"; }
  }

  function summarize(data) {
    const chosen = data.people.filter(function (p) { return p.selected; }).length;
    document.getElementById("compare-summary").textContent = data.custom
      ? "Who counts as the team? " + chosen + " of " + data.people.length + " people selected"
      : "Who counts as the team? Everyone (" + data.people.length + " people)";
  }

  function renderGroup(data) {
    const panel = document.getElementById("compare-group");
    if (!panel) { return; }
    panel.classList.remove("hidden");
    summarize(data);
    const list = document.getElementById("compare-people");
    list.textContent = "";
    data.people.forEach(function (p) {
      const box = DA.el("input", { type: "checkbox", value: p.person_id });
      box.checked = p.selected;
      box.addEventListener("change", applyGroup);
      list.appendChild(DA.el("label", { class: "check" }, [box, " " + p.name]));
    });
  }

  function loadGroup(team) {
    const panel = document.getElementById("compare-group");
    if (!panel) { return Promise.resolve(); }
    groupTeam = team;
    if (!team) { panel.classList.add("hidden"); return Promise.resolve(); }
    return DA.api("/api/teams/" + encodeURIComponent(team) + "/comparison").then(renderGroup)
      .catch(function (e) { panel.classList.remove("hidden"); groupMessage(e.message, "error"); });
  }

  // The team whose comparison group the charts use: the one picked at the top, else the first team,
  // so the people picker is there even on "All repositories". No teams at all means everyone.
  function groupTeamFor(picked) {
    if (picked) { return Promise.resolve(picked); }
    if (!fallbackTeam) {
      fallbackTeam = DA.api("/api/teams").then(function (data) {
        return data.teams && data.teams.length ? data.teams[0].team_id : "";
      }).catch(function () { fallbackTeam = null; return ""; });
    }
    return fallbackTeam;
  }

  function writeGroup(ids) {
    const team = groupTeam;
    groupMessage("Updating the median…");
    return DA.api("/api/teams/" + encodeURIComponent(team) + "/comparison", { method: "PUT", body: { person_ids: ids } })
      .then(function (data) { summarize(data); groupMessage("Median updated."); if (personId) { load(personId); } })
      .catch(function (e) { groupMessage(e.message, "error"); });
  }

  // Ticks apply after a one-second pause, so several clicks make one update; all ticked means the whole team.
  function applyGroup() {
    window.clearTimeout(groupTimer);
    groupMessage("Updating the median in a moment…");
    groupTimer = window.setTimeout(function () {
      const all = boxes();
      const ids = all.filter(function (box) { return box.checked; }).map(function (box) { return box.value; });
      if (!ids.length) { groupMessage("Tick at least one person to compare against.", "error"); return; }
      writeGroup(ids.length === all.length ? null : ids);
    }, GROUP_DELAY_MS);
  }

  function clear() {
    sequence += 1;
    Object.keys(charts).forEach(function (key) { charts[key].destroy(); delete charts[key]; });
    if (root) { root.textContent = ""; }
    root = null;
  }

  function mount(container) {
    clear();
    root = container;
    const select = DA.el("select", { id: "person-window", "aria-label": "Rolling window" }, [
      DA.el("option", { value: "30", text: "30 days" }),
      DA.el("option", { value: "60", text: "60 days" }),
      DA.el("option", { value: "90", text: "90 days" }),
    ]);
    select.addEventListener("change", function () {
      if (personId) { setLink(personId); load(personId); }
    });
    container.appendChild(DA.el("div", { class: "form-row" }, [
      DA.el("label", { for: "person-window", text: "Rolling window" }),
      select,
      DA.el("span", { class: "note", text: "Each point covers the days up to its date; the dashed line is the median of the people counted as the team." }),
      DA.el("a", { id: "download-csv", class: "button", download: true, text: "Download CSV" }),
    ]));
    container.appendChild(DA.el("div", { id: "series-summary", class: "series-summary hidden" }));
    container.appendChild(groupPanel());
    ROWS.forEach(function (row) {
      container.appendChild(DA.el("div", { class: "chart-row " + row[0] }, row[1].map(card)));
    });
    container.appendChild(DA.el("div", { id: "series-notes" }));
    setLink(personId);
  }

  function load(id) {
    if (!root) { return Promise.resolve(); }
    personId = id;
    sequence += 1;
    const mine = sequence;
    setLink(id);
    KEYS.forEach(function (key) { empty(key, "Loading…"); });
    const strip = document.getElementById("series-summary");
    if (strip) { strip.classList.remove("hidden"); strip.textContent = "Loading…"; }
    const notes = document.getElementById("series-notes");
    notes.textContent = "";
    return groupTeamFor(DA.state().team).then(function (team) {
      if (mine !== sequence) { return; }
      if (groupTeam !== team || !document.querySelector("#compare-people input")) { loadGroup(team); }
      const params = new URLSearchParams({ window_days: windowDays() });
      if (team) { params.set("team", team); }
      const weekly = new URLSearchParams(team ? { team: team } : {});
      DA.api("/api/person/" + encodeURIComponent(id) + "/weekly-points?" + weekly.toString()).then(function (w) {
        if (mine === sequence) { medianName = groupTeam ? (w.comparison.custom ? "Selected people's median" : "Team median") : "Everyone's median"; weeklyChart(w); }
      }).catch(function (e) { if (mine === sequence) { empty("weekly_points", e.message); } });
      return DA.api("/api/person/" + encodeURIComponent(id) + "/series?" + params.toString()).then(function (d) {
        if (mine === sequence) { showSeries(d); }
      });
    }).catch(function (e) {
      if (mine !== sequence) { return; }
      KEYS.forEach(function (key) {
        const note = document.getElementById("empty-" + key);
        if (note.textContent === "Loading…") { note.textContent = ""; note.classList.add("hidden"); }
      });
      if (strip) { strip.textContent = ""; strip.classList.add("hidden"); }
      DA.message(notes, e.message, "error");
    });
  }

  window.PersonCharts = { mount: mount, load: load, clear: clear, csvUrl: csvUrl };
})();
