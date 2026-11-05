(function () {
  "use strict";
  const DA = window.DA;

  function coverageLine(c) {
    return Object.keys(c || {}).map(function (k) { return k.replace(/_/g, " ") + ": " + (c[k] || "–"); }).join(" · ");
  }

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

  let shownFor = null;
  function showCompare(info, render) {
    const label = info ? info.label : "everyone";
    if (info && info.value.indexOf(CUSTOM) === 0) {
      Array.prototype.forEach.call(document.getElementById("uplift-compare").options, function (o) {
        if (o.value === CUSTOM) { o.textContent = info.label; }
      });
      if (shownFor !== info.value) { shownFor = info.value; peopleList(render); }
    }
    DA.upliftLegend(document.getElementById("uplift-legend"), label);
    document.getElementById("uplift-compare-note").textContent = info && info.note ? info.note : "";
  }

  function ofCount(side) {
    return side ? side.count + " of " + side.of : "–";
  }

  function draw(canvas, graph) {
    try { DA.upliftChart(canvas, graph, {}); } catch (e) { DA.message(canvas.parentNode, "The chart is not available."); }
  }

  function card(p) {
    const body = DA.el("div", { class: "card-body" });
    const link = DA.el("a", { href: "/uplift/person" + DA.query({ id: p.person_id, compare: compare() }), text: p.name });
    const node = DA.el("section", { class: "card" }, [
      DA.el("h3", {}, [link]),
      DA.el("p", { class: "subtitle", text: p.level + " · Day " + p.day_reached + " of 90 · blocks at or above the median of the comparison group, before Day 0: " + ofCount((p.at_or_above_median || {}).before) + ", after: " + ofCount((p.at_or_above_median || {}).after) }),
      body,
    ]);
    draw(DA.canvas(body), p.points);
    return node;
  }

  function grid(container, people) {
    container.textContent = "";
    if (!people.length) { DA.message(container, "Nobody is in the cohort yet. Add people with the cohort command."); return; }
    const width = Math.max.apply(null, people.map(function (p) { return p.grid.length; }));
    const heads = ["Person", "Level"];
    for (let i = 0; i < width; i += 1) { heads.push("Block " + i); }
    const rows = people.map(function (p) {
      const cells = [DA.el("td", { text: p.name }), DA.el("td", { text: p.level })];
      for (let i = 0; i < width; i += 1) {
        const b = p.grid[i];
        const text = !b ? "–" : (b.value === null ? "–" : String(b.value)) + (b.partial ? " (running)" : "");
        const cls = b && b.value !== null && b.median !== null && b.value >= b.median ? "good" : "";
        cells.push(DA.el("td", { class: cls, text: text }));
      }
      return DA.el("tr", {}, cells);
    });
    container.appendChild(DA.el("table", {}, [
      DA.el("thead", {}, [DA.el("tr", {}, heads.map(function (h) { return DA.el("th", { text: h }); }))]),
      DA.el("tbody", {}, rows),
    ]));
  }

  DA.page(function render() {
    showCompare(null);
    picker(render);
    DA.message(document.getElementById("uplift-cards"), "Loading the cohort… this can take a minute.");
    DA.api("/api/uplift/cohort" + DA.query({ compare: compare() })).then(function (d) {
      showCompare(d.compare, render);
      document.getElementById("uplift-coverage").textContent = "Data covered up to " + coverageLine(d.coverage);
      const cards = document.getElementById("uplift-cards");
      cards.textContent = "";
      d.people.forEach(function (p) { cards.appendChild(card(p)); });
      grid(document.getElementById("uplift-grid"), d.people);
    }).catch(function (e) { DA.message(document.getElementById("uplift-cards"), e.message, "error"); });
  });
})();
