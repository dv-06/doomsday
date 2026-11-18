# Architecture

## Goals and constraints

- ₹0 running cost, no servers to keep alive.
- Real data only; no fabricated shows, prices, seat numbers or seat maps.
- Hourly history with change detection kept in version control.
- Honest degradation when a platform blocks automation.
- Works with the owner's PC off.

The design follows from one constraint: **a static site cannot scrape.** Scraping
happens in scheduled GitHub Actions jobs, the results are committed to the repo, and
the static site reads the committed JSON.

## Components

```
┌──────────────────────────── GitHub repository ────────────────────────────┐
│                                                                           │
│  config/monitor.json ──► Python monitor ──► data/latest.json              │
│                              │              data/snapshots/**             │
│                              │              data/history/*.jsonl         │
│                              ▼                                            │
│                        Telegram / ntfy / webhook                          │
│                                                                           │
│  frontend/ (React) ◄── frontend/public/data (copied at build)             │
│        │                                                                  │
└────────┼──────────────────────────────────────────────────────────────────┘
         ▼
   GitHub Pages (static, HashRouter)
```

### Backend modules (`backend/doomsday_watch/`)

| Module | Responsibility |
|---|---|
| `config.py` | Load/validate JSON config, IST helpers, dataclasses. |
| `http.py` | Shared `httpx` client: timeouts, bounded retries with jitter, robots.txt cache, challenge detection. |
| `formats.py` | Ordered regex normalisation → format enum; Infinity Vision 3D kept separate from IMAX 3D; comfort/depth guidance per format. |
| `models.py` | `make_show()`, `TheatreObservation`, `SourceResult`, totals summarisation. |
| `sources/district.py` | Parse `__NEXT_DATA__` sessions, map cinemas by exact ID, build show records, venue verification. |
| `sources/bookmyshow.py` | Probe movie list/movie page; parse screening JSON-LD if served; report blocked showtimes honestly. |
| `seats.py` | Layout-based scoring (unused today) and block-level heuristic recommendations. |
| `diff.py` | Typed events between two snapshots; refuses destructive diffs for unhealthy sources. |
| `notify.py` | Telegram, ntfy, webhook senders; dedupe via `state.notified`; batching. |
| `store.py` | Load/write snapshots, history, meta, sources; retention pruning. |
| `monitor.py` | Orchestration: run adapters, merge observations, build snapshot, diff, notify, persist. |
| `api.py` | Optional FastAPI read API + token-protected `POST /run`. Not used by Pages. |
| `cli.py` | `run`, `probe`, `notify-test`, `validate`, `serve`. |

### Frontend (`frontend/src/`)

- `App.tsx` — hash-router shell, header status, toasts, 5-minute polling, settings
  context.
- `pages/Dashboard.tsx` — hero, stat cards, latest changes, filters, theatre grid.
- `pages/History.tsx` — Recharts trend + grouped change timeline with filters.
- `pages/Sources.tsx` — per-source evidence, venue verification table, exclusions,
  access rules.
- `pages/Settings.tsx` — local display/alert preferences, schedule docs, repo-config
  export.
- `lib/data.ts` — fetch/cache JSON, IST formatters, tone/event label maps.
- `components/TheatreCard.tsx` — per-date show rows, format badges, seat guide,
  platform observations, booking links.

## Two collection paths

**Normal path (Indian egress):** the OpenWrt router runs
`/opt/doomsday-watch/collect.sh` hourly. It fetches one District page, extracts
`__NEXT_DATA__` with `ucode`, filters the six cinema IDs and two target dates,
validates the compact payload, and uploads `data/inbox/district.json` with the
Contents API only when its SHA-256 changes. BookMyShow is never fetched there.

**Ingestion path:** `.github/workflows/ingest.yml` runs on that push, calls
`doomsday_watch ingest`, and reuses the existing `district` mapping plus the
normal diff/history/store/notify pipeline. No network source is contacted.
`pages.yml` deploys after ingestion completes via `workflow_run`.

**Fallback path:** `monitor.yml` has no schedule. A manual run makes the live
fetch, but exits early if `data/meta.json` has NAS provenance unless `force=true`
is explicitly selected.

## One monitoring run

