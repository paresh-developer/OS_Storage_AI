# Methodology

## Problem framing

Given a directory tree, produce (1) duplicate files, (2) files that are
probably no longer needed, (3) a forecast of how fast storage is being
consumed, and (4) a ranked list of what to do about it. Each of these is
tackled with a distinct, explainable technique rather than a single opaque
model, so every output can be justified to the user.

---

## 📌 At a glance: what AI is actually developed here

> **Three classical machine learning techniques — a weakly-supervised
> classifier, a regression forecaster, and an unsupervised clustering
> model — chosen deliberately over an LLM for cost, explainability, and
> fully offline operation.** Everything else in the app (duplicate
> detection, path classification, live-activity alerts, recommendation
> ranking) is deterministic or rule-based by design, not ML — see "What's
> *not* AI" below. That split is a design choice, not a gap: ML is used
> exactly where a real prediction/classification/grouping problem exists,
> not sprinkled in for appearance.

| # | Technique | Where | What it does |
|---|---|---|---|
| 1 | **Classification** — `RandomForestClassifier` (scikit-learn, 100 trees, depth 6) | [`unused.py`](../storage_ai/unused.py) (§2 below) | Predicts whether a file is "likely unused." Trained via **weak supervision**: files untouched ≥180 days become confident positive labels, files touched ≤7 days become confident negative labels — nobody hand-labels a filesystem, so the model bootstraps its own training signal from a heuristic, then classifies the ambiguous middle. Falls back to the pure heuristic if there isn't enough confidently-labeled data yet. |
| 2 | **Regression** — linear least-squares (`numpy.polyfit`) | [`prediction.py`](../storage_ai/prediction.py) (§3 below) | Forecasts storage growth (bytes/day, days-until-full) from either real scan-history snapshots or, on a first-ever scan, a pseudo-timeseries built from the files' own modification timestamps. |
| 3 | **Clustering** — `KMeans` (scikit-learn) on standardized features | [`clustering.py`](../storage_ai/clustering.py) (§7 below) | Unsupervised grouping of files by size × staleness into archetypes like "Large & Stale" — independent of the classifier above, so agreement between the two techniques is a meaningful cross-check, not a repeated signal. |

### What's *not* AI (worth stating plainly, not hiding)

- **Duplicate detection** (§1) is deterministic cryptographic hashing
  (SHA-256), not a model — there's no uncertainty to model once hashes
  match.
- **Path classification** (§5) and **live-activity trend alerts** (§6) are
  explainable pattern-matching and threshold rules, not learned models —
  chosen so a server admin can see exactly *why* something fired, in the
  same terms it fired in.
- **Recommendation ranking** (§4) just sorts the outputs of the three ML
  techniques above by estimated savings; it doesn't learn anything itself.

---

## 1. Duplicate detection — exact-match funnel

Two files are only worth comparing if they're the same size. Among same-size
files, most non-duplicates differ in their first few bytes, so a 4KB partial
hash cheaply eliminates almost all remaining false candidates. Only the
survivors of both filters get a full streamed SHA-256 hash. This keeps the
expensive full-file read limited to genuine candidates instead of every file
in the tree — important once a scan covers tens of thousands of files.

Within a confirmed duplicate group, the oldest copy (by creation time) is
kept by default and the rest are recommended for removal, on the reasoning
that newer copies are more likely to be accidental re-downloads or "Save As"
artifacts than the original.

## 2. Unused-file scoring — weak supervision

There is no labeled dataset of "files that are actually unused" — nobody
hand-annotates their own filesystem. The tool instead uses **weak
supervision**:

1. Files untouched for ≥180 days are confidently labeled *unused* (1);
   files accessed within the last 7 days are confidently labeled *active*
   (0). Everything in between is left unlabeled — the ambiguous middle
   ground a pure threshold rule handles poorly.
