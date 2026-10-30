(function () {
  "use strict";
  const DA = window.DA;
  const PersonCharts = window.PersonCharts;
  const STATS = [["prs_merged", "PRs merged"], ["reviews_given", "Reviews given"], ["reviews_assigned", "Reviews assigned"],
                 ["review_response_rate", "Response rate"], ["time_to_merge", "Median time to merge"], ["commits", "Commits"],
                 ["story_points_done", "Story points done"], ["qa_points_done", "QA points done"], ["issues_done", "Issues done"], ["cycle_time", "Median cycle time"],
                 ["cost_spent", "Claude cost"], ["story_points_per_dollar", "Points per dollar"]];

  function list(container, headers, rows) {
    container.textContent = "";
    if (!rows.length) { DA.message(container, "None in this window."); return; }
    const head = DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }));
    container.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, rows.map(function (r) {
      return DA.el("tr", {}, r.map(function (c) { return DA.el("td", { text: c === null || c === undefined ? "–" : String(c) }); }));
    }))]));
  }

  function tiles(container, pairs, id) {
    container.textContent = "";
    pairs.forEach(function (pair) {
      const tile = DA.el("div", { class: "stat" }, [DA.el("strong", { text: "…" }), DA.el("span", { text: pair[1] })]);
      container.appendChild(tile);
      DA.api("/api/metrics/" + pair[0] + DA.query({ include_inactive: "true" })).then(function (r) {
        const row = (r.rows || []).find(function (x) { return x.person_id === id; });
        tile.firstChild.textContent = r.status === "ok" && row ? DA.fmt(row.value, r.unit) : "–";
      }).catch(function () { tile.firstChild.textContent = "–"; });
    });
  }


  function remembered() {
    try { return window.localStorage.getItem("da.person") || ""; } catch (e) { return ""; }
  }

  function remember(id) {
    try { window.localStorage.setItem("da.person", id); } catch (e) { /* storage is off: nothing to remember */ }
  }

  function loadPeople() {
    return DA.api("/api/people" + DA.query({ include_inactive: "true" })).then(function (r) { return r.people; });
  }

  function fillPicker(people, chosen) {
    const picker = document.getElementById("person-picker");
    document.getElementById("all-people").setAttribute("href", "/people" + DA.query());
    picker.textContent = "";
    picker.appendChild(DA.el("option", { value: "", text: "Choose a person…" }));
    people.forEach(function (p) {
      picker.appendChild(DA.el("option", { value: p.person_id, text: p.status === "inactive" ? p.name + " (inactive)" : p.name }));
    });
    picker.value = chosen;
  }

  // Opening People from the nav lands here with no person: show the one viewed last, else the first by name.
  function chooseDefault() {
    const mount = document.getElementById("person-charts");
    loadPeople().then(function (people) {
      fillPicker(people, "");
      if (!people.length) { DA.message(mount, "No people yet. Add a team and run a sync first."); return; }
      const last = remembered();
      const known = people.some(function (p) { return p.person_id === last; });
      window.location.replace("/person" + DA.query({ id: known ? last : people[0].person_id }));
    }).catch(function (e) { DA.message(mount, e.message, "error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    PersonCharts.mount(document.getElementById("person-charts"));
    document.getElementById("person-picker").addEventListener("change", function (event) {
      if (event.target.value) {
        remember(event.target.value);
        window.location.assign("/person" + DA.query({ id: event.target.value }));
      }
    });
  });

  function day(iso) { return iso ? iso.slice(0, 10) : "–"; }

  DA.page(function render() {
    const s = DA.state();
    if (!s.id) { chooseDefault(); return; }
    remember(s.id);
    loadPeople().then(function (people) { fillPicker(people, s.id); }).catch(function () { /* the page works without the list */ });
    DA.api("/api/people/" + encodeURIComponent(s.id) + DA.query()).then(function (d) {
      document.getElementById("person-name").textContent = d.person.name;
      document.getElementById("person-identities").textContent =
        [d.person.accounts.join(", "), d.person.emails.join(", "), d.window.label].filter(Boolean).join(" · ");
      const commits = document.getElementById("person-commits");
      commits.textContent = "";
      DA.charts.bars(DA.canvas(commits), d.commits_weekly.map(function (w) { return w.week; }), d.commits_weekly.map(function (w) { return w.value; }), "Commits");
      DA.table(commits, ["Week starting", "Commits"], d.commits_weekly.map(function (w) { return [w.week, w.value]; }));
      const issuesCard = document.getElementById("person-issues-card");
      if (d.issues_done) {
        issuesCard.classList.remove("hidden");
        list(document.getElementById("person-issues"), ["Issue", "Type", "Story points", "Credit", "Credited via", "Resolved"],
          d.issues_done.map(function (i) { return [i.key, i.type, i.points, Math.round(i.share * 100) + "%", i.basis, day(i.resolved_at)]; }));
      } else {
        issuesCard.classList.add("hidden");
      }
      list(document.getElementById("person-pending"), ["#", "Title", "Repository", "Opened"],
        d.reviews_pending.map(function (p) { return [p.number, p.title, p.repository, day(p.created_at)]; }));
      list(document.getElementById("person-prs"), ["#", "Title", "Repository", "State", "Opened", "Merged"],
        d.pull_requests.map(function (p) { return [p.number, p.title, p.repository, p.state, day(p.created_at), day(p.merged_at)]; }));
      list(document.getElementById("person-reviews"), ["#", "Title", "Repository", "Kind", "When"],
        d.reviews_given.map(function (r) { return [r.number, r.title, r.repository, r.type, day(r.occurred_at)]; }));
    }).catch(function (e) { DA.message(document.getElementById("person-prs"), e.message, "error"); });

    const tickets = document.getElementById("person-tickets");
    DA.api("/api/tickets" + DA.query({ person: s.id })).then(function (t) {
      list(tickets, ["Ticket", "Type", "Points", "Claude cost", "Points per $", "Confidence", "PRs", "Hours to merge"],
        t.tickets.map(function (x) {
          return [x.key, x.type, x.points, DA.fmt(x.cost_usd, "usd"), DA.fmt(x.points_per_usd, "points_per_usd"),
                  x.confidence, x.pull_requests, DA.fmt(x.hours_to_merge, "hours")];
        }));
      if (t.cost_weekly && t.cost_weekly.some(function (w) { return w.cost_usd; })) {
        DA.charts.bars(DA.canvas(tickets), t.cost_weekly.map(function (w) { return w.week; }),
          t.cost_weekly.map(function (w) { return w.cost_usd; }), "Claude cost (USD)");
      }
      DA.notes(tickets, t.notes);
    }).catch(function (e) { DA.message(tickets, e.message, "error"); });

    PersonCharts.load(s.id);
    tiles(document.getElementById("person-stats"), STATS, s.id);
  });
})();
