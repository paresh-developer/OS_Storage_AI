# Storage AI — Intelligent Storage Cleanup Assistant

A desktop application that scans a folder tree, finds duplicate and likely-unused
files, forecasts future storage growth, and turns all of that into ranked,
actionable cleanup/archiving recommendations.

Built as an academic project on **AI at the Application Level**: rather than
call out to an LLM, the "AI" here is a set of classical, explainable
techniques — content hashing, weakly-supervised classification, and linear
regression forecasting — chosen so every recommendation can be traced back to
a concrete reason. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the
full write-up.

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
- **Ranked recommendations** — duplicates, unused files, and storage warnings
  combined into one list, sorted by estimated space recovered.
- **Safe by default** — cleanup actions send files to the OS trash
  (`send2trash`) or move them into a local dated archive folder; nothing is
  permanently deleted by this tool.

## Project layout

```
storage_ai/
  scanner.py        filesystem walk -> file metadata
  hashing.py         partial/full SHA-256 hashing
  duplicates.py        duplicate-group detection
  unused.py             unused-file heuristic + ML scoring
  prediction.py          storage growth forecasting
  recommender.py          combines everything into ranked recommendations
  actions.py               safe trash/archive operations + audit log
  database.py                SQLite persistence of scan snapshots
  pipeline.py                  end-to-end orchestration (scan -> ... -> recommendations)
  gui/                          PySide6 desktop UI
tests/                            pytest suite for the non-GUI logic
docs/METHODOLOGY.md                  design rationale for the report
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

## Running

```bash
.venv/bin/python main.py
```

Pick a folder, click **Scan**, then use the Dashboard, Duplicates, Unused
Files, and Recommendations tabs to review and act on the results.

## Testing

```bash
.venv/bin/python -m pytest
```

The suite covers the scanner, duplicate detector, unused-file scorer,
forecaster, recommender, and database layer — everything except the Qt GUI
itself, which is a thin wrapper over `pipeline.run_analysis`.
