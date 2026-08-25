# Storage AI — Intelligent Storage Cleanup Assistant

A desktop application that scans a folder tree, finds duplicate and likely-unused
files, forecasts future storage growth, and turns all of that into ranked,
actionable cleanup/archiving recommendations.

Built as an academic project on **AI at the Application Level**: rather than
call out to an LLM, the "AI" here is a set of classical, explainable
techniques — content hashing, weakly-supervised classification, and linear
regression forecasting — chosen so every recommendation can be traced back to
a concrete reason. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the
full write-up, and [`future_plan.md`](future_plan.md) for scalability and
local-LLM ideas not yet built.

## Features

- **Duplicate detection** — exact byte-for-byte duplicates found via a
  size → partial-hash → full-hash funnel, so only real candidates get fully
  hashed.
- **Unused-file scoring** — a `RandomForestClassifier` trained on
  weakly-labeled access patterns (falls back to a pure heuristic when there's
  not enough data to train), producing a 0–1 "likely unused" score per file.
- **Storage growth forecasting** — linear regression over either real scan
  history (once you've scanned the same folder more than once) or, on a first
  run, a pseudo-history built from the files' own modification timestamps.
- **File clustering** — K-means groups files by size and staleness into
  archetypes like "Large & Stale", an unsupervised cross-check independent
  of the classifier above.
- **Storage visualizations** — a file-type breakdown, a 30-day forecast, a
  folder-size treemap, and the cluster scatter, all on one dashboard.
- **Path classification** — every file is tagged `system`, `log`, `cache`,
  `application_data`, `user_data`, `trash`, or `other`, with a bonus label
  when it matches a well-known service default (e.g. `/var/lib/postgresql`
  → PostgreSQL) — see [Section 5 of the methodology](docs/METHODOLOGY.md#5-path-classification-and-applicationlog-awareness).
- **Ranked recommendations** — duplicates, unused files, storage warnings,
  and category advisories (e.g. "consider log rotation") combined into one
  list, sorted by estimated space recovered.
- **Safe by default** — cleanup actions send files to the OS trash
  (`send2trash`) or move them into a local dated archive folder; nothing is
  permanently deleted by this tool, and files under a live service's data
  directory or real OS system paths are never offered as delete/archive
  candidates in the first place.
- **Live activity monitoring** — a real-time create/modify/delete watcher
  (cross-platform, via `watchdog`) with rate-based trend alerts (large file
  added, rapid deletes by one user, activity bursts), runnable from the GUI
  or as a standalone always-on service. On Linux, optional `auditd`
  integration upgrades attribution from "who owns this file" to "who
  actually just did this" — see [Section 6 of the methodology](docs/METHODOLOGY.md#6-live-activity-monitoring).
- **Application storage-path discovery** — given just an app's name, finds
  where it actually stores its data, without being taught that app in
  advance: live process introspection via `/proc` first, then structured
  config-file parsing (JSON/YAML/TOML/INI), then an optional local,
  CPU-only extractive-QA model as a last resort for configs in a format
  nothing else understands. See [Section 8 of the methodology](docs/METHODOLOGY.md#8-application-storage-path-discovery--beyond-the-curated-table).

## Project layout

```
storage_ai/
  scanner.py            filesystem walk -> file metadata
  hashing.py            partial/full SHA-256 hashing
  duplicates.py         duplicate-group detection
  unused.py             unused-file heuristic + ML scoring
  clustering.py         K-means file clustering (size vs. staleness)
  prediction.py         storage growth forecasting
  path_classifier.py    system/log/cache/app-data/user-data/trash tagging
  category_advisor.py   static advisory recommendations by category/service
  treemap.py            squarified treemap layout (dashboard)
  recommender.py        combines everything into ranked recommendations
  actions.py            safe trash/archive operations + audit log
  database.py           SQLite persistence of scan snapshots + live activity
  pipeline.py           end-to-end orchestration (scan -> ... -> recommendations)
  watcher.py            live filesystem event watcher (cross-platform, via watchdog)
  audit_log.py          Linux auditd integration for real per-operation attribution
  trend_detector.py     rate-based alerts over live file activity
  watcher_service.py    standalone, independently-runnable live-monitoring service
  process_introspection.py  /proc-based discovery of a running process's storage paths
  config_discovery.py   finds + parses an app's config file, extracts path-like settings
  llm_config_extractor.py   optional local CPU-only extractive-QA fallback (see requirements-llm.txt)
  app_discovery.py       orchestrates the 3 tiers above into one ranked result
  gui/                  PySide6 desktop UI
tests/                  pytest suite for the non-GUI logic
docs/METHODOLOGY.md     design rationale for the report
requirements-llm.txt    optional heavy deps for the local LLM fallback tier (~1GB, not required)
```

## Setup

Requires Python 3.10+.

```bash
python3 -m venv --without-pip .venv   # only needed if `python3 -m venv` lacks pip
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -r requirements-dev.txt
```

(If your Python already has a working `venv`/`pip`, the usual
`python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt` is enough.)

Everything above is enough to run the full app. One tier of application
storage-path discovery (§8 of the methodology) is optional and not
installed by the steps above — see [sop.md](sop.md) if you want that
fallback tier too.

## Running

```bash
.venv/bin/python main.py
```

Pick a folder, click **Scan**, then use the Dashboard, File Types, Forecast,
Folders, Clusters, Duplicates, Unused Files, and Recommendations tabs to
review and act on the results. The **Live Activity** tab is independent of
scanning — pick a folder there and click **Start Live Monitoring** to watch
it in real time.

For monitoring that keeps running even when the GUI is closed (the point on
a server), run the watcher as its own process instead:

```bash
.venv/bin/python -m storage_ai.watcher_service /path/to/watch
```

See [Section 6 of the methodology](docs/METHODOLOGY.md#6-live-activity-monitoring)
for the `--enable-audit` flag, a sample systemd unit, and what it can and
can't attribute activity to.

## Testing

```bash
.venv/bin/python -m pytest
```

The suite covers the scanner, duplicate detector, unused-file scorer,
forecaster, recommender, and database layer — everything except the Qt GUI
itself, which is a thin wrapper over `pipeline.run_analysis`. The live
watcher is tested against real filesystem events (no root needed); the
auditd parser is tested against realistic sample data, since this repo's
dev environment has no `auditd` installed to test against live (see
`docs/METHODOLOGY.md`).
