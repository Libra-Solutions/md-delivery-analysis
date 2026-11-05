/* Uplift chart: 30-day blocks around Day 0 against the median and average of everyone.
   Usage: DA.upliftChart(canvas, personBlocks, {threshold: 0.7}) -> Chart.
   Draws only: every number (medians, averages, before and after figures) arrives from the API. */
(function () {
  "use strict";
  const DA = (window.DA = window.DA || {});
  const live = new Map();
  const GREY = "#9a998f";
  const BLUE = "#2a78d6";
  const GREEN = "#1baf7a";
  const TEAL = "#0f9aa8";
  const PURPLE = "#7a4fc9";
  const ORANGE = "#eb8a2a";
  const RED = "#d03030";
  const SHADES = ["rgba(42,120,214,0.07)", "rgba(42,120,214,0.14)", "rgba(42,120,214,0.07)"];
  const NAMES = ["Days 1-30", "Days 31-60", "Days 61-90"];

  function token(name, fallback) {
    const value = getComputedStyle(document.body).getPropertyValue(name).trim();
    return value || fallback;
  }

  // The median line and its legend key share this one theme colour (main text, light and dark).
  function medianInk() { return token("--text-primary", "#111111"); }

  function isAfter(block) { return block.index >= 0; }

  function present(value) { return value !== null && value !== undefined; }

  function line(label, data, colour, dash, order) {
    return { type: "line", label: label, data: data, borderColor: colour, backgroundColor: colour, borderWidth: 2,
             borderDash: dash, pointRadius: 0, tension: 0, spanGaps: false, order: order };
  }

  function blockLabel(block) {
    return block.start + (block.partial ? " (running)" : "");
  }

  // Draws Day 0 and the shaded Days 1-30, 31-60 and 61-90 bands behind the bars.
  const dayZeroPlugin = {
    id: "upliftDayZero",
    beforeDatasetsDraw: function (chart, args, opts) {
      const blocks = (opts && opts.blocks) || [];
      const x = chart.scales.x;
      const area = chart.chartArea;
      if (!x || !area || blocks.length === 0) { return; }
      const first = blocks.findIndex(isAfter);
      if (first < 0) { return; }
      const step = blocks.length > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : area.right - area.left;
      const ctx = chart.ctx;
      ctx.save();
      ctx.textAlign = "center";
      const bands = opts.bands === false ? 0 : SHADES.length;
      for (let band = 0; band < bands; band += 1) {
        const at = first + band;
        if (at >= blocks.length) { break; }
        const left = x.getPixelForValue(at) - step / 2;
        ctx.fillStyle = SHADES[band];
        ctx.fillRect(left, area.top, step, area.bottom - area.top);
        ctx.fillStyle = token("--text-muted", GREY);
        ctx.fillText(NAMES[band], left + step / 2, area.top + 12);
      }
      const dayZero = x.getPixelForValue(first) - step / 2;
      ctx.strokeStyle = token("--text-secondary", "#444444");
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(dayZero, area.top);
      ctx.lineTo(dayZero, area.bottom);
      ctx.stroke();
      ctx.fillStyle = token("--text-secondary", "#444444");
      ctx.textAlign = "right";
      ctx.fillText(opts.marker || "Day 0", dayZero - 4, area.top + 12);
      ctx.restore();
    },
  };

  // One shared legend per page: bar keys are squares, line keys are a top border in the line's style.
  const KEYS = [
    { text: "Person, before Day 0", bar: GREY },
    { text: "Person, after Day 0", bar: BLUE },
    { text: "At or above the median", bar: GREEN },
    { text: "Median of {who} that month", line: null, style: "dashed" },
    { text: "Average of {who} that month", line: ORANGE, style: "dotted" },
    { text: "Own median, before and after Day 0", line: TEAL, style: "solid" },
    { text: "Own average, before and after Day 0", line: PURPLE, style: "dashed" },
    { text: "Threshold (quality charts)", line: RED, style: "solid" },
  ];

  // `label` names the comparison group in the two monthly keys (default "everyone").
  // `mark` renames "Day 0" in the keys (the AI year page passes "AI start").
  DA.upliftLegend = function upliftLegend(container, label, mark) {
    const who = label || "everyone";
    container.textContent = "";
    container.classList.add("uplift-legend");
    KEYS.forEach(function (key) {
      if (mark) { key = Object.assign({}, key, { text: key.text.replace("Day 0", mark) }); }
      const swatch = DA.el("span", { style: key.bar
        ? "display:inline-block;width:12px;height:12px;vertical-align:middle;margin-right:6px;background:" + key.bar
        : "display:inline-block;width:22px;height:0;vertical-align:middle;margin-right:6px;border-top:2px " + key.style + " " + (key.line || medianInk()) });
      container.appendChild(DA.el("span", { style: "white-space:nowrap;margin-right:16px;display:inline-block" },
        [swatch, DA.el("span", { text: key.text.replace("{who}", who) })]));
    });
  };

  // A checklist of people for "Custom people…": options {people: [{person_id, name}], selected: [ids], onApply(ids)}.
  // Names go in as text; nothing is computed here beyond how many boxes are ticked.
  DA.upliftPeoplePicker = function upliftPeoplePicker(container, options) {
    const opts = options || {};
    const chosen = new Set(opts.selected || []);
    const boxes = [];
    container.textContent = "";
    const note = DA.el("span", { class: "note" });
    const apply = DA.el("button", { type: "button", text: "Apply" });
    function sync() {
      const ticked = boxes.filter(function (b) { return b.box.checked; }).length;
      apply.disabled = ticked < 2;
      note.textContent = ticked < 2 ? "Pick at least 2 people" : ticked + " people ticked";
    }
    function setAll(on) { boxes.forEach(function (b) { b.box.checked = on; }); sync(); }
    const list = DA.el("div", { style: "max-height:240px;overflow:auto;margin:8px 0" });
    (opts.people || []).forEach(function (p) {
      const box = DA.el("input", { type: "checkbox", value: p.person_id });
      box.checked = chosen.has(p.person_id);
      box.addEventListener("change", sync);
      boxes.push({ id: p.person_id, box: box });
      list.appendChild(DA.el("label", { style: "display:block" }, [box, " ", DA.el("span", { text: p.name })]));
    });
    apply.addEventListener("click", function () {
      const ids = boxes.filter(function (b) { return b.box.checked; }).map(function (b) { return b.id; });
      if (ids.length >= 2 && opts.onApply) { opts.onApply(ids); }
    });
    container.appendChild(DA.el("div", {}, [
      DA.el("button", { type: "button", text: "Select all", onclick: function () { setAll(true); } }), " ",
      DA.el("button", { type: "button", text: "Clear", onclick: function () { setAll(false); } }), " ",
      apply, " ", note,
    ]));
    container.appendChild(list);
    sync();
  };

  DA.upliftChart = function upliftChart(canvas, graph, options) {
    const opts = options || {};
    const blocks = (graph && graph.blocks) || [];
    const person = (graph && graph.person) || {};
    const before = person.before || {};
    const after = person.after || {};
    if (live.has(canvas)) { live.get(canvas).destroy(); live.delete(canvas); }
    if (typeof window.Chart === "undefined") {
      canvas.parentNode.replaceWith(DA.el("p", { class: "note", text: "Charts are unavailable because Chart.js did not load; use the table below." }));
      return null;
    }
    const grid = token("--grid", "#ecebe7");
    const ink = token("--text-secondary", "#444444");
    const colours = blocks.map(function (b) {
      if (!isAfter(b)) { return GREY; }
      return present(b.value) && present(b.median) && b.value >= b.median ? GREEN : BLUE;
    });
    const segment = function (summary, key, wantAfter) {
      return blocks.map(function (b) { return isAfter(b) === wantAfter && present(summary[key]) ? summary[key] : null; });
    };
    const datasets = [
      { type: "bar", label: "person", data: blocks.map(function (b) { return b.value; }), backgroundColor: colours,
        borderRadius: 3, maxBarThickness: 36, order: 5 },
      line("median", blocks.map(function (b) { return b.median; }), medianInk(), [6, 4], 1),
      line("average", blocks.map(function (b) { return b.average; }), ORANGE, [2, 3], 2),
      line("before median", segment(before, "median", false), TEAL, [], 3),
      line("before average", segment(before, "average", false), PURPLE, [6, 4], 4),
      line("after median", segment(after, "median", true), TEAL, [], 3),
      line("after average", segment(after, "average", true), PURPLE, [6, 4], 4),
    ];
    if (present(opts.threshold)) {
      datasets.push(line("threshold", blocks.map(function () { return opts.threshold; }), RED, [], 0));
    }
    canvas.setAttribute("aria-label", "Blocks of 30 days around Day 0 against the median and average of everyone");
    const chart = new window.Chart(canvas, {
      type: "bar",
      data: { labels: blocks.map(blockLabel), datasets: datasets },
      plugins: [dayZeroPlugin],
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: true },
          upliftDayZero: { blocks: blocks, marker: opts.marker, bands: opts.bands },
        },
        scales: {
          x: { grid: { color: "transparent" }, ticks: { color: ink } },
          y: { beginAtZero: true, grid: { color: grid }, ticks: { color: ink } },
        },
      },
    });
    live.set(canvas, chart);
    return chart;
  };
})();
