# QA dashboard design

Date: 2026-10-30. Branch: `QA-Metrics`.

## Goal

A QA status page for senior management with three numbers: QA fail rate, escape defect rate and
regression bugs. It runs locally like the rest of the app; hosting is out of scope for now.

## Scope

- Jira project **MD** only. C3 is out until its regression process is understood.
- Window: 2026-06-01 to today.
- Read-only. Uses data the Jira sync already stores (work_item, work_item_transition, link,
  property). No Jira calls, no schema migration, no sync changes.
- No per-person numbers. Rows are keyed by sprint, month or release; account ids and names never
  leave the query layer.

## Data findings (local database, 2026-10-30)

- MD since 2026-06-01: 100 Defects, 363 Bugs, 65 Sub-bugs, 669 Stories.
- Sprint field (`sprint_10006`) is set on about 95% of tickets; values are JSON lists of
  `{id, name, startDate, endDate, state, boardId}`.
- Workflow: `Code Review -> Ready for QA -> In QA -> Dev Done`. Of 439 MD Stories that reached
  `In QA`, 61 went back to `In Progress`, `To Do` or `Code Review`.
- Affects version is almost never set; fix version is on 64% of Defects. Release is therefore
  taken from regression story titles, not versions.
- Every release from 3.30 has a story titled `X.XX regression` (plus `round 2` and `lite`
  variants). Bugs are linked to it mostly with `Block`, also `Blocks`, `Relates`, `Defect` and
  `Action item`.

## Metrics

### QA fail rate (per sprint)

- Population: MD Stories with at least one transition to `In QA`, assigned to a sprint.
- Failed: the Story has at least one transition from `In QA` or `Ready for QA` to `In Progress`,
  `To Do` or `Code Review`.
- Rate = failed / tested. Zero tested gives no rate (shown as "—").
- Companion figure: Sub-bugs per tested Story = Sub-bugs whose parent is a tested Story in the
  sprint / tested Stories.

### Escape defect rate (per sprint, and per month)

- Defects / (Defects + Bugs + Sub-bugs), counting MD tickets whose `created_at` falls inside the
  sprint's start and end dates (or the calendar month, US Eastern).
- Zero denominator gives no rate.

### Regression bugs (per release)

- Regression story: MD work item whose summary matches `^\s*(\d+\.\d+)\s+regression`
  (case-insensitive). The captured `X.XX` is the release. `round 2` and `lite` stories group under
  the same release.
- Regression bug: a distinct Bug-type work item linked to any regression story of the release by any
  link kind other than `parent`, regardless of when the Bug was created. Linked items that are not
  synced, or not Bugs, are ignored. A Bug linked twice counts once.
- Releases are included when their first regression story was created on or after the window start.
- The headline is the count. No rate for now.

### Sprint membership

- A ticket belongs to the **last** sprint in its Sprint field (latest `startDate`).
- Only sprints whose name starts with `MD Sprint` count.
- Stories that were tested but have no sprint are counted and shown as a "not in a sprint" note.

### Status and pattern constants

QA statuses, bounce-back statuses, the sprint name prefix and the regression title pattern are
module-level constants in `metrics/qa.py`.

## Components

- `delivery_analysis/metrics/qa.py`: pure functions taking a connection and a window.
  `qa_fail_by_sprint`, `escape_rate_by_sprint`, `escape_rate_by_month`,
  `regression_bugs_by_release`, and `qa_dashboard` which bundles them. Each row carries its counts
  and the ticket keys behind them.
- `GET /api/qa` returns `{window, project, sprints, months, releases, unsprinted_tested}`.
- `GET /api/qa/export.csv` writes the three tables as sections of one CSV with the existing export
  helpers.
- `/qa` page: `qa.html` and `pages/qa.js`, linked from the nav. Headline tiles (latest closed sprint
  for the two rates, latest finished release for regression bugs), a chart per rate by sprint, and a
  release table. Clicking a number lists its ticket keys. The browser does not compute numbers.

## Edge cases

- Active sprint and the newest release are labelled "in progress" and skipped by the headline tiles.
- Malformed Sprint JSON is treated as no sprint.

## Testing

- `tests/test_metrics_qa.py` with a seeded database of made-up tickets (fake MD keys, `*.example`
  people): bounce-back detection including from `Ready for QA`, last-sprint rule, non-MD sprints
  ignored, escape denominator, regression grouping (round 2, lite, case), double-link dedupe,
  non-Bug links ignored, zero denominators.
- API tests for `/api/qa` and the CSV; static asset test for the new page.
- README gains a short QA dashboard section.