1. Load and validate `config/monitor.json`.
2. Load the previous snapshot from `data/latest.json`.
3. For each enabled source (isolated try/except):
   - check robots.txt (cached 24h);
   - fetch one or two public pages with timeout + retry/backoff;
   - detect challenge pages and classify `blocked` instead of parsing garbage;
   - parse shows, formats, prices, availability and booking links;
   - verify venue identity by platform ID.
4. Merge observations. If a source is unhealthy, carry forward its previous shows
   and mark them stale with an age (the diff never deletes them).
5. Build sorted shows and totals; `bookable_shows` = shows with availability + link.
6. Diff against the previous snapshot → typed events.
7. Notify configured channels for allowed event types; dedupe by event id.
8. Write `latest.json`, `sources.json`, `meta.json`, a snapshot, and append to
   `events.jsonl` / `runs.jsonl`; prune old snapshots.
9. Exit `3` when every source is externally blocked (Actions warns, preserves data
   and continues), and `2` only for a genuine monitor failure.
10. Dry run performs steps 1–7 with a throwaway cache and an empty in-memory diff,
    then returns before step 8: no snapshot, history, state, meta or cache file is
    written, and no notification is sent.

## Failure handling

| Failure | Behaviour |
|---|---|
| Timeout / connection reset | Up to `max_retries` with exponential backoff; source marked `partial`/`error`. |
| Cloudflare challenge | Detected by status/body markers → `blocked`; no parsing of the challenge page. |
| One theatre missing from source | That theatre keeps its previous shows, labelled stale; run stays `partial`. |
| All sources fail/block | Run is `degraded`, previous shows preserved with age, a degraded snapshot is stored, CLI exits `3` (workflow warns but commits/deploys). |
| Notification channel fails | Logged, other channels still attempted; run data is still saved. |
| Push conflict in Actions | `pull --rebase --autostash` and retry up to 3 times. |
| Router memory below 80 MB | Collector exits before fetching; current snapshot untouched. |
| Router parse/validation failure | No upload; state and the last GitHub snapshot are preserved. |
| NAS payload stale/malformed | Ingest exits 2 before writing; last good snapshot remains. |
| Duplicate NAS payload | Canonical hash matches provenance; no data or history is appended. |
| GitHub API 409 | Collector refreshes the file SHA and retries once. |
| Pages deploy fails | Data commit already exists; next successful run redeploys. |

## Key decisions

- **Repo as database.** No free-tier database limits, no credentials, and every
  snapshot is auditable in git history. Cost: repository growth (bounded by
  retention; history JSONL is small text).
- **Server-rendered District page instead of its API.** One request per run, public,
  and covered by robots.txt.
- **No anti-bot circumvention.** Blocked means blocked. The UI exposes it.
- **HashRouter.** GitHub Pages cannot rewrite paths; hashes avoid 404s for deep links.
- **Availability ≠ sales.** Diff wording and UI copy enforce this distinction.
- **One deployer at a time.** NAS ingest, the manual monitor and the Pages
  workflow share a concurrency group; deploys are queued, never raced.
- **Indian collection, cloud processing.** The router does only the geo-blocked
  fetch and compact extraction; GitHub keeps ownership of normalisation, diff,
  history and alerts, avoiding a second data model.
- **Manual cloud fallback is fenced.** The US monitor cannot overwrite NAS data
  without an explicit `force=true`.
- **Overall status is conservative.** `ok` means every enabled source was fully
  healthy; one partial/blocked source makes the whole run `partial`.
- **IST everywhere.** Dates are stored as IST calendar dates so a 00:30 show on
  18 Dec does not drift to 17 Dec in UTC.
- **Seat heuristics, not invented seats.** The platform has no public seat map, so
  the product returns a zone/depth recommendation and says it is heuristic.

## Extension points

- Add a theatre: add its exact `platform_ids.district` ID to config, verify the name
  in the Sources page, no code change.
- Add a date: append to the movie's `movies[].target_dates`.
- Add a movie: add a `movies[]` entry with its own District `content_id`, dates and
  optional `required_format_keys`. No new snapshot or ingest code is needed.
- Add a source: implement the adapter interface in `sources/`, register it in
  `monitor.ADAPTERS`, then enable it in config.
- Change cadence: edit the root cron on the router and
  `monitoring.interval_minutes` (display only).
- Real seat maps: feed a layout into `seats.recommend_from_layout()` and surface the
  returned seat labels in `TheatreCard`.
