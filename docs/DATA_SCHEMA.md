# Data schema and invariants

Everything the dashboard shows is derived from files in this repository. There is
no database server and no hidden API: `data/` is the database.

## Directory layout

```
data/
├── latest.json                 # newest full snapshot (what the site renders)
├── meta.json                   # run counter, schedule, last success/failure
├── state.json                  # notification dedupe + last observed state
├── sources.json                # last per-source health/evidence
├── snapshots/
│   └── 2026/12/<UTC timestamp>.json   # immutable hourly snapshots
└── history/
    ├── events.jsonl            # append-only change log
    └── runs.jsonl              # append-only run log (for charts)
```

`frontend/scripts/sync-data.mjs` copies `data/` into `frontend/public/data`
before each build, so the static site always ships the committed snapshot.

## `latest.json`

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-11-17T20:00:00+05:30",
  "checked_at": "2026-11-17T20:00:00+05:30",   // IST ISO-8601
  "status": "ok | partial | degraded",
  "movie": {
    "title": "Avengers: Doomsday",
    "release_date": "2026-12-17",
    "language": "English",
    "duration_minutes": 165,                    // null when unknown
    "poster": "https://...",                    // public CDN URL or null
    "target_dates": ["2026-12-17", "2026-12-18"],
    "district_url": "https://www.district.in/movies/...",
    "bookmyshow_url": null
  },
  "totals": {
    "theatres_monitored": 6,
    "theatres_with_listings": 3,
    "shows_total": 20,
    "shows_3d": 20,
    "shows_infinity_vision_3d": 20,
    "shows_imax_3d": 0,
    "bookable_shows": 20,
    "seats_available_total": 0,
    "formats": ["4dx", "infinity_vision_3d"],
    "dates": {
      "2026-12-17": { "shows": 20, "theatres": 3, "shows_3d": 20, "shows_infinity_vision_3d": 20 }
    }
  },
  "theatres": [
    {
      "id": "lulu-global-mall",
      "name": "Lulu Global Mall, Rajajinagar",
      "area": "Rajajinagar / Magadi Road",
      "listed": true,
      "verified": true,
      "verification": {
        "district": { "status": "verified", "source_name": "Cinepolis Lulu Global Mall",
                      "source_id": "56450", "checked_at": "..." }
      },
      "platforms": {
        "district": {
          "status": "ok | partial | blocked | not_listed | unavailable | stale",
          "checked_at": "...", "last_success_at": "...",
          "message": "human readable",
          "venue": { "id": "56450", "name": "...", "url": "https://..." },
          "raw_show_count": 8
        }
      },
      "shows": [
        {
          "id": "district:56450:2026-12-17:19:10:infinity_vision_3d",
          "theatre_id": "lulu-global-mall",
          "platform": "district",
          "date": "2026-12-17",           // IST calendar date
          "start": "19:10",               // 24h IST, no timezone stored per show
          "format_raw": "INFINITY VISION 3D",
          "format": "infinity_vision_3d", // normalised enum, see below
          "format_label": "Infinity Vision 3D",
          "screen": "Audi 6",
          "language": "English",
          "price_min": 420,               // INR, null when absent
          "price_max": 780,
          "currency": "INR",
          "seats_available": 0,           // source-reported; 0 ≠ confirmed sales
          "seats_total": 0,
          "areas": [                      // per-block availability when published
            { "name": "PRIME", "price": 780, "available": 12, "total": 120 }
          ],
          "bookable": true,
          "booking_url": "https://www.district.in/...",
          "source": "district"
        }
      ],
      "booking": {
        "url": "https://www.district.in/...",
        "source_urls": [{ "platform": "district", "url": "https://..." }]
      }
    }
  ],
  "sources": [
    {
      "source": "district",
      "status": "ok | partial | blocked | error",
      "checked_at": "...", "last_success_at": "...",
      "message": "...",
      "evidence": { "http_status": 200, "latency_ms": 812, "attempts": 1 },
      "notes": ["..."],
      "movie": { "url": "https://www.district.in/..." }   // optional
    }
  ],
  "excluded_lookalikes": [
    { "name": "Cinepolis Orion Avenue Mall Banaswadi", "district_id": "925", "reason": "Different mall..." }
  ]
}
```

### Normalised format enum

`imax_3d`, `imax_2d`, `infinity_vision_3d`, `infinity_vision_4dx_3d`, `4dx`, `ice_3d`, `3d`, `2d`, `dolby_cinema`,
`screenx`, `pxl`, `laser`, `imax`, `unknown`.

Infinity Vision 3D is intentionally **separate** from IMAX 3D. `format_raw`
keeps the platform's original string so the mapping can be audited.

## `history/events.jsonl`

One JSON object per line, append-only, never pruned:

```jsonc
{
  "id": "evt_...",              // stable hash of type + theatre + show + snapshot
  "type": "theatre_listed | first_show | show_added | show_removed | format_added |
           booking_opened | sold_out | seats_dropped | price_changed | date_added |
           source_blocked | source_recovered",
  "severity": "info | low | medium | high",
  "created_at": "2026-11-17T20:00:00+05:30",
  "theatre_id": "lulu-global-mall",
  "theatre_name": "Cinepolis Lulu Global Mall",
  "platform": "district",
  "date": "2026-12-17",
  "start": "19:10",
  "format": "infinity_vision_3d",
  "message": "New 19:10 Infinity Vision 3D show at ...",
  "details": { }
}
```

Rules enforced in `diff.py`:

- A show is only marked removed if the source that listed it is healthy. When a
  source is `blocked`/`partial`, its last known shows are carried forward and the
  event is `source_blocked` instead.
- `seats_dropped` messages say "availability drop", never "tickets sold".
- Events are deduplicated by id against `state.json` before notifying.

## `history/runs.jsonl`

```jsonc
{
  "checked_at": "...",
  "status": "ok | partial | degraded",
  "trigger": "schedule | manual",
  "duration_ms": 2450,
  "totals": { "shows_total": 20, "shows_3d": 20, ... },
  "sources": { "district": "ok", "bookmyshow": "blocked" },
  "events_count": 0
}
```

Used by the history chart (last 168 runs, about one week).

## `meta.json`

Run counter, `last_success_at`, `last_failure_at`, `monitoring.interval_minutes`,
`monitoring.next_check_at` and a human note about GitHub's best-effort scheduler.

## Retention

`retention.hourly_snapshots` (72) and `retention.daily_snapshots` (90) in
`config/monitor.json` control `store.prune()`. History JSONL files are never
pruned; they are the long-term audit trail.

## Invariants

1. No fabricated show, seat number, price or format. Missing data stays missing.
2. Seat counts are availability signals from the source, not proof of sales.
3. A blocked source produces no destructive diff; stale data is labelled stale.
4. All timestamps are stored in IST (`+05:30`) and rendered in IST.
5. `schema_version` gates future migrations; bump it when fields change.
