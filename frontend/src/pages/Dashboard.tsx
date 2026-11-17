import { useMemo, useState } from "react";
import type { Platform, Theatre } from "../types";
import {
  countdown,
  formatDate,
  formatDateTime,
  relativeTime,
  timeUntil,
  inr,
  DATA_BASE,
} from "../lib/data";
import { useAppData } from "../App";
import { Chip, ExternalLink, SectionHeading, StatusDot } from "../components/ui";
import { toneClasses } from "../lib/data";
import TheatreCard from "../components/TheatreCard";

type AvailabilityFilter = "all" | "bookable" | "unavailable";

interface Filters {
  date: string;
  theatre: string;
  platform: Platform | "all";
  format: string;
  availability: AvailabilityFilter;
  onlyListed: boolean;
}

const initialFilters: Filters = {
  date: "all",
  theatre: "all",
  platform: "all",
  format: "all",
  availability: "all",
  onlyListed: false,
};

function Hero() {
  const { snapshot, meta, fromCache } = useAppData();
  if (!snapshot) return null;
  const targetDates = snapshot.movie.target_dates;
  const sourceRows = snapshot.sources;
  const lastSuccess = meta?.last_success_at ?? snapshot.checked_at;
  const attemptedLater = new Date(snapshot.checked_at).getTime() > new Date(lastSuccess).getTime();

  return (
    <section className="panel-warm grain relative overflow-hidden">
      {snapshot.movie.poster && (
        <div
          className="pointer-events-none absolute inset-y-0 right-0 hidden w-1/2 opacity-25 [mask-image:linear-gradient(to_left,black,transparent)] lg:block"
          style={{
            backgroundImage: `url(${snapshot.movie.poster})`,
            backgroundSize: "cover",
            backgroundPosition: "center 18%",
          }}
          aria-hidden="true"
        />
      )}
      <div className="relative grid grid-cols-1 gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1.35fr),minmax(0,1fr)] lg:gap-8">
        <div className="min-w-0">
          <p className="label text-flame/80">Marvel Studios · Bengaluru</p>
          <h1 className="mt-2 font-display text-5xl leading-[0.92] tracking-[0.02em] text-white sm:text-6xl lg:text-7xl">
            AVENGERS:
            <span className="block text-flame">DOOMSDAY</span>
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-sand/80">
            Hourly ticket watch across six Bengaluru theatres for{" "}
            <strong className="font-semibold text-white">{targetDates.map((d) => formatDate(d, { weekday: undefined })).join(" and ")}</strong>.
            Formats are detected per show — Infinity Vision 3D is tracked separately from IMAX 3D.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Chip tone="ember">In cinemas {formatDate(snapshot.movie.release_date)}</Chip>
            <Chip tone="muted">Countdown {countdown(snapshot.movie.release_date)}</Chip>
            {snapshot.movie.duration_minutes && <Chip tone="muted">{snapshot.movie.duration_minutes} min</Chip>}
            {snapshot.movie.district_url && <ExternalLink href={snapshot.movie.district_url}>District movie page</ExternalLink>}
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            {targetDates.map((date) => {
              const summary = snapshot.totals.dates[date];
              return (
                <div key={date} className="rounded-xl border border-white/10 bg-black/25 px-3.5 py-2.5">
                  <p className="text-[11px] font-medium uppercase tracking-wider text-ash">{formatDate(date)}</p>
                  <p className="mt-1 text-sm font-semibold text-white">
                    {summary?.shows ? `${summary.shows} shows · ${summary.theatres} theatres` : "Not released yet"}
                  </p>
                  {summary?.shows > 0 && (
                    <p className="mt-0.5 text-[11px] text-ash">
                      {summary.shows_3d} in 3D · {summary.shows_infinity_vision_3d} Infinity Vision 3D
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="min-w-0 rounded-2xl border border-white/[0.08] bg-black/45 p-4 backdrop-blur">
          <div className="flex items-center justify-between">
            <p className="label">Monitoring</p>
            <span className={`chip ${toneClasses[fromCache ? "warn" : snapshot.status === "ok" ? "live" : "ember"]}`}>
              <StatusDot tone={fromCache ? "warn" : snapshot.status === "ok" ? "live" : "ember"} />
              {fromCache ? "Cached" : snapshot.status === "ok" ? "All sources OK" : snapshot.status === "partial" ? "Partial coverage" : "Degraded"}
            </span>
          </div>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-ash">Last successful check</dt>
              <dd className="text-right font-medium text-white" title={formatDateTime(lastSuccess)}>
                {relativeTime(lastSuccess)}
                <span className="block text-[11px] font-normal text-ash">{formatDateTime(lastSuccess)} IST</span>
              </dd>
            </div>
            {attemptedLater && (
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-ash">Latest attempt</dt>
                <dd className="text-right font-medium text-white" title={formatDateTime(snapshot.checked_at)}>
                  {relativeTime(snapshot.checked_at)}
                  <span className="block text-[11px] font-normal text-ash">
                    {formatDateTime(snapshot.checked_at)} IST · {snapshot.status === "degraded" ? "all sources blocked" : "incomplete"}
                  </span>
                </dd>
              </div>
            )}
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-ash">Next scheduled check</dt>
              <dd className="text-right font-medium text-white">
                {timeUntil(meta?.monitoring.next_check_at)}
                <span className="block text-[11px] font-normal text-ash">
                  every {meta?.monitoring.interval_minutes ?? 60} min via the Indian-egress NAS collector
                </span>
              </dd>
            </div>
            <div className="divider" />
            <div>
              <dt className="label mb-2">Sources</dt>
              <div className="space-y-2">
                {sourceRows.map((source) => {
                  const tone = source.status === "ok" ? "live" : source.status === "partial" ? "ember" : "danger";
                  return (
                    <div key={source.source} className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13px] font-medium capitalize text-sand">{source.source === "bookmyshow" ? "BookMyShow" : "District"}</p>
                        <p className="truncate text-[11px] text-ash" title={source.message}>
                          {source.status === "ok" ? "Showtimes read from public pages" : source.message}
                        </p>
                      </div>
                      <span className={`chip shrink-0 ${toneClasses[tone]}`}>
                        <StatusDot tone={tone} pulse={false} />
                        {source.status}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </dl>
          {fromCache && (
            <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-[11px] leading-relaxed text-amber-200/90">
              Showing the last snapshot saved in this browser because the live data could not be fetched.
            </p>
          )}
          {meta?.monitoring.schedule_note && (
            <p className="mt-3 text-[11px] leading-relaxed text-ash">{meta.monitoring.schedule_note}</p>
          )}
        </div>
      </div>
    </section>
  );
}

function StatGrid() {
  const { snapshot } = useAppData();
  if (!snapshot) return null;
  const totals = snapshot.totals;
  const stats = [
    {
      label: "Theatres with listings",
      value: `${totals.theatres_with_listings}/${totals.theatres_monitored}`,
      note: "In your six-theatre watchlist",
      accent: true,
    },
    {
      label: "Shows tracked",
      value: String(totals.shows_total),
      note: `${formatDate(snapshot.movie.target_dates[0])} & ${formatDate(snapshot.movie.target_dates[1])}`,
    },
    { label: "3D shows", value: String(totals.shows_3d), note: "Any 3D format, incl. premium" },
    { label: "Infinity Vision 3D", value: String(totals.shows_infinity_vision_3d), note: "Not counted as IMAX" },
    { label: "IMAX 3D", value: String(totals.shows_imax_3d), note: "Separate premium format" },
    { label: "Bookable now", value: String(totals.bookable_shows), note: "Source says seats can be bought" },
  ];
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className={`panel grain relative overflow-hidden p-4 ${stat.accent ? "border-ember/25" : ""}`}
        >
          <p className="label">{stat.label}</p>
          <p className={`stat-number mt-2 ${stat.accent ? "!text-flame" : ""}`}>{stat.value}</p>
          <p className="mt-1 text-[11px] leading-snug text-ash">{stat.note}</p>
        </div>
      ))}
    </div>
  );
}

function LatestChanges() {
  const { snapshot } = useAppData();
  const events = snapshot?.events ?? [];
  if (!events.length) return null;
  const top = events.slice(0, 3);
  return (
    <div className="panel mt-4 p-4">
      <div className="flex items-center justify-between">
        <p className="label text-flame/80">Latest detected changes</p>
        <ExternalLink href={`${DATA_BASE}/history/events.jsonl`}>raw log</ExternalLink>
      </div>
      <ul className="mt-2.5 space-y-1.5">
        {top.map((event) => (
          <li key={event.id} className="flex items-baseline gap-2 text-[13px] text-sand/90">
            <span className="text-flame">↗</span>
            <span className="min-w-0 flex-1">{event.message}</span>
            <span className="shrink-0 text-[11px] text-ash">{relativeTime(event.created_at)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FiltersBar({ filters, onChange, theatres, formats }: {
  filters: Filters;
  onChange: (patch: Partial<Filters>) => void;
  theatres: Theatre[];
  formats: { key: string; label: string }[];
}) {
  const dates = useAppData().snapshot?.movie.target_dates ?? [];
  const selectClass =
    "rounded-lg border border-white/10 bg-graphite px-2.5 py-2 text-[13px] text-sand outline-none transition hover:border-white/20 focus:border-flame/60";
  return (
    <div className="panel sticky top-[68px] z-30 mt-4 flex flex-wrap items-center gap-2 p-3 backdrop-blur-xl md:top-[61px]">
      <div className="flex rounded-xl border border-white/10 bg-black/30 p-1">
        {[{ value: "all", label: "Both dates" }, ...dates.map((d) => ({ value: d, label: formatDate(d, { year: undefined }) }))].map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange({ date: option.value })}
            className={`rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition ${
              filters.date === option.value ? "bg-ember text-white" : "text-ash hover:text-sand"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      <select aria-label="Filter by theatre" className={selectClass} value={filters.theatre} onChange={(e) => onChange({ theatre: e.target.value })}>
        <option value="all">All theatres</option>
        {theatres.map((theatre) => (
          <option key={theatre.id} value={theatre.id}>{theatre.name}</option>
        ))}
      </select>
      <select aria-label="Filter by platform" className={selectClass} value={filters.platform} onChange={(e) => onChange({ platform: e.target.value as Filters["platform"] })}>
        <option value="all">All platforms</option>
        <option value="district">District</option>
        <option value="bookmyshow">BookMyShow</option>
      </select>
      <select aria-label="Filter by format" className={selectClass} value={filters.format} onChange={(e) => onChange({ format: e.target.value })}>
        <option value="all">All formats</option>
        {formats.map((format) => (
          <option key={format.key} value={format.key}>{format.label}</option>
        ))}
      </select>
      <select aria-label="Filter by availability" className={selectClass} value={filters.availability} onChange={(e) => onChange({ availability: e.target.value as AvailabilityFilter })}>
        <option value="all">Any availability</option>
        <option value="bookable">Bookable only</option>
        <option value="unavailable">Unavailable only</option>
      </select>
      <label className="ml-auto flex cursor-pointer items-center gap-2 text-[12px] text-ash">
        <input
          type="checkbox"
          checked={filters.onlyListed}
          onChange={(e) => onChange({ onlyListed: e.target.checked })}
          className="h-3.5 w-3.5 accent-[#e2571e]"
        />
        Only with shows
      </label>
    </div>
  );
}

function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="panel mt-4 flex flex-col items-center gap-2 p-10 text-center">
      <span className="text-2xl" aria-hidden="true">🍿</span>
      <p className="text-sm font-medium text-sand">{message}</p>
      {hint && <p className="max-w-md text-xs leading-relaxed text-ash">{hint}</p>}
    </div>
  );
}

export default function Dashboard() {
  const { snapshot, loading, error, refresh, settings, fromCache } = useAppData();
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [showAll, setShowAll] = useState(false);

  const formats = useMemo(() => {
    const map = new Map<string, string>();
    for (const theatre of snapshot?.theatres ?? []) {
      for (const format of theatre.formats) map.set(format.key, format.label);
    }
    return Array.from(map, ([key, label]) => ({ key, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [snapshot]);

  const theatres = useMemo(() => {
    const all = snapshot?.theatres ?? [];
    return all.filter((theatre) => !settings.enabledTheatres || settings.enabledTheatres.includes(theatre.id));
  }, [snapshot, settings.enabledTheatres]);

  const visible = useMemo(() => {
    return theatres.filter((theatre) => {
      if (filters.theatre !== "all" && theatre.id !== filters.theatre) return false;
      if (filters.onlyListed && !theatre.listed) return false;
      const relevant = theatre.shows.filter((show) => {
        if (filters.date !== "all" && show.date !== filters.date) return false;
        if (filters.platform !== "all" && show.platform !== filters.platform) return false;
        if (filters.format !== "all" && show.format.key !== filters.format) return false;
        if (filters.availability === "bookable" && !["bookable", "few_left", "filling_fast"].includes(show.availability.status)) return false;
        if (filters.availability === "unavailable" && show.availability.status !== "sold_out") return false;
        return true;
      });
      const narrowed = filters.platform !== "all" || filters.format !== "all" || filters.availability !== "all" || filters.date !== "all";
      return narrowed ? relevant.length > 0 : true;
    });
  }, [theatres, filters]);

  const ordered = useMemo(
    () => [...visible].sort((a, b) => Number(b.listed) - Number(a.listed) || a.name.localeCompare(b.name)),
    [visible],
  );

  const shown = showAll ? ordered : ordered.slice(0, 6);
  const minPrice = Math.min(
    ...snapshot?.theatres.flatMap((t) => t.shows.map((s) => s.price.min).filter((p): p is number => p !== null)) ?? [],
  );

  if (loading && !snapshot) {
    return (
      <div className="space-y-4">
        <div className="panel h-72 animate-pulse" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="panel h-28 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="panel p-10 text-center">
        <h1 className="font-display text-4xl tracking-wide text-white">NO SNAPSHOT YET</h1>
        <p className="mx-auto mt-2 max-w-lg text-sm text-ash">
          The dashboard reads <code className="text-flame">data/latest.json</code>. Run the OpenWrt collector
          once or trigger the GitHub Actions ingest workflow.
        </p>
        {error && <p className="mt-3 text-xs text-red-300">{error}</p>}
        <button type="button" className="btn-ember mt-5" onClick={() => void refresh(true)}>Try again</button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {error && (
        <div className="mb-3 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-2.5 text-xs text-red-200">
          Live refresh failed ({error}). Showing the last known data.
        </div>
      )}
      {fromCache && (
        <div className="mb-3 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-200">
          Offline/cached snapshot. It may be older than the hourly schedule.
        </div>
      )}
      <Hero />
      <StatGrid />
      <LatestChanges />
      <FiltersBar filters={filters} onChange={(patch) => setFilters((current) => ({ ...current, ...patch }))} theatres={theatres} formats={formats} />

      <div className="mt-5">
        <SectionHeading
          eyebrow="Watchlist"
          title="Bengaluru theatres"
          description="Each card shows what the source publicly reports. Booking links go straight to the platform; unavailable means the source exposes no buyable seats."
          right={
            <div className="flex items-center gap-2 text-[12px] text-ash">
              <span>{ordered.length} of {theatres.length} theatres match</span>
              {ordered.length > 6 && (
                <button type="button" className="btn !py-1.5 text-xs" onClick={() => setShowAll((current) => !current)}>
                  {showAll ? "Show fewer" : "Show all"}
                </button>
              )}
            </div>
          }
        />
        {shown.length === 0 ? (
          <EmptyState
            message="No theatres match these filters"
            hint="Try clearing the format or availability filter. Theatres without a released show are still worth watching — they appear as “Not released yet”."
          />
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {shown.map((theatre) => (
              <TheatreCard
                key={theatre.id}
                theatre={theatre}
                filters={filters}
                targetDates={snapshot.movie.target_dates}
                platforms={settings.enabledPlatforms}
              />
            ))}
          </div>
        )}
      </div>

      <div className="panel mt-6 flex flex-col gap-3 p-4 text-[12px] leading-relaxed text-ash sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-3xl">
          <strong className="text-sand">Data honesty:</strong> showtimes, screens, prices and area-wise seat counts come from
          District&apos;s public pages. BookMyShow is probed every hour; when it blocks automated access we say so and keep the
          last good snapshot instead of inventing data. Unavailable seats are <em>not</em> confirmed ticket sales.
        </p>
        <div className="flex shrink-0 gap-2">
          {snapshot.sources.map((source) => (
            <Chip key={source.source} tone={source.status === "ok" ? "live" : source.status === "partial" ? "ember" : "danger"}>
              {source.source === "bookmyshow" ? "BMS" : "District"}: {source.status}
            </Chip>
          ))}
        </div>
      </div>
      <p className="mt-3 text-center text-[11px] text-ash/70">
        {snapshot.totals.seats_available_total.toLocaleString("en-IN")} seats reported available across all tracked shows
        {" · "}prices from {inr(minPrice)} where the source publishes them. Status labels are kept exactly as the source
        reports them and are never converted into sales numbers.
      </p>
    </div>
  );
}
