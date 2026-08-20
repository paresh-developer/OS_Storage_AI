# Methodology

## Problem framing

Given a directory tree, produce (1) duplicate files, (2) files that are
probably no longer needed, (3) a forecast of how fast storage is being
consumed, and (4) a ranked list of what to do about it. Each of these is
tackled with a distinct, explainable technique rather than a single opaque
model, so every output can be justified to the user.

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
