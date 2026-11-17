# Doomsday Watch

Hourly ticket-availability tracker for **Avengers: Doomsday** in **Bengaluru**, for
**17 Dec 2026** and **18 Dec 2026**, across six theatres on **District** and
**BookMyShow**. Static dashboard, no paid services, runs with your computer off.

> **Data honesty first.** Every show, format, price and seat count below comes from
> a public source page. Missing data is shown as missing. Seat drops are
> _availability signals_, never claims that tickets were sold. No seat numbers are
> invented when a platform does not publish a seat map.

---

## What it does

- Watches **six Bengaluru theatres** every hour via GitHub Actions.
- Detects show listings, new showtimes, **formats** (2D, 3D, IMAX 3D, **Infinity
  Vision 3D**, 4DX, ICE, Dolby, ScreenX, P[XL], laser), booking openings, sell-outs,
  price changes and availability drops between snapshots.
- Renders a dark cinematic dashboard: hero status, stat cards, format/date/platform
  filters, per-theatre show rows, and a seat-comfort guide.
- Keeps an append-only history of snapshots and change events in the repository.
- Sends **Telegram**, **ntfy.sh** and generic webhook alerts (all free), plus
  in-browser notifications while the tab is open.
- Degrades honestly: if BookMyShow blocks the runner, the run is marked `partial`,
  the last BookMyShow snapshot is preserved and labelled, and District keeps working.

### Cloud access reality (verified 2026-11-17)

District serves Bengaluru pages from India but answers GitHub-hosted runners
(Azure/US IP `40.86.12.32`) with Akamai **HTTP 403 "Access Denied"**, even with
browser headers. BookMyShow's showtimes remain Cloudflare-blocked. The monitor
therefore records an honest **degraded** run from the cloud, preserves the last
successful listings (with their age), and keeps the hourly snapshot/deploy loop
running. It does **not** proxy around the block. Local runs from an Indian
connection still collect fresh data. See `docs/DEPLOYMENT.md` for options.

### Current live state (last committed run)

| | |
|---|---|
| Status | `partial` — District OK, BookMyShow showtimes blocked by Cloudflare |
| Shows found | 20 (all Infinity Vision 3D; 4 of them 4DX), 3 of 6 theatres |
| 17 Dec 2026 | 20 shows · 3 theatres |
| 18 Dec 2026 | **0 shows** — not released by any source yet, so none are shown |
| IMAX 3D | 0 (Infinity Vision is deliberately **not** counted as IMAX) |

This is real captured data in `data/latest.json`; it changes as platforms release
more shows.

---

## Architecture

```
GitHub Actions (cron: 5 * * * *)
        │
        ├── District adapter ──┐
        └── BookMyShow adapter ─┤  httpx, timeouts, retries, robots.txt
                                 ▼
                          monitor.run_monitor()
                                 │
              ┌──────────────────┼───────────────────┐
              ▼                  ▼                   ▼
        diff vs previous    notify (Telegram,    store snapshots,
        snapshot            ntfy, webhook)       events.jsonl, runs.jsonl
                                 │
                                 ▼
                    git commit data/ + build Vite site
                                 │
                                 ▼
                     GitHub Pages (static dashboard)
```

- **Backend:** Python 3.11+, `httpx` only (stdlib dataclasses, json, re). No
  database server, no ORM.
- **Frontend:** React 18, Vite 5, TypeScript, Tailwind CSS 3, Recharts. HashRouter
  so it works on GitHub Pages without rewrite rules.
- **Storage:** the git repository itself. `data/` is committed every hour.
- **Cost:** ₹0. GitHub Actions free minutes for public repositories, GitHub Pages
  free for public repositories, Telegram/ntfy free.

Full details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

---

## Quick start (local)

Requirements: Python 3.11+, Node 20+.

```bash
git clone <your-fork-url> doomsday-watch
cd doomsday-watch

# Backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Safe check: fetch + diff only, writes nothing
PYTHONPATH=backend python -m doomsday_watch --config config/monitor.json --data data run --dry-run

# Real monitoring pass (writes data/latest.json, history and a snapshot)
PYTHONPATH=backend python -m doomsday_watch --config config/monitor.json --data data run

# Tests
pip install -r requirements-dev.txt
PYTHONPATH=backend pytest backend/tests -q

# Dashboard
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

The dev server copies `data/` into `frontend/public/data` before starting
(`predev`), so the UI shows the same committed snapshot the live site uses.

### Commands

```bash
# run one snapshot (the hourly job uses this)
PYTHONPATH=backend python -m doomsday_watch --config config/monitor.json --data data run

# accessibility report only; writes nothing
PYTHONPATH=backend python -m doomsday_watch probe

