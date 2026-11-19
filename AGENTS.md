# Instructions for AI assistants

For **humans running reports**: all setup, monthly commands, CLI options, output columns, and combined-workbook format are in **[README.md](README.md)**. Do not duplicate that material here — link to the relevant README section instead.

This file covers **what agents should do** when a user asks for help (including users with little or no programming experience).

---

## Source of truth (README sections)

| Topic | README section |
|-------|----------------|
| One-time setup (`uv`, `gh`, PAT, SSO) | [Install and setup](README.md#install-and-setup) |
| Monthly combined Excel (primary workflow) | [Monthly combined workbook (CEDT)](README.md#monthly-combined-workbook-cedt) |
| Agency / team tabs (`config/teams.yaml`) | [Agency / team tabs](README.md#agency--team-tabs) |
| Output directory (`--output-dir`, `GITHUB_ANALYSIS_RESULTS`) | [Output directory configuration](README.md#output-directory-configuration) |
| macOS / Linux / Windows, no `~/Dev` required | [macOS guide](#macos-macbook--setup-and-monthly-report), [Windows guide](#windows--setup-and-monthly-report), [Platforms and paths](README.md#platforms-and-paths) |
| Single-repo CLI | [Single-repo quick start](README.md#single-repo-quick-start), [Commands](README.md#commands) |
| Column / metric definitions | [Monthly metrics](README.md#monthly-metrics) and related tables in README |
| Architecture (for code changes) | [docs/architecture.md](docs/architecture.md) |

**Local output folder** (generated artifacts, not in git): default `~/github-analysis-results/` — or whatever the user set in `GITHUB_ANALYSIS_RESULTS`. See [Output directory configuration](README.md#output-directory-configuration). Do not assume `~/Dev` or a fixed clone path.

---

## Codebase layout (agents editing code)

```
github-analysis/
├── README.md                      # human runbook — update when CLI/columns change
├── AGENTS.md                      # this file
├── config/
│   └── teams.yaml                 # agency/team rosters → combined workbook team tabs
├── scripts/
│   ├── run_monthly.sh             # full calendar month → YYYY-MM/combined-YYYY-MM.xlsx
│   ├── run_cedt_trio.sh           # partial window → START_to_END/ under results base
│   └── combine_person_summaries.py
├── docs/architecture.md
└── github_analysis/               # Python package (cli, pipeline, export)
```

---

## Default behavior (do not override unless user asks)

Production monthly runs use **`./scripts/run_monthly.sh YYYY-MM`**, which applies the five CEDT repos, **`--merged-only`**, US Eastern dates, and workers documented in README. See [Monthly combined workbook (CEDT)](README.md#monthly-combined-workbook-cedt).

---

## When the user asks for a report

**You run it.** Do not hand them a long shell script unless they must complete GitHub login in a browser (OAuth) or create a PAT.

### Canonical commands (from repo root)

Discover the **clone path** (`git rev-parse --show-toplevel`) and **output directory** (`echo $GITHUB_ANALYSIS_RESULTS` or default `~/github-analysis-results`). Then:

| Request | You run |
|---------|---------|
| Full calendar month | `./scripts/run_monthly.sh YYYY-MM` |
| Dry-run | `./scripts/run_monthly.sh YYYY-MM --dry-run` |
| Partial window | `./scripts/run_cedt_trio.sh START END` — dates per README |
| Combined Excel only (data already fetched) | `uv run python scripts/combine_person_summaries.py …` — see README [Rebuild combined Excel only](README.md#rebuild-combined-excel-only-no-github-fetch) |

**Deliverable path:** `{results-base}/YYYY-MM/combined-YYYY-MM.xlsx` (or `{results-base}/{START}_to_{END}/…` for partial runs) — report the **resolved full path**, not a hardcoded `~/Dev/...` location. Team tabs come from `config/teams.yaml`.

### Agency / team tabs (agents)

Full schema and examples: [Agency / team tabs](README.md#agency--team-tabs).

| User asks | You do |
|-----------|--------|
| Add / edit a team or member | Edit [`config/teams.yaml`](config/teams.yaml) only — `name` (sheet tab), optional `team_banner` (row-1 banner), `members[].name` + `members[].user` |
| Rebuild after roster change (data already fetched) | Re-run `combine_person_summaries.py` on that run’s directory — do **not** re-fetch GitHub unless they ask |
| “What’s on the TresPi tab?” | Point to README: banner = `team_banner`, rows = Totals filtered to that roster |

Do **not** hardcode team rosters in Python or shell scripts.

### Agent checklist

1. **`gh auth status`** — if it fails, walk the user through [Authenticate with GitHub](README.md#4-authenticate-with-github); you cannot complete browser OAuth for them.
2. Confirm **which month or date range** in plain language before running.
3. Run the command from the **tool repo root** with `working_directory` set if Cursor shell output is empty.
4. On failure, read **`{repo}-*_run.log`** in the user's **run subdirectory** — do not guess.
5. Tell the user the **full path** to the combined `.xlsx` when done (under `{results-base}/YYYY-MM/` or `{START}_to_{END}/`).
6. **Do not commit** generated `.tsv` / `.xlsx` / `.json` / `.log` files.

---

## Helping non-technical users

Use README for factual details; your job is to **execute and explain in plain language**.

### What you do vs what they do

| Step | Who |
|------|-----|
| Install `uv` / `gh`, clone repo, `uv sync` | You guide using [Install and setup](README.md#install-and-setup); they may need to approve installs |
| `gh auth login` / PAT / org SSO | **They** must authenticate in browser or paste a token |
| `./scripts/run_monthly.sh YYYY-MM` | **You** run this |
| Open the Excel file | Give the **full path** under their output dir; macOS Finder **Go to Folder**, Windows Explorer `%USERPROFILE%\…`, or Linux file manager — see [Platforms and paths](README.md#platforms-and-paths) |

### User intent → your response

| User says | You do |
|-----------|--------|
| “Run the July report” / “Last month’s metrics” | Resolve `YYYY-MM`, run `./scripts/run_monthly.sh YYYY-MM`, report output path |
| “Where is the file?” | Give Finder path above; deliverable name `combined-YYYY-MM.xlsx` |
| “It failed” / “Nothing happened” | Read latest `*_run.log`; explain in non-jargon (see below) |
| “Do I need to run anything?” | No — if setup is done, you run the script; they only log in to GitHub if auth is missing |
| “What’s in the Totals sheet?” | Point to [Monthly combined workbook (CEDT)](README.md#monthly-combined-workbook-cedt) |
| “Add another agency / team tab” | Edit `config/teams.yaml` per [Agency / team tabs](README.md#agency--team-tabs); rebuild combined Excel if they already have a run |
| “Change the TresPi banner title” | Set `team_banner` on that team in `config/teams.yaml`, then rebuild combined Excel |

### Relaying errors (plain language)

| Log / symptom | Tell the user |
|---------------|----------------|
| `gh auth status` / not logged in | “GitHub isn’t signed in on this machine — run `gh auth login` once (I can walk you through it).” |
| 404 / not found on repo | “Your token can’t see the repo — check PAT `repo` scope and org SSO authorization.” |
| Rate limit / 403 | “GitHub throttled us — wait ~an hour and we can retry.” |
| Run succeeded | “Your report is ready at …/combined-YYYY-MM.xlsx — open that file in Excel.” |

Always state expected **wait time (~15–30 minutes)** once before a full fetch.

---

## Working on the codebase

| Task | Where |
|------|--------|
| Add CLI command | [docs/extending-the-cli.md](docs/extending-the-cli.md) |
| Pipeline / phases | [docs/architecture.md](docs/architecture.md) |
| Combined workbook / team tabs | `scripts/combine_person_summaries.py` |
| Agency rosters | `config/teams.yaml` (not Python) |
| Defaults (org, output dir) | `delivery_analysis/connectors/github/config.py` (`github_analysis/config.py` is a compatibility shim) |

After changing CLI, columns, teams config schema, or monthly workflow: **update README.md first**, then adjust this file only if agent behavior changes.

---

## Delivery analytics package (agents editing code)

- New code lives in `delivery_analysis/` (`core`, `connectors`, `store`, `sync`, `app`, `cli`). The GitHub code moved to `delivery_analysis/connectors/github/`; each old `github_analysis/...` module is a shim that aliases the old name to the new module, so do not add code to the shims.
- Run tests with `uv run pytest`. Never print, log, or store credential values; use `delivery_analysis.settings.redact` and `Secret`.
- Specs and plans live in `C:\Work\Planning`, not in this repo.

### Teams (agents)

Rosters are discovered from commits and stored in SQLite (`team`, `team_member`, `person`, `identity`); `config/teams.yaml` is a local, git-ignored import or export, never committed. Code: `delivery_analysis/identity/merge.py` (merging), `delivery_analysis/teams/` (discover, reconcile, import and export), `delivery_analysis/cli/teams.py`. Tests use made-up people on `*.example` domains only; never put real names or emails in tests or fixtures.

### Bitbucket connector (agents)

Code: `delivery_analysis/connectors/bitbucket/` (`client.py` HTTP and back-off, `normalize.py` pure mapping, `resolve.py`, `connector.py`), `delivery_analysis/store/repo_selection.py`, `delivery_analysis/cli/repos.py`. A repository scope string is the repository UUID and the connector name is `bitbucket`; team rosters rely on that to stay protected when a sync fails. Tests use `tests/bitbucket_fakes.py` (a `MockTransport` fake) and made-up people only; never call the live API from a test and never print or store the `BITBUCKET` token.

### App and metrics (agents)

Metrics live in `delivery_analysis/metrics/` (`catalog.py` lists them; each compute function returns per-account observations, and `registry.run_metric` turns them into per-person rows). The web API is `delivery_analysis/app/api.py`; pages are static files in `delivery_analysis/app/static/` (no build step, Chart.js vendored). Add a metric by writing its compute function and giving its catalog entry `compute=`; screens pick it up without changes. Never compute numbers in the browser.

**Points follow the Director's velocity rule** (so the app agrees with his "MD Dev Velocity" table): `metrics/credit.py` credits the Jira `Dev1`/`Dev2` fields first (0.75 to Dev1 and 0.25 to Dev2, who is usually the reviewer, when both differ; `DEV2_SHARE`; this departs from his table's 0.5/0.5 split by the user's decision), then Claude-era evidence, then linked PR authors, then the assignee; a ticket counts from `work_item.delivered_at`, the first time it reached Dev Done or later (`metrics/delivered.py`, `derive_delivered` runs after every sync, statuses overridable with `DELIVERED_STATUSES`); and the Jira connector's `developers` scope syncs tickets from projects that are not selected when a team member is Dev1 or Dev2. Never reintroduce `status_category = 'done'` as the definition of "completed" in a new query; use `DELIVERED_AT_SQL`. The step-by-step reconciliation with his table is in `evidence-scripts/velocity_reconcile.py` in the Direct Reports folder of the Planning folder.
