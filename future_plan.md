# Future Plan — Storage AI

This is a forward-looking list of *not-yet-built* ideas, kept separate from
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) (documents what's built and
why) and [`sop.md`](sop.md) (how to run/troubleshoot what's built). Items
here are proposals to evaluate, not commitments — several depend on each
other and are ordered with that in mind.

## 1. Scalability

- **Multi-folder & scheduled scanning.** Today the app scans one folder at
  a time, on demand. The database schema already keys every snapshot by
  `root_path` (`database.py`), so this is additive, not a redesign: a
  small scheduler (cron, or a `QTimer` in a background service) that
  re-runs `pipeline.run_analysis` over a configured list of roots and
  writes each into its own snapshot history.
- **Incremental scanning.** A full re-scan currently re-walks and
  re-hashes everything. For a tree that's mostly unchanged since the last
  snapshot, skipping the hash step for any file whose `(size, mtime)`
  matches the last snapshot's record for that exact path would cut
  repeat-scan time substantially on large, slow-changing trees.
- **Parallel hashing for large trees.** The size → partial-hash →
  full-hash funnel (`hashing.py`, `duplicates.py`) already minimizes what
  gets fully read, but the full-hash pass itself is single-threaded.
  Multiprocessing across same-size candidate groups would help on
  100k+-file trees with many large duplicate candidates, without changing
  the funnel logic itself.
- **Multi-host aggregation.** The live-activity subsystem already answers
  "who's doing what on *this* server." The natural next step is the same
  question across a fleet: each host runs its own
  `watcher_service.py`/scheduled scan, and a small central collector (even
  just periodic SQLite → central-DB sync, no need for anything heavier)
  aggregates per-host snapshots and alerts into one inventory/dashboard.
- **inotify watch-limit handling at scale.** Watching a very broad root
  already skips permission-denied subtrees and tells the user how to
  raise `fs.inotify.max_user_watches` (see `sop.md`). At real scale (many
  broad roots, or many hosts) this could go further: detect the limit
  before hitting it and either prioritize watching the most
  active/highest-churn subtrees or warn with a concrete per-root watch
  count up front.
- **Batch application discovery.** `app_discovery.discover_app_storage_paths()`
  currently takes one app name at a time. On a shared server running many
  services, a batch mode that runs discovery for every process currently
  listed in `/proc` (deduplicated by binary name) would turn "find this
  one app's storage" into "here's a full storage inventory of everything
  running on this box right now" — useful for the exact
  multi-user/shared-server scenario this project targets.
- **SQLite contention under real multi-writer load.** Fine today (one
  writer at a time, opened-and-closed per call — see `sop.md`'s
  `database is locked` entry), but multiple simultaneous
  `watcher_service.py` instances or scheduled scans could start
  contending. WAL mode (`PRAGMA journal_mode=WAL`) is a cheap first step;
  a real server-based DB is very likely overkill unless multi-host
  aggregation above actually ships.

## 2. Using an OS-local LLM to enhance more features

Today, `llm_config_extractor.py` bundles its *own* small, dedicated model
(DistilBERT via `transformers`/`torch`, ~1GB of extra dependencies) purely
for tier 3 of application discovery. The idea here is broader: many users
already have a local LLM running for other purposes (e.g. an
[Ollama](https://ollama.com) server on `localhost:11434`, or a
`llama.cpp` server) — detecting and reusing *that*, instead of always
requiring the bundled model, avoids the extra download entirely for those
users, and opens the door to reusing it for more than just discovery.

- **Detect-and-prefer an already-running local LLM.** A lightweight,
  short-timeout HTTP check (e.g. `GET /api/tags` for Ollama) at startup,
  gated the same way `llm_config_extractor.is_available()` already gates
  the bundled model — if nothing is found, fall back to the bundled
  extractive model or skip the tier entirely, exactly as now. No network
  call ever leaves the machine (`localhost` only), preserving the
  fully-offline property this project has held throughout.
- **Natural-language explanations of recommendations.** Have the local
  LLM rephrase an already-computed recommendation ("47 duplicate files,
  212MB recoverable, oldest copy kept") into a plain-language sentence for
  the dashboard. Critically, the LLM would only ever *rephrase numbers
  and reasons this app already computed deterministically* — it would
  never be asked to decide what's unused or what's a duplicate itself.
  That decision stays exactly where it is today: `unused.py`,
  `duplicates.py`, `recommender.py`.
- **Free-text queries over scan results.** "Show me anything that looks
  like an old backup from last year" translated into filters over
  already-scanned metadata (extension, age, path, category) — the LLM
  only ever produces a filter, never touches file content or decides
  what to delete.
- **Suggesting a label for a genuinely unrecognized application.** When
  none of §8's deterministic tiers (process introspection, config
  parsing, curated table) can name an app, but process introspection or
  config discovery *did* find a plausible storage path, a local LLM could
  suggest a likely service name from the discovered config keys/path —
  presented as an unconfirmed suggestion a human accepts or rejects, never
  auto-applied to the curated table.
- **Drafting advisory text for new services.** `category_advisor.py`'s
  advice strings are hand-written today. A local LLM could draft a first
  pass for a newly-added service's rotation/retention advice from its
  known defaults, for a human to review before it ships — a writing aid,
  not a new decision-maker.

**Guardrail that applies to every item above, without exception:** any
LLM-produced text, label, or suggestion must be visibly marked as
AI-suggested in the UI, and must never be auto-applied to a destructive or
semi-destructive action (trash, archive, an edited config, a promoted
curated-table entry) without an explicit human confirmation step. This
matches the safety posture `actions.py` already holds for trash/archive,
and keeps the project's "explainable, not just automated" framing intact.
A full off-switch (disable all LLM tiers, bundled and local-server both)
should always remain available, so the app can run 100% deterministic when
that matters — e.g. for an academic write-up that needs every result to be
traceable to non-ML logic on demand.

## 3. The feedback loop these two sections both depend on

Several ideas above (auto-promoting a discovered app to the curated table,
personalizing which suggestions get surfaced, eventually auto-applying a
*repeat, previously-accepted* low-risk suggestion) all need the same
missing piece first: **recording what the user actually decided about a
suggestion**, not just what action they took. The `actions` table today
(`database.py`) is write-only — it logs that a trash/archive happened, not
whether a *recommendation* was accepted, rejected, or ignored, and it has
no equivalent at all for §8's discovery findings or any future LLM
suggestion.

This is the same gap already named honestly in
`docs/METHODOLOGY.md`'s "Known limitations" for the classifier/clustering
and for §8's discovery findings — closing it (a small
`suggestion_feedback` table: suggestion type, detail, shown-at, decision,
decided-at) is the prerequisite for essentially every personalization idea
in this document, and should come before, not after, any of them are
built.

## 4. Rough ordering

1. The feedback-loop table (§3) — small, and everything else compounds on
   top of it.
2. Multi-folder/scheduled scanning and incremental scanning (§1) — mostly
   mechanical extensions of what already exists.
3. Detect-and-prefer a local LLM server for the existing discovery tier
   (§2) — reduces the bundled model's footprint before adding new
   LLM-powered features on top of it.
4. The remaining local-LLM feature ideas (§2) and multi-host aggregation
   (§1) — largest scope, and benefit most from §3's detection layer and
   §1's per-host scan data already existing.
