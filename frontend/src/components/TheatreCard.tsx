import { useState } from "react";
import type { DateSummary, Platform, PlatformObservation, Show, Theatre } from "../types";
import {
  availabilityTone,
  formatBadgeClass,
  formatDate,
  inr,
  platformLabel,
  relativeTime,
  toneClasses,
} from "../lib/data";
import { AvailabilityChip, Bar, Chip, ExternalLink } from "./ui";
import type { Tone } from "../lib/data";

interface Props {
  theatre: Theatre;
  targetDates: string[];
  filters: { date: string; platform: string; format: string; availability: string };
  platforms?: Platform[];
}

const platformTone = (status: string): Tone => {
  if (status === "ok") return "live";
  if (status === "not_listed" || status === "unavailable") return "muted";
  if (status === "stale") return "warn";
  if (status === "partial") return "ember";
  return "danger";
};

function healthChip(theatre: Theatre) {
  const health = theatre.health;
  const map: Record<string, { label: string; tone: Tone }> = {
    live: { label: "Live", tone: "live" },
    partial: { label: "Partial data", tone: "ember" },
    stale: { label: `Stale · ${health.age_minutes ?? "?"}m`, tone: "warn" },
    unavailable: { label: "Source unavailable", tone: "danger" },
    error: { label: "Error", tone: "danger" },
  };
  const entry = map[health.status] ?? { label: health.status, tone: "muted" as const };
  return <Chip tone={entry.tone}>{entry.label}</Chip>;
}

