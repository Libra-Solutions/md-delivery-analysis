(function () {
  "use strict";
  const DA = window.DA;
  const TITLES = { story_points_done: "Story points done", prs_merged: "PRs merged", reviews_given: "Reviews given" };
  const QUALITY = { prs_with_tests: "PRs with tests", comments_received_per_pr: "Comments received per PR",
                    durability: "Durability", inline_comments_given: "Inline comments given" };
  const WORKED = { prs_front_end: "Front-end PRs", prs_back_end: "Back-end PRs", prs_database: "Database PRs",
                   prs_multi_layer: "Multi-layer PRs", reviews_given: "Reviews given",
                   inline_comments_given: "Inline comments given", teammates_reviewed: "Teammates reviewed",
                   big_tickets: "Big tickets (8+ points)" };

  // The "Compare against" choice lives in the URL as compare= (everyone when absent).
  function compare() { return new URLSearchParams(window.location.search).get("compare") || ""; }

  const CUSTOM = "people:";
  function isCustom() { return compare().indexOf(CUSTOM) === 0; }
  function chosenIds() { return isCustom() ? compare().slice(CUSTOM.length).split(",").filter(Boolean) : []; }

  // "Custom people…" shows a checklist; Apply writes compare=people:<ids> to the URL and reloads.
  function peopleList(render) {
    const box = document.getElementById("uplift-people");
    DA.api("/api/people" + DA.query()).then(function (data) {
      box.hidden = false;
      DA.upliftPeoplePicker(box, { people: data.people, selected: chosenIds(), onApply: function (ids) {
        DA.setParam("compare", CUSTOM + ids.join(","));
        render();
      } });
    }).catch(function (e) { DA.message(box, e.message, "error"); box.hidden = false; });
  }

  let pickerReady = false;
  function picker(render) {
    if (pickerReady) { return; }
    pickerReady = true;
    const select = document.getElementById("uplift-compare");
    DA.api("/api/uplift/compare-options").then(function (data) {
      data.options.forEach(function (o) {
        let text = o.size === null || o.size === undefined ? o.label : o.label + " (" + o.size + ")";
        if (o.value === CUSTOM && isCustom()) { text = chosenIds().length + " chosen people"; }
        select.appendChild(DA.el("option", { value: o.value, text: text, selected: o.value === (isCustom() ? CUSTOM : compare() || "everyone") }));
      });
      select.addEventListener("change", function () {
        if (select.value === CUSTOM) { peopleList(render); return; }
        document.getElementById("uplift-people").hidden = true;
        DA.setParam("compare", select.value === "everyone" ? "" : select.value);
        render();
      });
    }).catch(function () { pickerReady = false; });
  }

  let who = "everyone";
  let shownFor = null;
  function showCompare(info, render) {
    const label = info ? info.label : "everyone";
    who = label;
    if (info && info.value.indexOf(CUSTOM) === 0) {
      Array.prototype.forEach.call(document.getElementById("uplift-compare").options, function (o) {
        if (o.value === CUSTOM) { o.textContent = info.label; }
      });
      if (shownFor !== info.value) { shownFor = info.value; peopleList(render); }
    }
    DA.upliftLegend(document.getElementById("uplift-legend"), label);
    document.getElementById("uplift-compare-note").textContent = info && info.note ? info.note : "";
  }

  function cell(v) { return DA.el("td", { text: v === null || v === undefined ? "–" : String(v) }); }

  function table(headers, rows) {
    return DA.el("table", {}, [
      DA.el("thead", {}, [DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }))]),
      DA.el("tbody", {}, rows.map(function (r) { return DA.el("tr", {}, r.map(cell)); })),
    ]);
  }

  function draw(body, graph, options) {
    const canvas = DA.canvas(body);
    try { DA.upliftChart(canvas, graph, options || {}); } catch (e) { DA.message(canvas.parentNode, "The chart is not available."); }
  }

  function beforeAfter(blocks) {
    const rows = [];
    [["person", "Person"], ["everyone", who]].forEach(function (pair) {
      const group = blocks[pair[0]] || {};
      ["before", "after"].forEach(function (when) {
        const s = group[when] || {};
        rows.push([pair[1], when, s.median, s.average, s.low, s.high, s.count]);
      });
    });
    return table(["Who", "When", "Median", "Average", "Low", "High", "Blocks"], rows);
  }

  function metricTable(rows) {
    const labels = [];
    rows.forEach(function (r) { (r.windows || []).forEach(function (w) { if (labels.indexOf(w.label) < 0) { labels.push(w.label); } }); });
    const body = rows.map(function (r) {
      const byLabel = {};
      (r.windows || []).forEach(function (w) { byLabel[w.label] = w; });
      return [r.label || r.metric, r.before, r.before_median_everyone].concat(labels.map(function (l) {
        const w = byLabel[l];
        return w ? w.value + " (" + who + " " + w.median + ", x" + (w.uplift === null || w.uplift === undefined ? "–" : w.uplift) + ")" : "–";
      }));
    });
    return table(["Metric", "Before", who + " before"].concat(labels), body);
  }

  function graphs(root, d) {
    Object.keys(d.graphs).forEach(function (name) {
      const g = d.graphs[name];
      const empty = (g.blocks.blocks || []).filter(function (b) { return b.no_data; }).map(function (b) { return b.start; });
      const note = [g.blocks.short_baseline ? "Short baseline: fewer than 6 blocks before Day 0, so the before numbers are thin." : "",
        empty.length ? "No data for the blocks starting " + empty.join(", ") + ": nobody in " + who + " has any, so the selected repositories likely do not cover them. They are left out of the figures." : ""]
        .filter(Boolean).join(" ");
      const body = DA.card(root, TITLES[name] || name, note);
      draw(body, g.blocks);
      body.appendChild(beforeAfter(g.blocks));
      body.appendChild(metricTable(g.table));
    });
    draw(DA.card(root, "Points by merge date", "The same points counted on the day the PR merged."), d.points_by_merge);
  }

  function windows(root, d) {
    const body = DA.card(root, "Windows and verdicts");
    body.appendChild(table(["Window", "Days reached", "Total", "Pro-rated to the full window", "Median of " + who + " (full window)", "Before median", "Uplift"],
      d.windows.map(function (w) { return [w.label, w.reached, w.total, w.prorated, w.median, w.before_median, w.uplift]; })));
    d.verdicts.forEach(function (v) {
      body.appendChild(DA.el("h4", { text: v.label }));
      body.appendChild(table(["Item", "Verdict", "Value", "Threshold"],
        v.items.map(function (i) { return [i.item, i.verdict, i.value, i.threshold]; })));
    });
  }

  function quality(root, d) {
    const row = DA.el("div", { class: "chart-row two" });
    root.appendChild(row);
    d.quality.forEach(function (q) {
      const body = DA.card(row, QUALITY[q.metric] || q.metric, q.threshold === null ? "" : "Threshold " + q.threshold);
      draw(body, q.blocks, { threshold: q.threshold });
    });
  }

  function worked(root, d) {
    const body = DA.card(root, "How they worked", "Per window.");
    const labels = [];
    Object.keys(d.how_they_worked).forEach(function (m) {
      d.how_they_worked[m].forEach(function (w) { if (labels.indexOf(w.label) < 0) { labels.push(w.label); } });
    });
    body.appendChild(table(["Measure"].concat(labels), Object.keys(WORKED).map(function (m) {
      const byLabel = {};
      (d.how_they_worked[m] || []).forEach(function (w) { byLabel[w.label] = w; });
      return [WORKED[m]].concat(labels.map(function (l) { return byLabel[l] ? byLabel[l].total : null; }));
    })));
  }

  function ai(root, d) {
    const body = DA.card(root, "Claude use by week", d.ai.starts ? "Data starts " + d.ai.starts : "No Claude data for this person.");
    body.appendChild(table(["Week", "Cost (USD)", "Active days", "Points"],
      (d.ai.weeks || []).map(function (w) { return [w.week, w.cost_usd, w.active_days, w.points]; })));
  }

  function explain(root, d) {
    const body = DA.card(root, "What the data says");
    body.appendChild(DA.el("ul", { class: "notes" }, d.explain.map(function (t) { return DA.el("li", { text: t }); })));
  }

  DA.page(function render() {
    const s = DA.state();
    const root = document.getElementById("person-body");
    document.getElementById("back-link").setAttribute("href", "/uplift" + DA.query({ compare: compare() }));
    showCompare(null);
    picker(render);
    if (!s.id) { DA.message(root, "Choose a person from the cohort page."); return; }
    DA.message(root, "Loading… this can take a minute.");
    DA.api("/api/uplift/person/" + encodeURIComponent(s.id) + DA.query({ compare: compare() })).then(function (d) {
      showCompare(d.compare, render);
      document.getElementById("person-name").textContent = d.person.name;
      document.getElementById("person-summary").textContent = d.level + " · Day 0 " + d.day0 + " · Day " + d.day_reached + " of 90";
      document.getElementById("person-coverage").textContent = "Data covered up to " + Object.keys(d.coverage || {}).map(function (k) {
        return k.replace(/_/g, " ") + ": " + (d.coverage[k] || "–");
      }).join(" · ");
      root.textContent = "";
      graphs(root, d); windows(root, d); quality(root, d); worked(root, d); ai(root, d); explain(root, d);
    }).catch(function (e) { DA.message(root, e.message, "error"); });
  });
})();
