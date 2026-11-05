(function () {
  "use strict";
  const DA = window.DA;
  const TITLES = { story_points_done: "Story points done", prs_merged: "PRs merged", reviews_given: "Reviews given" };
  const CUSTOM = "people:";
  const MARK = "AI start";

  // The person (id=) and the "Compare against" choice (compare=) live in the URL.
  function compare() { return new URLSearchParams(window.location.search).get("compare") || ""; }
  function isCustom() { return compare().indexOf(CUSTOM) === 0; }
  function chosenIds() { return isCustom() ? compare().slice(CUSTOM.length).split(",").filter(Boolean) : []; }

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

  let pickersReady = false;
  function pickers(render) {
    if (pickersReady) { return Promise.resolve(); }
    pickersReady = true;
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
    }).catch(function () { pickersReady = false; });
    const who = document.getElementById("year-person");
    return DA.api("/api/uplift/year/people").then(function (data) {
      who.textContent = "";
      data.people.forEach(function (p) {
        const start = p.ai_start ? "AI start " + p.ai_start + (p.at_data_start ? " or earlier" : "") : "AI start unknown";
        who.appendChild(DA.el("option", { value: p.person_id, text: p.name + " · " + p.level + " · " + start }));
      });
      if (!DA.state().id && data.people.length) { DA.setParam("id", data.people[0].person_id); }
      who.value = DA.state().id;
      who.addEventListener("change", function () { DA.setParam("id", who.value); render(); });
    });
  }

  let who = "everyone";
  let shownFor = null;
  function showCompare(info, render) {
    who = info && info.label !== "Everyone" ? info.label : "everyone";
    if (info && info.value.indexOf(CUSTOM) === 0) {
      Array.prototype.forEach.call(document.getElementById("uplift-compare").options, function (o) {
        if (o.value === CUSTOM) { o.textContent = info.label; }
      });
      if (shownFor !== info.value) { shownFor = info.value; peopleList(render); }
    }
    DA.upliftLegend(document.getElementById("uplift-legend"), who, MARK);
    document.getElementById("uplift-compare-note").textContent = info && info.note ? info.note : "";
  }

  function text(v) { return v === null || v === undefined ? "–" : String(v); }

  function table(headers, rows) {
    return DA.el("table", {}, [
      DA.el("thead", {}, [DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }))]),
      DA.el("tbody", {}, rows.map(function (r) { return DA.el("tr", {}, r.map(function (v) { return DA.el("td", { text: text(v) }); })); })),
    ]);
  }

  function beforeSince(graph, split) {
    const rows = [];
    [["person", "Person"], ["everyone", who]].forEach(function (pair) {
      const group = graph[pair[0]] || {};
      (split ? [["before", "Before AI"], ["after", "Since AI"]] : [["before", "Last 12 months"]]).forEach(function (when) {
        const s = group[when[0]] || {};
        rows.push([pair[1], when[1], s.median, s.average, s.low, s.high, s.count]);
      });
    });
    return table(["Who", "When", "Median", "Average", "Low", "High", "Months"], rows);
  }

  function ratio(r) { return r === null || r === undefined ? "–" : "x" + r; }

  // The words below only restate numbers the API sent; nothing is computed here but their order.
  function effectLine(effect) {
    const me = effect.person.median, them = effect.group.median;
    if (me.change === null) { return "Not enough months on both sides of the AI start to compare."; }
    const gap = effect.vs_group === null ? "" : effect.vs_group > 0 ? ", a bigger rise than " + who
      : effect.vs_group < 0 ? ", a smaller rise than " + who : ", the same as " + who;
    return "Median month went from before to since AI by " + me.change + " (" + ratio(me.ratio) + "); " + who +
      " moved by " + text(them.change) + " (" + ratio(them.ratio) + ")" + gap + ". Average moved by " +
      effect.person.average.change + " against " + text(effect.group.average.change) + " for " + who + ".";
  }

  function graphs(root, d) {
    Object.keys(d.graphs).forEach(function (name) {
      const g = d.graphs[name];
      const empty = g.blocks.filter(function (b) { return b.no_data; }).map(function (b) { return b.start; });
      const note = [d.ai_start && g.short_baseline ? "Short baseline: fewer than 6 months of data before the AI start." : "",
        empty.length ? "No data for " + empty.join(", ") + ": nobody in " + who + " has any, so the selected repositories likely do not cover it. These months are left out of the figures." : ""]
        .filter(Boolean).join(" ");
      const body = DA.card(root, TITLES[name] || name, note);
      const canvas = DA.canvas(body);
      try { DA.upliftChart(canvas, g, { marker: MARK, bands: false }); } catch (e) { DA.message(canvas.parentNode, "The chart is not available."); }
      if (d.ai_start) { body.appendChild(DA.el("p", { class: "note", text: "AI effect: " + effectLine(g.effect) })); }
      body.appendChild(beforeSince(g, Boolean(d.ai_start)));
    });
  }

  function expectations(root, d) {
    const body = DA.card(root, "Against the expectations at their level", d.level +
      " thresholds. These are AI-agnostic: they hold whether or not someone uses AI.");
    d.expectations.forEach(function (p) {
      body.appendChild(DA.el("h4", { text: p.label + " · from " + p.first + ", " + p.days + " days" }));
      body.appendChild(table(["Item", "Verdict", "Value", "Threshold"],
        p.items.map(function (i) { return [i.item, i.verdict, i.value, i.threshold]; })));
    });
  }

  DA.page(function render() {
    const root = document.getElementById("person-body");
    showCompare(null);
    pickers(render).then(function () {
      const id = DA.state().id;
      if (!id) { DA.message(root, "No direct reports are set up. Add them with: delivery-analysis cohort set"); return; }
      DA.message(root, "Loading the year…");
      return DA.api("/api/uplift/year/person/" + encodeURIComponent(id) + DA.query({ compare: compare() })).then(function (d) {
        showCompare(d.compare, render);
        document.getElementById("person-name").textContent = d.person.name;
        document.getElementById("person-summary").textContent = d.level + " · " +
          (d.ai_start ? "AI start " + d.ai_start + (d.at_data_start ? " (or earlier)" : "") : "AI start unknown");
        const notes = document.getElementById("person-notes");
        notes.textContent = "";
        d.notes.forEach(function (t) { notes.appendChild(DA.el("li", { text: t })); });
        document.getElementById("person-coverage").textContent = "Data covered up to " + Object.keys(d.coverage || {}).map(function (k) {
          return k.replace(/_/g, " ") + ": " + (d.coverage[k] || "–");
        }).join(" · ");
        root.textContent = "";
        graphs(root, d); expectations(root, d);
      });
    }).catch(function (e) { DA.message(root, e.message, "error"); });
  });
})();