# send a test alert to every configured channel
PYTHONPATH=backend python -m doomsday_watch notify-test

# validate config + latest snapshot
PYTHONPATH=backend python -m doomsday_watch validate

# optional local API (FastAPI)
pip install -r requirements-api.txt
PYTHONPATH=backend python -m doomsday_watch serve --port 8000
```

Useful `run` flags: `--dry-run` (fetch, diff and report **without writing any
snapshot/history/cache file or sending alerts**), `--skip-notifications`, and
`--github-summary` (writes to `$GITHUB_STEP_SUMMARY`). Global options `--config`
and `--data` must come **before** the subcommand:

```bash
PYTHONPATH=backend python -m doomsday_watch --data data run --dry-run
```

---

## Deploy for free (GitHub only)

1. Push this repository to GitHub as a **public** repo (Pages on private repos
   requires a paid plan).
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
3. **Settings → Actions → General → Workflow permissions:** allow read and write
   (the hourly job commits `data/`).
4. Add notification secrets (optional): **Settings → Secrets and variables →
   Actions** → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NTFY_TOPIC`,
   `NOTIFY_WEBHOOK_URL`. Optionally add a repository **variable**
   `DASHBOARD_URL=https://dv-06.github.io/doomsday/` so alerts link to the site.
5. Install the OpenWrt collector from [`router/`](router/README.md) on an
   Indian-egress router, add its fine-grained PAT and enable the hourly cron.
6. Your dashboard is at `https://<user>.github.io/<repo>/`.

Normal collection is done by the Indian-egress OpenWrt collector
(`router/collect.sh`), which uploads only `data/inbox/district.json`. The
`Ingest NAS snapshot` workflow validates it and runs the existing Python
normalisation/diff/history pipeline without fetching the network. `Deploy
dashboard` then builds and publishes Pages. The old `Hourly ticket watch`
workflow has **no schedule**; it remains only as a manual fallback and refuses
to overwrite a NAS snapshot unless `force=true` is set.

All workflows share the `doomsday-watch-pages` concurrency group, so they queue
instead of deploying competing builds. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for PAT setup, scheduler caveats,
custom domains and troubleshooting.

> A push made with the default `GITHUB_TOKEN` does **not** trigger other workflows.
> That is why the monitor deploys Pages itself instead of relying on the push to
> trigger a separate deploy workflow.

---

## Notifications

Credentials are read **only** from environment variables or Actions secrets; the
config file stores variable names, never values.

