# Standard Operating Procedure — Storage AI

This document explains how the project was built, what's required to run it,
and how to diagnose and fix the issues you're most likely to hit. Pair it
with [`ReadMe.md`](ReadMe.md) (quick start) and
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) (why the analysis works the way
it does).

## 1. How this was built

The build went in this order — useful context if you need to extend the
project the same way:

1. **Scoped the architecture** before writing code: desktop GUI (not CLI/web),
   Python, classical ML + heuristics (not an LLM call), academic-project
   structure. These were deliberate choices, not defaults — see
   [Section 5](#5-design-choices-and-why) if you want the reasoning.
2. **Set up an isolated Python environment.** The target machine had no
   `pip` and no working `venv` module (`ensurepip` missing) and no
   passwordless `sudo`, so instead of touching system packages, pip was
   bootstrapped entirely in user space:
   ```bash
   python3 -m venv --without-pip .venv
   curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
   .venv/bin/pip install -r requirements-dev.txt
   ```
3. **Built the non-GUI core first, bottom-up**, each module with a single
   responsibility so it could be unit-tested without Qt:
   `scanner.py` → `hashing.py` → `duplicates.py` → `unused.py` →
   `prediction.py` → `database.py` → `recommender.py` → `actions.py` →
   `pipeline.py` (the orchestrator that wires all of the above together).
4. **Wrote the test suite alongside the core modules** (`tests/`, pytest) —
   21 tests covering scanning, duplicate grouping, unused-file scoring
   (both the ML and heuristic-fallback paths), forecasting, the
   recommendation ranker, and the SQLite layer.
5. **Built the GUI as a thin layer over `pipeline.run_analysis`**
   (`storage_ai/gui/`): a `QThread` worker so scanning never blocks the UI,
   and four tabs (Dashboard, Duplicates, Unused Files, Recommendations) that
   each just render what the pipeline returns.
6. **Verified it for real**, not just with unit tests: built a scratch demo
   folder containing a known exact duplicate and two files with timestamps
   forced 400 days in the past, ran the full pipeline against it to confirm
   correct output, then drove the actual `MainWindow` through a real scan
   (via a headed X11/Wayland session) and screenshotted all four tabs to
   confirm the UI rendered and updated correctly.
7. **Fixed what the visual pass caught**: two tables had columns too narrow
   for their own header text or content (`duplicates_tab.py`,
   `unused_tab.py`, `recommendations_tab.py`) — fixed with explicit
   `setSectionResizeMode(..., Stretch)` / `setColumnWidth(...)` calls.

## 2. Requirements to run

- **Python 3.10+** (built and tested on 3.13).
- **A display server** — PySide6 is a GUI toolkit; it needs `DISPLAY`
  (X11) or `WAYLAND_DISPLAY` set. It will not run over a plain SSH session
  without X forwarding, and will not run in a fully headless container
  unless you use Qt's offscreen platform plugin (see FAQ).
- **Internet access**, only for the one-time setup step (downloading
  `get-pip.py` and the packages in `requirements.txt`). Nothing at runtime
  calls out to the network — all analysis is local.
- **Disk**: the app writes its database and archive folder to
  `~/.storage_ai/` (see `storage_ai/config.py` — `APP_DIR`).
- No GPU, no API keys, no external services.

## 3. Setup, step by step

```bash
cd /home/paresh/Documents/OS_Storage_AI

# 1. Create a virtual environment.
python3 -m venv .venv
# If that fails with "ensurepip is not available", create it without pip
# and bootstrap pip manually instead:
#   python3 -m venv --without-pip .venv
#   curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python

# 2. Install dependencies (add -dev for pytest too).
.venv/bin/pip install -r requirements-dev.txt

# 3. Run the test suite.
.venv/bin/python -m pytest

# 4. Launch the app.
.venv/bin/python main.py
```

## 4. Troubleshooting / common errors

### `ensurepip is not available` when creating the venv
Debian/Ubuntu ship `venv` and `pip` as separate apt packages
(`python3-venv`, `python3-pip`) that may not be installed, and installing
them needs `sudo`. If you don't have `sudo` available (or don't want to
touch system packages), bootstrap pip inside a pip-less venv instead — no
root required:
```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
```
If you *do* have sudo and prefer the system route:
```bash
sudo apt install python3-venv python3-pip
```