2. If at least 20 confident examples exist for each class, a
   `RandomForestClassifier` (features: days since last access, days since
   last modification, log file size, and a file-type "decay risk" category)
   trains on the confident examples and scores every file, including the
   ambiguous ones. This lets the model pick up interaction effects a single
   threshold can't — e.g. a large media file that hasn't been *modified* in
   a year but *was* opened recently should score differently than a log
   file with the same access pattern.
3. If there isn't enough confident data yet (a small or freshly-touched
   tree), the same features feed a transparent weighted heuristic instead,
   so the tool still produces a usable ranking on the very first run.

Both paths output the same 0–1 "probability this file is unused" scale, so
downstream code doesn't need to know which one ran.

## 3. Storage growth forecasting — linear regression over two data sources

Forecasting needs a time series, and a single scan is a single point in
time. Two sources are used depending on what's available:

- **Repeated-scan history** (preferred): every scan of a root is persisted
  (timestamp, total size) to a local SQLite database. Once the same root has
  been scanned twice or more, a least-squares linear fit over these real
  data points gives bytes/day growth directly.
- **File-timestamp fallback** (first scan): with no scan history yet, the
  files' own modification timestamps are bucketed by month and treated as a
  cumulative pseudo time series, then fit the same way. This is a weaker
  signal — it assumes files are rarely deleted — but it means the tool gives
  a usable forecast immediately instead of requiring the user to wait weeks
  for enough real snapshots to accumulate.

The resulting growth rate is projected against current free disk space
(`shutil.disk_usage`) to estimate days-until-full and a 30-day projected
total.

## 4. Recommendation ranking

Duplicate groups, unused-file candidates (above a 0.6 score threshold), and
a storage-exhaustion warning (if the forecast horizon is within 30 days) are
merged into one list and sorted by estimated bytes recovered, with the
storage warning (which recovers nothing by itself) always sorted last. Each
recommendation carries a confidence value — 1.0 for exact duplicates (no
uncertainty once hashes match), the classifier/heuristic score for unused
files, and a slightly reduced confidence for a forecast based on the weaker
file-timestamp fallback.

## 5. Path classification and application/log awareness

The tool also classifies every scanned path into one of seven categories --
`system`, `log`, `cache`, `application_data`, `user_data`, `trash`, or
`other` -- and, when a path matches a well-known service default (e.g.
`/var/lib/postgresql`, `C:\Program Files\MongoDB`), attaches that service's
name as a bonus label (`storage_ai/path_classifier.py`).

This is deliberately **not** a config-file parser. PostgreSQL's
`data_directory` and MongoDB's `storage.dbPath` are user-configurable, so a
lookup table of "default" install locations is only ever a hint -- a real
production database is quite likely to have been pointed somewhere custom.
Rather than pretend a static table can resolve the *real* location, the
classifier matches by path pattern (curated absolute prefixes for known
top-level system/service directories, then generic name- and
extension-based rules -- e.g. any `*.log` file, any folder literally named
`cache`) and simply falls back to a generic category when nothing matches.
Reading actual service configs to find the true configured path was
considered and explicitly deferred: it would need one parser per service,
possibly elevated read permissions, and would still be one wrong assumption
away from misleading a user -- the pattern-based approach degrades
gracefully instead of confidently guessing wrong.

Config-change suggestions follow the same philosophy as the rest of the
app: a fixed, static advice string keyed to the matched category or service
(`storage_ai/category_advisor.py`) -- e.g. "consider log rotation" -- never
an attempt to read or edit a live service's actual configuration. Editing a
running database's config is a different risk class than trashing a stale
PDF: getting it wrong can mean data loss or a service that won't restart.