### Telegram (free)

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Message your new bot once, then get your chat id from
   [@userinfobot](https://t.me/userinfobot) (or the `getUpdates` API).
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

### ntfy.sh (free, no account)

Pick an unguessable topic and subscribe to it in the ntfy app:

```bash
export NTFY_TOPIC="doomsday-bengaluru-7f3c9a"
PYTHONPATH=backend python -m doomsday_watch notify-test
```

### Testing

```bash
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
PYTHONPATH=backend python -m doomsday_watch notify-test
```

Alerts fire only for event types listed in `notifications.notify_on`, and each
event id is deduplicated in `data/state.json`, so the same event is never sent
twice. Set `DASHBOARD_URL` to include a link in messages.

---

## Configuration (`config/monitor.json`)

| Key | Purpose |
|---|---|
| `movie.district.content_id` / `slug` | District movie page identity (`176735`). |
| `target_dates` | `2026-12-17`, `2026-12-18` (IST calendar dates). |
| `monitoring.interval_minutes` | Displayed interval; the real cadence is the workflow cron. |
| `monitoring.request_timeout_seconds` / `max_retries` | HTTP resilience. |
| `monitoring.user_agent` | Descriptive UA; identifies this as a personal tracker. |
| `theatres[].platform_ids.district` | Exact venue ID used for matching. |
| `theatres[].aliases` | Accepted source names for verification. |
| `retention` | Snapshot pruning (hourly 72, daily 90). |
| `sources.*.enabled` | Disable an adapter without deleting code. |
| `notifications` | Channel enable flags and env-var names. |

### Venues tracked

| Watchlist name | District venue | ID |
|---|---|---|
| Lulu Global Mall, Rajajinagar | Cinepolis Lulu Global Mall | `56450` |
| Orion Mall, Dr Rajkumar Road | PVR Orion Mall | `1022299` |
| Mantri Square Mall, Malleshwaram | INOX Mantri Square | `1020725` |
| GT World Mall, Magadi Road | PVR GT World Mall | `1022303` |
| Miraj Cinemas, Sunkadakatte | Miraj Cinemas: TGN Lotus Elite | `52080` |
| Global Mall, Mysore Road | PVR Global Mall | `1022307` |

Deliberately excluded lookalikes (documented in config and shown in the UI):
Cinepolis Orion Avenue Mall Banaswadi (`925`), INOX Central Mantri Junction JP Nagar
(`1020726`), Cinepolis VIP Lulu (`56451`).

---

## Source access and limits

| Platform | What works | What does not |
|---|---|---|
| **District** | Public movie page with server-rendered `__NEXT_DATA__`: cinema list, sessions, screen/format, prices, area-wise seat availability, booking links. | No public seat-layout page (empty payload), so no exact seat numbers. |
| **BookMyShow** | Movie list and movie page (release date, existence). | Showtimes and seat pages return a Cloudflare challenge (`403`). Treated as blocked. |

What the monitor **never** does: solve CAPTCHAs, rotate proxies/identities, log in,
join queues, call private APIs, or scrape at a rate beyond one request per page per
hour. `robots.txt` is checked and cached (24h). When a source blocks the runner the
run is marked `partial`/`blocked`, stale data is labelled with its age, and no shows
are deleted from the dashboard.

### Seat recommendations

District publishes block-level availability, not seat maps. The tracker therefore:

- ranks published blocks by comfort (recliner > prime > executive > normal) and
  free-seat ratio;
- returns a **zone recommendation** plus a depth percentage (front/mid-rear) for the
  screen, labelled _heuristic_;
- never invents seat numbers such as "J14".

If a platform ever serves a real layout, `seats.recommend_from_layout()` scores
seats by centre-x, mid-rear y-depth and edge avoidance. BookMyShow seat maps are
not accessible, so this path is not used today.

---

## Data and history

- `data/latest.json` — full current snapshot used by the UI.
- `data/snapshots/YYYY/MM/<UTC>.json` — immutable hourly snapshots.
- `data/history/events.jsonl` — append-only change log.
- `data/history/runs.jsonl` — append-only run log for the trend chart.
- `data/meta.json`, `data/state.json`, `data/sources.json` — schedule, notification
  dedupe and per-source health.

Schemas, normalised format enum and invariants are documented in
[`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md).

---

## Tests

```bash
pip install -r requirements-dev.txt
PYTHONPATH=backend pytest backend/tests -q
```

40 tests cover CLI parsing, dry-run isolation, normal and partial runs, NAS inbox
ingestion, duplicate/stale payload protection, format normalisation (including
Infinity Vision ≠ IMAX), District parsing against a trimmed real fixture, seat
heuristics, diff/notification rules, snapshot retention, and the end-to-end
pipeline with blocked sources.

Frontend checks:

```bash
cd frontend
npm run typecheck
npm run build
```

---

## Known limitations

1. **BookMyShow showtimes are blocked** from both GitHub's runners and the router
   (Cloudflare). Coverage is District-only; the UI keeps BookMyShow visibly blocked
   instead of pretending it was checked.
2. **18 Dec 2026 has no shows yet.** The tracker shows zero rather than guessing.
3. **GitHub cron is best-effort.** Runs can be delayed by minutes during peak load;
   scheduled workflows pause after 60 days of repository inactivity (this project's
   hourly data commits keep it active).
4. **Seat maps are not public**, so recommendations are zone-level heuristics.
5. Venue IDs and the movie content id are pinned manually; if a platform changes its
   catalogue the verification panel will show a mismatch rather than silently
   mapping to the wrong cinema.
6. GitHub Pages is static; the optional FastAPI service is for local use only.
7. Overall run status is `partial` whenever any enabled source is blocked or
   partial, even if another source returned full data — incomplete coverage is
   never presented as complete. `ok` requires every source to be fully healthy.
8. **GitHub-hosted runners cannot reach District** (geo/datacenter 403) or
   BookMyShow showtimes (Cloudflare). The scheduled US collector is therefore
   disabled; fresh District data comes from the Indian-egress OpenWrt collector.

---

## Repository layout

```
backend/doomsday_watch/     monitor, adapters, diff, store, seats, notify, api
backend/tests/              pytest suite + trimmed District fixture
config/monitor.json         movie, dates, theatres, sources, retention
data/                       committed snapshots, history, derived files
frontend/                   React + Vite dashboard (syncs data/ before build)
router/                     OpenWrt ucode collector, install/uninstall, docs
.github/workflows/          NAS ingest + Pages deploy, manual monitor fallback
docs/                       architecture, data schema, deployment
.env.example                every supported environment variable
```

## Licence / attribution

Personal, non-commercial tracker. Movie title, poster and showtime data belong to
their respective rights holders and platforms. No ticket inventory is resold and no
booking is automated. Please keep the request rate polite and respect each
platform's terms.
