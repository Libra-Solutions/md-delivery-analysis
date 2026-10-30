(function () {
  "use strict";
  const DA = window.DA;

  function pct(value) { return DA.fmt(value, "ratio"); }
  function asPct(value) { return value === null || value === undefined ? null : Math.round(value * 1000) / 10; }

  function showKeys(title, keys) {
    const box = document.getElementById("qa-detail");
    box.textContent = "";
    const body = DA.card(box, title, keys.length + " tickets");
    body.appendChild(DA.el("p", { text: keys.join(", ") }));
    box.scrollIntoView({ behavior: "smooth" });
  }

  function keysLink(text, title, keys) {
    if (!keys || !keys.length) { return DA.el("span", { text: text }); }
    return DA.el("a", { href: "#qa-detail", text: text, onclick: function (event) { event.preventDefault(); showKeys(title, keys); } });
  }

  function table(body, headers, rows) {
    const head = DA.el("tr", {}, headers.map(function (h, i) { return DA.el("th", { class: i ? "num" : "", text: h }); }));
    const lines = rows.map(function (cells) {
      return DA.el("tr", {}, cells.map(function (cell, i) {
        return DA.el("td", { class: i ? "num" : "" }, [typeof cell === "string" ? DA.el("span", { text: cell }) : cell]);
      }));
    });
    body.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, lines)]));
  }

  function tile(box, value, label) {
    box.appendChild(DA.el("div", { class: "stat" }, [DA.el("strong", { text: value }), DA.el("span", { text: label })]));
  }

  function headline(data) {
    const box = document.getElementById("qa-headline");
    box.textContent = "";
    const s = data.headline.sprint;
    const r = data.headline.release;
    tile(box, s ? pct(s.fail_rate) : "–", "QA fail rate" + (s ? " · " + s.name : ""));
    tile(box, s ? pct(s.escape_rate) : "–", "Escape defect rate" + (s ? " · " + s.name : ""));
    tile(box, r ? String(r.bugs) : "–", "Regression bugs" + (r ? " · release " + r.release : ""));
  }

  function sprintCharts(data) {
    const box = document.getElementById("qa-charts");
    box.textContent = "";
    const labels = data.sprints.map(function (s) { return s.name + (s.in_progress ? " (in progress)" : ""); });

    const fail = DA.card(box, "QA fail rate by sprint", "Stories that reached In QA and were sent back to development");
    DA.charts.series(DA.canvas(fail), labels, [{ label: "QA fail rate %", data: data.sprints.map(function (s) { return asPct(s.fail_rate); }) }], { type: "line" });
    table(fail, ["Sprint", "Tested", "Failed QA", "Fail rate", "Sub-bugs per Story"], data.sprints.map(function (s, i) {
      return [labels[i], String(s.tested), keysLink(String(s.failed), s.name + " · failed QA", s.failed_keys), pct(s.fail_rate), DA.fmt(s.sub_bugs_per_story)];
    }));

    const escape = DA.card(box, "Escape defect rate by sprint", "Defects ÷ (Defects + Bugs + Sub-bugs) created during the sprint");
    DA.charts.series(DA.canvas(escape), labels, [{ label: "Escape defect rate %", data: data.sprints.map(function (s) { return asPct(s.escape_rate); }) }], { type: "line" });
    table(escape, ["Sprint", "Defects", "Bugs", "Sub-bugs", "Escape rate"], data.sprints.map(function (s, i) {
      return [labels[i], keysLink(String(s.defects), s.name + " · Defects", s.defect_keys), String(s.bugs), String(s.sub_bugs), pct(s.escape_rate)];
    }));

    const month = DA.card(box, "Escape defect rate by month", "Same rate by calendar month (US Eastern)");
    const months = data.months.map(function (m) { return m.month; });
    DA.charts.series(DA.canvas(month), months, [{ label: "Escape defect rate %", data: data.months.map(function (m) { return asPct(m.escape_rate); }) }]);
    table(month, ["Month", "Defects", "Bugs", "Sub-bugs", "Escape rate"], data.months.map(function (m) {
      return [m.month, keysLink(String(m.defects), m.month + " · Defects", m.defect_keys), String(m.bugs), String(m.sub_bugs), pct(m.escape_rate)];
    }));
  }

  function releases(data) {
    const box = document.getElementById("qa-releases");
    box.textContent = "";
    const body = DA.card(box, "Regression bugs by release", "Bugs linked to the release's X.XX Regression stories");
    const labels = data.releases.map(function (r) { return r.release + (r.in_progress ? " (in progress)" : ""); });
    DA.charts.series(DA.canvas(body), labels, [{ label: "Regression bugs", data: data.releases.map(function (r) { return r.bugs; }) }]);
    table(body, ["Release", "Regression bugs", "Regression stories"], data.releases.map(function (r, i) {
      return [labels[i], keysLink(String(r.bugs), "Release " + r.release + " · regression bugs", r.bug_keys), r.regression_stories.join(", ")];
    }));
  }

  function render(data) {
    const scope = "Jira project " + data.project + ", " + data.window.start + " to " + data.window.end +
      ". Team, sprint and release figures only. The team and window pickers above do not apply here.";
    const loose = data.unsprinted_tested ? " " + data.unsprinted_tested + " tested Stories had no sprint and are left out." : "";
    DA.message(document.getElementById("qa-scope"), scope + loose);
    headline(data);
    sprintCharts(data);
    releases(data);
  }

  DA.page(function () {
    DA.api("/api/qa").then(render).catch(function (error) {
      DA.message(document.getElementById("qa-charts"), "Could not load QA numbers: " + error.message, "error");
    });
  });
})();
