# Data schema and invariants

Everything the dashboard shows is derived from files in this repository. There is
no database server and no hidden API: `data/` is the database.

## Directory layout

```
data/
├── inbox/district.json         # compact District payload uploaded by the router
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
  "schema_version": 2,
  "generated_at": "2026-11-17T20:00:00+05:30",
  "checked_at": "2026-11-17T20:00:00+05:30",   // IST ISO-8601
  "status": "ok | partial | degraded",          // ok = every source fully healthy; partial = at least one blocked/partial
  // Multi-movie source of truth. Each entry has its own movie, totals,
  // theatres, sources and events. Session IDs are namespaced by content ID.
  "movies": [
    {
      "movie": { "id": "avengers-doomsday", "title": "Avengers: Doomsday", "required_format_keys": [] },
      "totals": { "shows_total": 20 },
      "theatres": [ /* same theatre shape as below */ ],
      "events": [ /* movie_id + movie_title on every event */ ]
    },
    {
      "movie": { "id": "ramayana", "title": "Ramayana", "required_format_keys": ["4dx_3d"] },
      "totals": { "shows_total": 2, "shows_4dx_3d": 2 },
      "theatres": [ /* only explicit 4DX-3D sessions */ ]
    }
  ],
  // Compatibility aliases = primary movie (Avengers). Do not use for new code.
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
    "shows_4dx": 0,
    "shows_4dx_3d": 0,
    "movies_tracked": 2,
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
          "start": "19:10",               // 24h IST derived from the source clock
          "start_iso": "2026-12-17T19:10:00+05:30",
          "source_time": "2026-12-17T13:40",  // raw District clock (naive UTC)
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
  ],
  "provenance": {                              // optional; set for NAS ingestion
    "transport": "nas_inbox",
    "collected_at": "2026-11-17T23:00:00+05:30",
    "ingested_at": "2026-11-17T23:01:12+05:30",
    "content_sha256": "...",
    "collector": { "name": "openwrt-ucode", "host": "openwrt", "egress": "IN" }
  }
}
```

The District source's `checked_at` and `last_success_at` use the collector's
`collected_at`, not the later ingestion time. `snapshot.checked_at` remains the
ingestion run time. The optional `provenance` object is additive; older readers
ignore it.

## `data/inbox/district.json` (NAS payload)

This file is written only by the OpenWrt collector and consumed by the `ingest`
CLI:

```jsonc
{
  "schema_version": 2,
  "source": "district",
  "collected_at": "2026-11-17T23:00:00+05:30",
  "collector": { "name": "openwrt-ucode", "version": "2.0.0", "host": "openwrt", "egress": "IN" },
  "movies": [
    {
      "id": "avengers-doomsday",
      "status": "ok | unavailable | error",
      "content_id": "176735",
      "movie_url": "https://www.district.in/movies/...",
      "movie": { "title": "Avengers: Doomsday", "release_date": "..." },
      "groups": [
        {
          "data": { "id": "56450", "name": "Cinepolis Lulu Global Mall..." },
          "sessions": [
            { "sid": "...", "showTime": "2026-12-17T13:40",  // naive UTC in District payload
              "audi": "MACRO XE", "scrnFmt": "MS INFINITY VISION 3D",
              "total": 277, "avail": 41, "seatStatus": "Filling Fast",
              "areas": [{ "label": "NORMAL", "price": 890, "sTotal": 19, "sAvail": 19 }] }
          ],
          "available_dates": ["2026-12-17"]
        }
      ]
    },
    {
      "id": "ramayana",
      "status": "ok",
      "content_id": "176276",
      "movie": { "title": "Ramayana", "release_date": "2026-11-05" },
      "groups": [
        {
          "data": { "id": "1022299", "name": "PVR Orion Mall..." },
          "sessions": [
            { "sid": "...", "showTime": "2026-11-18T06:10", "scrnFmt": "4DX-3D", "areas": [] }
          ]
        }
      ]
    }
  ]
}
```

Ingestion rejects a payload with a wrong content ID/title, a missing configured
movie, no movie metadata for an `ok` entry, malformed sessions, a timestamp more
than 3 hours old or in the future, or a timestamp older than the current snapshot.
An `unavailable`/`error` movie entry is accepted and preserves that movie's last
good snapshot while the other movie updates. A payload whose canonical data hash
equals the previous snapshot (and whose `normalizer_version` is current) is ignored
without writing data.

Schema-v1 single-movie payloads are still accepted for compatibility; the other
configured movie is recorded as missing/partial rather than silently dropped.

### Multi-movie invariants

- Doomsday and Ramayana have distinct `movie.id`, `district_content_id`, session
  IDs, snapshot totals and event IDs.
- `required_format_keys: ["4dx_3d"]` filters only after the source format is
  normalised. District's `4DX-3D` maps to `4dx_3d`; `3D`, `4DX`, `IMAX 3D` and
  `Infinity Vision 4DX 3D` do not.
- A movie with no published sessions remains present with zero shows. Nothing is
  invented for unpublished dates.
- All `showTime` values are naive UTC from District; conversion to Asia/Kolkata
  happens once in the Python adapter. `source_time` retains the raw value.

### Normalised format enum

`imax_3d`, `imax_2d`, `infinity_vision_3d`, `infinity_vision_4dx_3d`, `4dx_3d`,
`4dx_2d`, `ice_3d`, `dolby_3d`, `dolby_2d`, `screenx_3d`, `screenx_2d`, `pxl_3d`,
`pxl_2d`, `laser_3d`, `3d`, `2d`, `unknown`.

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

## Dry-run guarantee

`run --dry-run` executes the fetch/parse/diff path with a temporary cache directory
and returns before any write. It creates no `data/` directory or files, does not
touch `state.json` (so notification dedupe is unchanged), and never sends an alert.

## Time semantics (District)

District's `showTime` is a naive UTC clock. For example, raw `06:15` with District's
own `8_am_to_12_pm` tag is 11:45 IST and matches PVR's 11:45 listing. Ingest converts
it exactly once to `Asia/Kolkata`; the raw value is retained as `source_time`.
The collector sends all sessions for the six cinemas so sessions whose UTC date is
the previous day are not lost before the IST date filter runs.

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
6. The router never uploads inferred sales; only source-reported seat counts. An
   unchanged payload hash is skipped, so the collector cannot churn the repo.