**Safety consequence:** files categorized `system` or `application_data`
are excluded from the unused-file, duplicate, and clustering analyses
entirely (`pipeline.py` computes `analyzable_records` before any of those
run). A live database's data files can look "unused" under naive
access-time heuristics while the database is very much running --
particularly on a filesystem mounted `noatime`, where access time never
updates at all -- so the staleness heuristics that are appropriate for a
Downloads folder are not safe to apply to a running service's own files.
These files still count toward the total size, forecast, and the
dashboard's category breakdown; they just never become a delete/archive
recommendation. True kernel/virtual filesystems (`/proc`, `/sys`, `/dev`,
`/run` on Linux) are excluded even earlier, at scan time, so they're never
walked at all (`scanner.py`'s `_should_prune_dir`).

## 6. Live activity monitoring

Everything above analyzes a folder as it is *right now*. This section covers
the separate, always-on piece: watching a folder continuously for
create/modify/delete events, in real time, with per-user activity trends --
built for the "multiple people on one server" case, where the interesting
question isn't "what's here" but "who's doing what, right now."

### What actually gets watched

`watcher.py` does not hand the root path to watchdog as a single
`recursive=True` watch. Early on, that's exactly what it did, and it made
watching anything broad (a whole home directory, or `/`) fail outright the
moment the recursive setup reached even one directory it couldn't read
(watchdog validates the entire tree synchronously before starting — see
"Two layers of user attribution" below for why that validation is
synchronous at all) — a permission-denied directory anywhere aborted
*everything*, not just that subtree.

Instead, `iter_watchable_dirs()` walks the tree itself first (the same
`os.walk`-based approach as `scanner.py`, reusing its exact pruning rule,
`should_prune_dir`), and schedules one non-recursive watch per directory
that survives:
- **Noisy/huge directories are skipped** — the same `DEFAULT_EXCLUDES` as
  scanning (`.git`, `node_modules`, `.venv`, ...), for two reasons at once:
  they'd otherwise burn a large share of the OS's inotify watch budget, and
  their churn (a `.git` object being written during every commit) would
  generate rate-based alerts that have nothing to do with real user
  activity.
- **True virtual filesystems are skipped** — `/proc`, `/sys`, `/dev`, `/run`
  on Linux, same `LINUX_VIRTUAL_FS_ROOTS` as scanning. `/proc` in particular
  is actively hostile to recursive watching: it has one ephemeral
  "directory" per running process that can vanish mid-walk.
- **Unreadable directories are skipped, not fatal** — `os.walk`'s default
  behavior (`onerror=lambda e: None`) already silently declines to descend
  into a directory it can't list; this just extends that same tolerance to
  watch *registration*, one directory at a time, rather than one
  all-or-nothing recursive call.

Because each directory gets its own **non-recursive** watch, a directory
created *during* monitoring needs its watch registered reactively —
`_Handler._extend_coverage()` does this in `on_created`/`on_moved` for new
directories, walking and scheduling the new subtree the same way, with the
same exclusion rules. This reintroduces a small, real trade-off: there's a
narrow window (sub-10ms in local testing) between a new directory appearing
and its watch being registered, during which a file written immediately
inside it could be missed. This is a known, accepted limitation of manually
managing recursive coverage rather than relying on a single kernel-level
recursive watch — real usage essentially never hits it (it requires writing
into a directory in the same instant it's created, with no gap at all).

None of this makes watching `/` itself *cheap* — it's still one inotify
watch per surviving directory, and a large filesystem can still approach
the OS's default 65536-watch limit (`LiveWatcherError` gives the exact
`sysctl` command to raise it if so) — but a permission-restricted subtree
no longer prevents watching everything else, which is what made it fail
outright before.

### Two layers of user attribution

A live filesystem watcher (`watcher.py`, via the cross-platform `watchdog`
library — Linux inotify / Windows `ReadDirectoryChangesW` / macOS FSEvents)
can tell you a path changed and roughly how, but the kernel-level
notification APIs it wraps have **no concept of which user or process did
it**. That's a hard boundary, not a missing feature to bolt on. So there are
two distinct, honestly-different-quality layers of attribution:

1. **File ownership** (always available, weak signal) — `os.stat()`'s
   `st_uid`, resolved to a username. Cheap, but it says who *owns* the file,
   not who just touched it, and it's simply unavailable for a delete (there's
   nothing left to `stat()` once the file is gone).