### The app window never appears / hangs on launch
Almost always a missing display. Check:
```bash
echo "$DISPLAY $WAYLAND_DISPLAY"
```
If both are empty, you're in a headless session — either enable X
forwarding (`ssh -X`), run on the machine's own desktop session, or (for
automated/CI testing only, not normal use) run with Qt's offscreen plugin:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python main.py
```

### `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`
Usually a missing system library that Qt's XCB backend depends on (common
on minimal Linux installs). On Debian/Ubuntu:
```bash
sudo apt install libxcb-cursor0
```

### Scan finishes but shows 0 files, or takes far longer than expected
- Check the folder isn't entirely covered by `DEFAULT_EXCLUDES` in
  `storage_ai/config.py` (`.git`, `node_modules`, `.venv`, `__pycache__`,
  etc. are always skipped).
- Very large trees (100k+ files) will be slower during duplicate hashing —
  that stage streams every byte of every same-size file. This is expected;
  see [Section 5](#5-design-choices-and-why) for why the funnel design
  minimizes this already.
- Permission-denied files/directories are silently skipped by design (a
  normal home directory almost always has at least one), not treated as an
  error.

### `PermissionError` / files won't trash or archive
`send2trash` and the archive move both need write access to the file and
its parent directory. Files owned by another user or on a read-only mount
will fail — the GUI reports these in a warning dialog rather than crashing,
and nothing else in the batch is rolled back.

### GUI freezes or throws `QBasicTinner`/`QObject` cross-thread warnings
This is a real Qt rule, not a cosmetic warning: **only the main thread may
touch widgets.** All scanning already runs on a background `QThread`
(`storage_ai/gui/scan_worker.py`) and reports back to the main thread only
via Qt signals connected to bound methods of `QWidget` subclasses — Qt
auto-detects the thread mismatch on those connections and queues them
correctly. If you extend the GUI and see this warning, the near-certain
cause is a signal connected to a **plain function or lambda** instead of a
method on a `QObject`/`QWidget` — Qt can't determine that receiver's thread
affinity, so it runs the slot directly on the worker thread instead of
queuing it. Fix: connect to a bound method of a widget/QObject, or wrap the
callback so it is one.

### `sqlite3.OperationalError: database is locked`
The SQLite file at `~/.storage_ai/storage_ai.sqlite3` is opened per-call
(see `database.py:connect`) and closed immediately after, so this shouldn't
happen in normal single-instance use. It generally means two instances of
the app (or an app instance plus a manual `sqlite3` shell) had the file open
at once. Close the other connection and retry.

### Forecast says "no growth trend detected" / days-until-full is empty
This is correct, not a bug, when there's no signal to extrapolate from: a
brand-new folder with all files at the same timestamp, or free space so
large relative to growth that the projection is effectively infinite. See
`prediction.py` — `bytes_per_day` of `0` intentionally yields
`days_until_full = None` rather than a misleading number.

### Tests fail with `ModuleNotFoundError: No module named 'storage_ai'`
Run pytest from the project root (`.venv/bin/python -m pytest`, not a bare
`pytest` from a different directory), or set
`PYTHONPATH=/home/paresh/Documents/OS_Storage_AI` explicitly. Python adds a
*script's own directory* to `sys.path`, not the current working directory —
this bites you if you invoke a script file from elsewhere by absolute path.

## 5. Design choices and why

Kept brief here — full detail in `docs/METHODOLOGY.md`.

| Choice | Why |
|---|---|
| Desktop GUI (PySide6), not CLI/web | Chosen directly by you at project kickoff; visual dashboard + one-click actions fit a storage-cleanup tool better than a report-only CLI. |
| Heuristics + local ML, not an LLM | No API cost, fully offline, deterministic and explainable — important for an academic write-up where you need to justify *why* a file was flagged. |
| Weak supervision for the unused-file classifier | There's no labeled ground truth for "this file is unused" on a real filesystem; bootstrapping labels from confident heuristic cases is the standard workaround. |
| Size → partial-hash → full-hash duplicate funnel | Avoids fully hashing every file in the tree; only genuine candidates reach the expensive full read. |
| send2trash / archive, never a hard delete | A storage tool that's occasionally wrong about "unused" must be recoverable — see `actions.py`. |
| SQLite snapshot history for forecasting | Free, zero-setup, local persistence; a real time series improves the forecast the more the tool is used. |

## 6. FAQ

**Q: Does this need an internet connection to run?**
No, only to install dependencies once. All scanning, hashing, ML, and
forecasting run locally.

**Q: Does it send any of my file data anywhere?**
No. There's no network call anywhere in `storage_ai/` — grep for
`requests`/`urllib`/`socket` if you want to verify.

**Q: Can it permanently delete files?**
Not through anything the app exposes. "Trash" uses the OS trash/recycle
bin; "archive" moves the file into `~/.storage_ai/archive/<date>/...`. Both
are reversible by the user afterward.

**Q: Why does the first scan's storage forecast feel rough?**
It's built from the files' own modification timestamps (see
`prediction.py`, `history_source == "file-timestamps"`) because there's no
scan history yet. Scan the same folder again later (a week or more apart)
and it switches to real snapshot-based regression, which is more accurate.

**Q: Why is a file I use often flagged as "unused"?**
Check `days_since_access` in the Unused Files tab. On Linux, some
filesystems mount with `relatime` or `noatime`, meaning "last accessed
time" doesn't update the way you'd expect. If your access times are
generally unreliable on your system, weight `days_since_modified` more
heavily when interpreting scores, or adjust `UNUSED_CONFIDENT_DAYS` /
`ACTIVE_CONFIDENT_DAYS` in `storage_ai/config.py`.

**Q: Can I point it at more than one folder, or schedule recurring scans?**
Not yet — this version scans one folder at a time, on demand. The database
schema already keys snapshots by `root_path`, so multi-folder support and a
scheduled/background scan are natural next additions, not architectural
changes.

**Q: How do I reset everything (start fresh)?**
Delete `~/.storage_ai/` — this removes the snapshot history, the audit log,
and the archive folder. It doesn't touch anything in the folders you've
scanned.

**Q: Where do I change the thresholds (what counts as "unused", the
recommendation score cutoff, excluded directories)?**
All in one place: `storage_ai/config.py`.