function venueHost(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function matches(show: Show, filters: Props["filters"]): boolean {
  if (filters.date !== "all" && show.date !== filters.date) return false;
  if (filters.platform !== "all" && show.platform !== filters.platform) return false;
  if (filters.format !== "all" && show.format.key !== filters.format) return false;
  if (filters.availability === "bookable" && !["bookable", "few_left", "filling_fast"].includes(show.availability.status)) return false;
  if (filters.availability === "unavailable" && show.availability.status !== "sold_out") return false;
  return true;
}

function ShowChip({ show }: { show: Show }) {
  const tone = availabilityTone[show.availability.status] ?? "muted";
  const label = (
    <>
      <span className="font-mono text-[12px] font-medium text-white">{show.start}</span>
      <span className="text-[10px] uppercase tracking-wide text-ash">{show.format.label}</span>
      {show.availability.status === "sold_out" && <span className="text-[10px] text-red-300">sold out</span>}
    </>
  );
  const title = [
    `${show.date} ${show.start} · ${show.format.label}`,
    show.screen ? `Screen: ${show.screen}` : null,
    show.availability.available_seats !== null ? `${show.availability.available_seats} seats reported available` : null,
    show.price.min ? `from ${inr(show.price.min)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  if (show.booking_url) {
    return (
      <a
        href={show.booking_url}
        target="_blank"
        rel="noopener noreferrer"
        title={title}
        className={`chip ${toneClasses[tone]} transition hover:-translate-y-0.5 hover:border-flame/50 hover:text-white`}
      >
        {label}
      </a>
    );
  }
  return <span className={`chip ${toneClasses[tone]}`} title={title}>{label}</span>;
}

function DayRow({ date, day, shows, theatre }: { date: string; day?: DateSummary; shows: Show[]; theatre: Theatre }) {
  const listedAnywhere = Object.values(theatre.platforms).some((obs) => obs?.listed);
  return (
    <div className="border-t border-white/[0.05] py-3 first:border-t-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-sand">{formatDate(date, { year: undefined })}</span>
          {day?.listed ? <AvailabilityChip status={day.booking_status} /> : <Chip tone="muted">Not released</Chip>}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-ash">
          {day?.listed && day.seats_available !== null && <span>{day.seats_available} seats reported</span>}
          {day?.listed && <span>{shows.length} show{shows.length === 1 ? "" : "s"}</span>}
        </div>
      </div>
      {shows.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {shows.map((show) => (
            <ShowChip key={show.id} show={show} />
          ))}
        </div>
      ) : (
        <p className="mt-1.5 text-[12px] leading-relaxed text-ash">
          {listedAnywhere
            ? "Cinema is listed for this movie, but no sessions are published on this date yet."
            : "Not in the source's session list yet — this card will update automatically when tickets drop."}
        </p>
      )}
      {day?.price_min !== null && day?.price_min !== undefined && (
        <p className="mt-1.5 text-[11px] text-ash/80">
          {inr(day.price_min)}–{inr(day.price_max)} · {day.formats.map((f) => f.label).join(" · ")}
        </p>
      )}
    </div>
  );
}

function SeatPreview({ theatre }: { theatre: Theatre }) {
  const rec = theatre.best_seats;
  const [open, setOpen] = useState(false);
  if (!rec) {
    return (
      <div className="rounded-xl border border-white/[0.06] bg-black/25 p-3">
        <p className="label">Seat guide</p>
        <p className="mt-1 text-[12px] leading-relaxed text-ash">
          No public seat counts for this theatre yet, so no recommendation is invented.
        </p>
      </div>
    );
  }
  const isHeuristic = rec.mode === "heuristic";
  return (
    <div className="rounded-xl border border-white/[0.06] bg-black/25">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-2 p-3 text-left"
        aria-expanded={open}
      >
        <div className="min-w-0">
          <p className="label flex items-center gap-2">
            Seat guide
            <span className={`chip ${isHeuristic ? toneClasses.muted : toneClasses.live} !px-1.5 !py-0 text-[9px]`}>
              {isHeuristic ? "heuristic" : "seat map"}
            </span>
          </p>
          <p className="mt-1 truncate text-[12px] text-sand">
            {isHeuristic
              ? `${rec.best.map((area) => area.area).slice(0, 2).join(" · ")} — centre, ${rec.target_zone.depth_percent[0]}–${rec.target_zone.depth_percent[1]}% back`
              : `Best seats ${rec.best.slice(0, 3).map((seat) => `${seat.row}${seat.number}`).join(", ")}`}
          </p>
        </div>
        <span className="shrink-0 text-[11px] font-medium text-flame">{open ? "Hide" : "Why?"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-white/[0.06] p-3">
          {isHeuristic ? (
            <>
              <p className="text-[12px] leading-relaxed text-sand/90">
                Aim for the middle 40% of a row, centred on the screen&apos;s midpoint, and sit{" "}
                {rec.target_zone.depth_percent[0]}–{rec.target_zone.depth_percent[1]}% of the way back.{" "}
                {rec.target_zone.depth_note}.
              </p>
              <div>
                <p className="label mb-1.5">Recommended blocks</p>
                <div className="space-y-1.5">
                  {rec.best.map((area) => (
                    <div key={area.area} className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-2">
                      <div className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="font-medium text-sand">{area.area}</span>
                        <span className="text-ash">
                          {area.available_seats}/{area.total_seats} free · {inr(area.price)}
                        </span>
                      </div>
                      <div className="mt-1.5">
                        <Bar value={area.available_seats} max={area.total_seats} tone="live" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {rec.second_best.length > 0 && (
                <p className="text-[11px] leading-relaxed text-ash">
                  Second choice: {rec.second_best.map((a) => `${a.area} (${a.available_seats} free)`).join(", ")}
                </p>
              )}
              {rec.avoid.length > 0 && (
                <p className="text-[11px] leading-relaxed text-ash">
                  Avoid: {rec.avoid.map((a) => `${a.area ?? "edges"} — ${a.reason}`).join("; ")}.
                </p>
              )}
            </>
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                <div>
                  <p className="label mb-1.5">Best seats</p>
                  <ul className="space-y-1">
                    {rec.best.slice(0, 4).map((seat) => (
                      <li key={`${seat.row}-${seat.number}`} className="text-[12px] text-sand">
                        <span className="font-mono font-semibold text-flame">{seat.row}{seat.number}</span>{" "}
                        <span className="text-ash">{seat.reasons[0]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="label mb-1.5">Avoid</p>
                  <ul className="space-y-1">
                    {rec.avoid.slice(0, 3).map((seat) => (
                      <li key={`${seat.row}-${seat.number}-avoid`} className="text-[12px] text-sand">
                        <span className="font-mono font-semibold text-red-300">{seat.row}{seat.number}</span>{" "}
                        <span className="text-ash">{seat.reasons[0]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <p className="text-[11px] text-ash">{rec.depth_note} ({rec.available_seats}/{rec.total_seats} seats free)</p>
            </>
          )}
          <p className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-2 text-[11px] leading-relaxed text-ash">
            {rec.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
}

function PlatformRow({ platform, obs }: { platform: string; obs: PlatformObservation }) {
  const tone = platformTone(obs.status);
  const detail =
    obs.status === "ok"
      ? obs.shows.length
        ? `Read ${obs.shows.length} target-date show${obs.shows.length === 1 ? "" : "s"}`
        : "Listed, no target-date shows"
      : obs.status === "not_listed"
        ? "Not in this movie's session list"
        : obs.error || "No data";
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-white/[0.05] bg-white/[0.015] px-2.5 py-2">
      <div className="min-w-0">
        <p className="text-[12px] font-medium text-sand">{platformLabel[platform] ?? platform}</p>
        <p className="truncate text-[11px] text-ash" title={detail}>{detail}</p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {obs.stale && obs.data_age_minutes !== null && obs.data_age_minutes !== undefined && (
          <span className="text-[10px] text-amber-300">{obs.data_age_minutes}m old</span>
        )}
        <span className={`chip ${toneClasses[tone]} !px-2 !py-0.5 text-[10px]`}>{obs.status}</span>
      </div>
    </div>
  );
}

export default function TheatreCard({ theatre, targetDates, filters, platforms }: Props) {
  const [expanded, setExpanded] = useState(false);
  const visiblePlatforms: Platform[] = platforms ?? ["district", "bookmyshow"];
  const platformEntries = Object.entries(theatre.platforms).filter(([platform]) =>
    visiblePlatforms.includes(platform as Platform),
  ) as [Platform, PlatformObservation][];
  const filteredDates = targetDates.filter((date) => filters.date === "all" || filters.date === date);
  const allVisibleShows = theatre.shows.filter((show) => matches(show, filters));
  const primaryUrl = theatre.booking.url ?? theatre.booking.source_urls.find((source) => source.url)?.url ?? null;
  const host = venueHost(primaryUrl);
  const verified = Object.values(theatre.verification).some((entry) => entry.status === "verified");

  return (
    <article className="panel grain relative flex flex-col overflow-hidden">
      <header className="p-4 pb-2.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[15px] font-semibold leading-tight text-white">{theatre.name}</h3>
              {healthChip(theatre)}
            </div>
            <p className="mt-0.5 text-[11px] text-ash">
              {theatre.area}
              {theatre.platforms.district?.venue?.id ? ` · District venue ${theatre.platforms.district.venue.id}` : ""}
            </p>
          </div>
          {verified ? (
            <Chip tone="live" title={theatre.verification.district?.note ?? "Venue matched by ID on the platform"}>
              ✓ Venue verified
            </Chip>
          ) : (
            <Chip tone="warn" title="Venue could not be matched by ID this run">Unverified</Chip>
          )}
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {theatre.formats.map((format) => (
            <Chip key={format.key} className={formatBadgeClass(format.key)}>
              {format.label} · {format.count}
            </Chip>
          ))}
          {theatre.booking.status !== "unknown" && <AvailabilityChip status={theatre.booking.status} />}
          {theatre.booking.url && <Chip tone="muted">{theatre.shows[0]?.price.min ? `from ${inr(theatre.shows[0].price.min)}` : "prices on source"}</Chip>}
        </div>
      </header>

      <div className="px-4">
        {filteredDates.map((date) => {
          const day = theatre.dates[date];
          const shows = (day?.shows ?? []).filter((show) => matches(show, filters));
          return <DayRow key={date} date={date} day={day} shows={shows} theatre={theatre} />;
        })}
      </div>

      <div className="px-4 pb-3">
        <SeatPreview theatre={theatre} />
      </div>

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {Object.entries(theatre.platforms).map(([platform, obs]) =>
            obs ? <Chip key={platform} tone={platformTone(obs.status)} className="!px-2 !py-0.5 text-[10px]">{platformLabel[platform] ?? platform}: {obs.status}</Chip> : null,
          )}
          {theatre.health.status === "stale" && theatre.health.age_minutes !== null && (
            <span className="text-[10px] text-amber-300">data {theatre.health.age_minutes}m old</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn !px-2.5 !py-1.5 text-[11px]" onClick={() => setExpanded((current) => !current)} aria-expanded={expanded}>
            {expanded ? "Less" : `Details${allVisibleShows.length ? ` · ${allVisibleShows.length}` : ""}`}
          </button>
          {primaryUrl ? (
            <a href={primaryUrl} target="_blank" rel="noopener noreferrer" className="btn-ember !px-3 !py-1.5 text-[11px]">
              Book on {host?.includes("district") ? "District" : host?.includes("bookmyshow") ? "BookMyShow" : "source"}
            </a>
          ) : (
            <span className="chip border-white/10 bg-white/5 text-[10px] text-ash">No booking link yet</span>
          )}
        </div>
      </div>

      {expanded && (
        <div className="space-y-4 border-t border-white/[0.06] bg-black/20 p-4">
          <div>
            <p className="label mb-2">All detected shows</p>
            {allVisibleShows.length === 0 ? (
              <p className="text-[12px] text-ash">No shows match the active filters.</p>
            ) : (
              <div className="space-y-2">
                {allVisibleShows.map((show) => (
                  <div key={show.id} className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[13px] font-semibold text-white">{show.start}</span>
                        <span className="text-[11px] text-ash">{formatDate(show.date, { year: undefined })}</span>
                        <Chip className={formatBadgeClass(show.format.key)}>{show.format.label}</Chip>
                        {show.screen && <Chip tone="muted">{show.screen}</Chip>}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-ash">
                        {show.price.min !== null && <span>{inr(show.price.min)}–{inr(show.price.max)}</span>}
                        <AvailabilityChip status={show.availability.status} raw={show.availability.status_raw} />
                      </div>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <Bar
                        value={show.availability.available_seats}
                        max={show.availability.total_seats}
                        tone={show.availability.status === "sold_out" ? "danger" : "live"}
                      />
                      <span className="shrink-0 text-[10px] text-ash">
                        {show.availability.available_seats !== null
                          ? `${show.availability.available_seats}/${show.availability.total_seats}`
                          : "seat count not published"}
                      </span>
                    </div>
                    {show.availability.areas.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                        {show.availability.areas.map((area) => (
                          <span key={area.label} className="text-[10px] text-ash">
                            <span className={availabilityTone[area.status] === "danger" ? "text-red-300" : "text-sand/80"}>{area.label}</span>
                            {" "}{area.available_seats ?? "?"}/{area.total_seats ?? "?"} · {inr(area.price)}
                          </span>
                        ))}
                      </div>
                    )}
                    {show.booking_url && (
                      <div className="mt-1.5">
                        <ExternalLink href={show.booking_url}>Open seat layout</ExternalLink>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <p className="label mb-2">Platform observations</p>
            <div className="space-y-1.5">
              {platformEntries.map(([platform, obs]) => <PlatformRow key={platform} platform={platform} obs={obs} />)}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="label mb-1.5">Venue verification</p>
              {Object.entries(theatre.verification).length === 0 ? (
                <p className="text-[11px] text-ash">No venue match this run.</p>
              ) : (
                Object.entries(theatre.verification).map(([platform, entry]) => (
                  <div key={platform} className="mb-2 text-[11px] leading-relaxed text-ash">
                    <p className="text-sand">{platformLabel[platform] ?? platform}: <span className="text-ash">{entry.source_name ?? "—"}</span></p>
                    <p>{entry.note}</p>
                  </div>
                ))
              )}
            </div>
            <div>
              <p className="label mb-1.5">Source links</p>
              <div className="flex flex-col gap-1">
                {theatre.booking.source_urls.filter((source) => source.url && visiblePlatforms.includes(source.platform)).map((source) => (
                  <ExternalLink key={source.platform} href={source.url as string}>
                    {platformLabel[source.platform] ?? source.platform} venue page
                  </ExternalLink>
                ))}
                {theatre.other_dates_seen && theatre.other_dates_seen.length > 0 && (
                  <p className="mt-1 text-[11px] text-ash">
                    Sessions also seen on: {theatre.other_dates_seen.map((date) => formatDate(date, { year: undefined })).join(", ")} (outside your target dates)
                  </p>
                )}
              </div>
            </div>
          </div>

          {theatre.notes && <p className="text-[11px] leading-relaxed text-ash/80">{theatre.notes}</p>}
          <p className="text-[10px] text-ash/60">Last observed {relativeTime(theatre.platforms.district?.checked_at ?? theatre.platforms.bookmyshow?.checked_at)}</p>
        </div>
      )}
    </article>
  );
}