2. **Real per-operation attribution** (Linux only, requires setup) — the
   kernel's audit subsystem (`auditd`) tracks exactly which uid/pid/process
   performed a given syscall against a watched path. `audit_log.py` reads
   this via `ausearch -i` (interpreted output, so uid→username and syscall
   numbers→names are already resolved — reimplementing that translation
   table would mean tracking kernel-architecture-specific syscall numbers by
   hand, which is exactly the kind of thing that quietly breaks across
   kernel versions). `database.upgrade_event_attribution()` then correlates
   an audit event back to the matching stat()-attributed row (same path,
   timestamps within a few seconds of each other — both the watcher and
   auditd fire for the same real-world operation within a fraction of a
   second, so this tolerance is generous, not loose) and upgrades it in
   place. A delete recorded with no owner information gets its real acting
   user filled in this way, which is the whole reason this layer exists.

Layer 2 requires root to configure (`auditctl -w <path> -p wa -k
storage_ai_watch`) and to read audit records, and only exists at all if
`auditd` and its userspace tools are installed. **IP-address attribution was
explicitly scoped out**: an IP only means something if activity arrives over
a network protocol (Samba/NFS/SSH), and would require parsing *that
protocol's own connection logs* — a different integration per protocol, none
of which this app can assume exists. Continuously attributing file activity
to specific users on a shared server is also, plainly, user monitoring — it's
worth being something your organization's policy actually sanctions.

### Trend detection

`trend_detector.py` applies fixed, explainable threshold rules over a
sliding time window — a large file added, N deletes by one user within a
window, N modifications by one user within a window, or a general activity
burst — deliberately not a learned model, so a server admin can see exactly
why an alert fired in the same terms it fired in. Thresholds live as named
constants in that module, tunable the same way the rest of the app's
thresholds are (see `config.py` for the scan-side equivalents).

### Two ways to run it

- **From the GUI** (Live Activity tab): starts `watcher.py` directly in the
  desktop process for convenience/testing on one machine. Deliberately does
  *not* poll auditd (kept server-only, to avoid duplicating that machinery
  in the GUI thread) — attribution here is file-ownership only. Stops when
  the app closes.
- **As a standalone service** (`watcher_service.py`): the piece that makes
  "runs without stopping" actually true independent of the GUI. Both write
  to the same SQLite tables (`file_events`, `activity_alerts`), so the GUI
  tab works identically regardless of which one produced the data.
  ```
  python -m storage_ai.watcher_service /srv/shared
  python -m storage_ai.watcher_service --enable-audit /srv/shared   # needs root
  ```
  To keep it running across reboots on a headless server, install it as a
  systemd service:
  ```ini
  # /etc/systemd/system/storage-ai-watcher.service
  [Unit]
  Description=Storage AI live activity watcher
  After=network.target auditd.service

  [Service]
  ExecStart=/path/to/.venv/bin/python -m storage_ai.watcher_service --enable-audit /srv/shared
  Restart=on-failure
  User=root

  [Install]
  WantedBy=multi-user.target
  ```
  (Drop `--enable-audit` and `User=root` if you only want file-ownership
  attribution and don't need or want root privileges for this service.)

### What was and wasn't verified

The environment this was built in has no `auditd` installed and no root
access, so the auditd integration's live event-capture path could not be
exercised end to end here. What *was* verified:
- `audit_log.py`'s parser, thoroughly, against realistic sample text
  matching the documented, stable `ausearch -i` record format.
- `watcher.py`'s live event capture, against real inotify events (this
  needs no special privileges, unlike auditd).
- The full standalone service (`watcher_service.py`), run as a real
  subprocess against real file activity, including a correct clean shutdown
  on SIGINT/SIGTERM — its auditd-specific code path (`--enable-audit`)
  excepted, for the reason above.
- The GUI Live Activity tab, end to end, including real rapid-delete
  activity correctly triggering an alert.

If you deploy `--enable-audit` on a real server, verify the attribution
upgrade actually happens (a `file_events` row's `attribution_source`
changing from `stat` to `audit`) before relying on it for anything
consequential.

## 7. File clustering — unsupervised size/staleness grouping

`clustering.py` groups files with `KMeans` (scikit-learn) on exactly two
numeric features — log-scaled size and days since last access — scaled
with `StandardScaler` before fitting so neither feature's raw magnitude
(bytes range over many orders of magnitude; days do not) dominates the
distance metric the algorithm actually clusters on.

This is deliberately independent of the classifier in §2: that model is
trained toward a specific "is this file unused" label; clustering gets no
labels at all, it just finds structure in the data. So when a file is both
scored likely-unused *and* falls in the "Large & Stale" cluster, that's two
different techniques agreeing — a stronger signal than either alone, not a
restatement of the same one.

Cluster labels ("Large & Stale", "Small & Active", ...) are assigned
relative to *this scan's own* median size and age, not a fixed absolute
threshold, so "large" and "stale" mean something sensible whether the
folder is a code repository or a Downloads folder.

**Why 3 clusters, not a rounder number like 4:** the reason is external to
the clustering algorithm itself. The Dashboard's cluster scatter chart
needs a distinguishable color per cluster, and a scatter plot requires
every *pair* of series to be distinguishable (a viewer might compare any
two clusters, not just adjacent ones) — a stricter bar than, say, a
treemap's adjacent segments. The app's validated categorical palette only
clears that stricter bar for its first 3 slots (see
`storage_ai/gui/palette.py`); a 4th would put two colors on screen together
that a colorblind viewer genuinely cannot tell apart. Trading a finer
4-way split for a chart that's actually readable was a deliberate call,
made only after running the numbers through the palette's own validator's
documented results — not an oversight.

## 8. Application storage-path discovery — beyond the curated table

§5's curated table (`path_classifier.py`) only ever knows what it's been
explicitly taught: it can label `/var/lib/postgresql` as PostgreSQL, but it
has nothing to say about an application it's never heard of. This section
covers the actual answer to "how would this program find *any*
application's storage location, including ones not in that table" —
implemented as four tiers of decreasing reliability, tried in order, in
`app_discovery.discover_app_storage_paths()`. A later tier only runs when
every earlier one found nothing, because a cheaper and more certain answer
always beats a more expensive and less certain one.

### Tier 1: process introspection — observe reality, not a claim

`process_introspection.py` reads `/proc/<pid>/cmdline` (for a config/data
path passed as a command-line flag — most daemons accept one) and
`/proc/<pid>/fd/*` (every file the process actually has open right now).
Neither needs any advance knowledge of the specific application: the flag
pattern (`--config`, `-c`, `--datadir`, `-D`, ...) is generic, and open file
descriptors are just observed fact. This is the strongest signal precisely
because it's not inference — it's what the process is *really doing*, not
what a setting merely claims it will do. It only works while the process
is running, and reading another user's `/proc/<pid>/fd` needs the same
permission as reading their files directly (a normal, expected boundary,
not an error to route around).

Verified against real subprocesses (not mocked) in
`tests/test_process_introspection.py` — a Python process started with a
`--datadir` flag and an open file inside that directory, both signals
correctly recovered.

### Tier 2: structured config discovery — the declared setting

`config_discovery.py` globs a handful of generic candidate locations
(`/etc/{app}.conf`, `/etc/{app}/config.yaml`, `~/.config/{app}/...`, and
similar), parses whatever structured format it finds (JSON and TOML via
the standard library, YAML via `PyYAML`, `key = value` `.conf`/`.ini` files
via `configparser`), and then applies a **fuzzy match**: any key whose name
contains `path`/`dir`/`directory`/`storage`/`dbpath`/`datadir` (case
insensitive) and whose value looks like an absolute path
(`looks_like_absolute_path`) becomes a candidate, scored higher if that
path actually exists on disk. This is genuinely generic — it found
MongoDB's `storage.dbPath` and PostgreSQL's `data_directory` with the
exact same code, no per-app key-name knowledge at all.

Two real parsing bugs were caught by tests while building this, not just
theorized:
- `configparser` treats a section literally named `DEFAULT` specially and
  silently excludes it from `.sections()` — the synthetic section this
  module wraps flat `key = value` files in (for `.conf` files with no
  `[section]` header at all, e.g. `postgresql.conf`) is named `ROOT`
  instead, specifically to avoid that trap.
- `postgresql.conf`-style files quote their string values
  (`data_directory = '/var/lib/postgresql/14/main'`); the quotes have to
  be stripped before the path-shape check runs, or every quoted value
  fails it.

### Tier 3: the optional local LLM extractor — last resort, heavily gated

`llm_config_extractor.py` is reached only when a candidate config file
exists but didn't parse as any of tier 2's supported formats — a
freeform-text config, or a format this project's parser doesn't handle.
It's an **extractive** question-answering model (`distilbert-base-cased-
distilled-squad`, run via `transformers`/`torch`, CPU-only), not a
generative one, on purpose: "find the span of text in this document that
answers the question" is a narrower, safer task for a small model than
"write me the answer" — it can only ever return text that already appears
in the input, never invent a path from nothing.

This is an **optional dependency** (`requirements-llm.txt`, ~1GB combined
for `torch`+`transformers`+the model weights) — nothing else in this app
imports it, `is_available()` returns `False` gracefully if it isn't
installed, and `app_discovery.py` simply skips this tier. Core scanning,
classification, forecasting, and clustering never require it.

**Three real failure modes were found and worked around while building
this, not hypothesized in advance** (all reproduced as regression tests in
`tests/test_llm_config_extractor.py`):

1. *Question phrasing matters far more than expected for a model this
   small.* The identical text, the identical model, answered with two
   different but reasonable-sounding questions, swung from a correct,
   0.5+-confidence extraction to confidently extracting the bare key name
   instead of its value. There's no single phrasing that reliably works
   across realistic config styles, so this asks several genuinely
   different questions (`DEFAULT_QUESTIONS`) and keeps the best result —
   not one fixed prompt.
2. *The model's answer span often includes more than just the value* —
   the whole `dbPath = /mnt/data` line, or sometimes just the bare key
   name with no value at all. A regex (`_PATH_SUBSTRING_RE`) pulls the
   actual path-shaped substring out of whatever span comes back, which
   recovers a correct answer even from an imprecise span, and — just as
   usefully — finding no such substring in *any* attempted question's
   answer is itself a hard, reliable rejection signal.
3. *Confidence alone is not trustworthy.* This model was trained on SQuAD
   1.1, which contains no "unanswerable" examples. Fed a config with no
   storage path in it anywhere, at least one question phrasing
   **confidently (0.47 — comfortably above a naive 0.4 threshold) pointed
   at unrelated text as if it were the answer.** The regex path-shape
   extraction from finding #2 is what actually catches this (there is no
   path-shaped substring in nonsense text), not the score. This is why
   the shape check is mandatory and not skippable via the confidence
   parameter — a classical, deterministic check keeping a small model
   honest, the same pattern as everywhere else ML is used in this app
   (§2's heuristic fallback; §4's advisory text never auto-editing a
   config it merely read).

A discovered path from this tier is also weighted down by a fixed discount
(`_LLM_CONFIDENCE_DISCOUNT`) relative to the deterministic tiers when
`app_discovery.py` ranks findings, on top of already only ever being tried
last.

### A note on implementation, found while building this

As of the `transformers` version this was built against, the classic
single-span `pipeline("question-answering", ...)` convenience wrapper was
no longer registered under that task name (`pipeline()` raised `KeyError:
Unknown task`) — a real, verified change encountered while implementing
this, not a design preference. The underlying model classes
(`AutoModelForQuestionAnswering`, `DistilBertForQuestionAnswering`) are
still present, so this calls them directly: tokenize with
`return_offsets_mapping=True`, mask out any token belonging to the
question (via `sequence_ids()`) before taking the softmax-weighted
argmax of the start/end logits, then map the answer span's token indices
back to character offsets in the *original* context string rather than
decoding tokens directly — naive token decoding fragments paths on `/`,
`-`, and `.` and reinserts spaces that were never there (an earlier,
incorrect version of this code produced answers like `"mongo - storage"`
for exactly this reason).

## Safety

No recommendation is ever executed automatically, and no action is a hard
delete: "trash" sends the file to the OS trash/recycle bin (`send2trash`,
fully recoverable by the user), and "archive" moves it into a local dated
archive folder under the app's data directory rather than removing it. Every
action is logged to a SQLite audit table with a timestamp, type, path, and
size.

## Known limitations

- Duplicate detection is exact-match only; near-duplicates (e.g. a resized
  copy of the same photo, or two versions of a document) are out of scope.
- `st_ctime` on Linux is metadata-change time, not file-creation time; the
  "keep the oldest copy" rule is a reasonable but imperfect proxy for
  "keep the original."
- The file-timestamp forecast fallback assumes files aren't frequently
  deleted; a tree with heavy churn will overestimate growth until real
  snapshot history accumulates.
- The known-service labels in path classification are default-location
  hints, not verified facts -- a custom install (a non-default `data_directory`,
  a Dockerized database, a non-standard Windows install path) simply won't
  match and falls back to a generic category rather than a wrong label.
  This is intentional (see "Path classification" above) but means the
  service-specific advisory recommendations will under-fire on
  non-standard setups.
- Without `--enable-audit`, live activity user attribution is file-ownership
  based, not per-operation -- a shared-permission file edited by someone
  other than its owner will show the owner, not the editor, and deletes show
  no user at all. This is a fundamental limit of what any filesystem-level
  watcher (inotify, `ReadDirectoryChangesW`, FSEvents) can know, not a bug.
- The auditd integration's live event-capture path is unverified on a real
  auditd instance (see "Live activity monitoring" above for what was and
  wasn't tested, and why).
- Network-client (IP address) attribution is out of scope entirely -- it
  would require parsing a specific network protocol's own server logs
  (Samba/NFS/SSH), not anything visible to a filesystem watcher or auditd.
- A directory created during monitoring has a narrow (sub-10ms observed)
  race window before its watch is registered, during which a file written
  immediately inside it could be missed -- see "What actually gets watched"
  above.
- Watching very broad roots (a whole home directory, `/`) works -- a
  permission-denied subtree is skipped rather than fatal -- but is not
  cheap: it's still one inotify watch per surviving directory, and can
  still approach the OS's watch-count limit on a large enough filesystem.
- Process introspection (§8, tier 1) only finds a storage path while the
  process is actually running, and reading another user's `/proc/<pid>/fd`
  needs the same permission as reading their files directly -- neither is
  a bug, just what `/proc` visibility actually allows.
- Structured config discovery (§8, tier 2) only checks a fixed list of
  generic candidate locations (`/etc/{app}...`, `~/.config/{app}/...`); an
  application whose config lives somewhere genuinely unconventional won't
  be found there at all, regardless of format.
- The optional LLM extractor (§8, tier 3) is extractive, not generative --
  it can only return text that already appears in the config, never
  invent a path -- but it is still a small model on a narrow SQuAD-style
  task: it can extract the wrong span, and its own confidence score is not
  trustworthy on its own (a verified case scored 0.47 on text with no
  storage path at all). The mandatory path-shape check catches that
  specific failure mode, but a similarly-shaped wrong string (e.g. an
  unrelated absolute path mentioned nearby) could still slip through
  uncaught.
- None of §8's tiers currently feed back into `path_classifier.py`'s
  curated table -- a discovered path is surfaced as a finding, not
  automatically promoted into a permanent classification rule. Doing that
  safely would need the human-in-the-loop confirmation step described in
  "Known limitations" for §2/§4 (recording a user's accept/reject decision
  on a suggestion), which doesn't exist yet either.
