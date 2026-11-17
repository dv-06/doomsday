import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HistoryEvent, RunRecord } from "../types";
import { useAppData } from "../App";
import {
  eventIcons,
  eventLabels,
  formatDate,
  formatDateTime,
  legacyEventClock,
  loadEvents,
  loadRuns,
  relativeTime,
  severityClasses,
} from "../lib/data";
import { Chip, SectionHeading, StatusDot } from "../components/ui";

const PAGE = 60;

function ChartCard({ runs }: { runs: RunRecord[] }) {
  const data = useMemo(() => {
    // Bucket by hour so manual runs and retries do not create duplicate ticks.
    const buckets = new Map<number, RunRecord>();
    for (const run of runs.slice(-168)) {
      const slot = Math.floor(new Date(run.checked_at).getTime() / 3_600_000);
      buckets.set(slot, run);
    }
    return Array.from(buckets.values()).map((run) => ({
      label: new Intl.DateTimeFormat("en-IN", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Asia/Kolkata",
      }).format(new Date(run.checked_at)),
      shows: run.totals?.shows_total ?? 0,
      threeD: run.totals?.shows_3d ?? 0,
      infinity: run.totals?.shows_infinity_vision_3d ?? 0,
      seats: run.totals?.seats_available_total ?? 0,
    }));
  }, [runs]);

  if (data.length < 1) {
    return <p className="text-sm text-ash">No runs recorded yet. The chart appears after the first hourly snapshot.</p>;
  }

  if (data.length < 2) {
    return (
      <div className="grid h-64 place-items-center rounded-xl border border-dashed border-white/10 bg-black/20 px-6 text-center">
        <div>
          <p className="text-sm font-medium text-sand">Trend starts with the second hourly run</p>
          <p className="mt-1 max-w-sm text-[12px] leading-relaxed text-ash">
            There is one stored snapshot so far ({data[0].label} IST, {data[0].shows} shows). A line needs at least two
            hours of history, so nothing is drawn yet rather than faking a trend.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-64 w-full sm:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="gShows" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e2571e" stopOpacity={0.45} />
              <stop offset="100%" stopColor="#e2571e" stopOpacity={0.02} />
            </linearGradient>
undefined          </defs>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={40} tick={{ fill: "#7d7d8a", fontSize: 10 }} />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "#7d7d8a", fontSize: 10 }} width={40} />
          <Tooltip
            contentStyle={{
              background: "#121216",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 12,
              fontSize: 12,
              color: "#f4e7dd",
            }}
            labelStyle={{ color: "#9a9aa7" }}
          />
          <Area type="stepAfter" dataKey="shows" name="Shows" stroke="#f97316" strokeWidth={2} fill="url(#gShows)" />
          <Line type="stepAfter" dataKey="threeD" name="3D shows" stroke="#34d399" strokeWidth={1.5} strokeDasharray="5 3" dot={{ r: 2.5, fill: "#34d399", strokeWidth: 0 }} />
          <Line type="stepAfter" dataKey="infinity" name="Infinity Vision 3D" stroke="#38bdf8" strokeWidth={1.5} strokeDasharray="1 3" dot={{ r: 2.5, fill: "#38bdf8", strokeWidth: 0 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function TimelineEvent({ event }: { event: HistoryEvent }) {
  const legacy = event.time_basis ? null : legacyEventClock(event.date, event.start);
  const shownDate = legacy?.date ?? event.date;
  const shownStart = legacy?.start ?? event.start;
  const shownMessage = legacy && event.message
    ? event.message
        .split(event.start ?? "").join(legacy.start)
        .split(event.date ?? "").join(legacy.date)
    : event.message;
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      <span className="absolute left-[15px] top-7 h-full w-px bg-white/[0.07] last:hidden" aria-hidden="true" />
      <span className={`relative z-10 mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full border text-[13px] ${severityClasses[event.severity] ?? severityClasses.low}`}>
        {eventIcons[event.type] ?? "•"}
      </span>
      <div className="min-w-0 flex-1 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-semibold text-sand">{eventLabels[event.type] ?? event.type}</span>
          <span className="text-[11px] text-ash">{event.theatre_name}</span>
          {event.platform && <Chip tone="muted" className="!px-1.5 !py-0 !text-[9px]">{event.platform === "bookmyshow" ? "BookMyShow" : event.platform}</Chip>}
          {shownDate && (
            <span className="text-[10px] text-ash/80">
              {formatDate(shownDate, { year: undefined })}
              {shownStart ? ` · ${shownStart}` : ""}
            </span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-ash/70" title={formatDateTime(event.created_at)}>{relativeTime(event.created_at)}</span>
        </div>
        <p className="mt-1 text-[12px] leading-relaxed text-sand/90">{shownMessage}</p>
      </div>
    </li>
  );
}

export default function History() {
  const { snapshot } = useAppData();
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [type, setType] = useState("all");
  const [theatre, setTheatre] = useState("all");
  const [limit, setLimit] = useState(PAGE);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [nextEvents, nextRuns] = await Promise.all([loadEvents(), loadRuns()]);
        if (!alive) return;
        setEvents(nextEvents);
        setRuns(nextRuns);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Could not load history");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const theatres = snapshot?.theatres ?? [];
  const filtered = useMemo(
    () =>
      events.filter(
        (event) =>
          (type === "all" || event.type === type) &&
          (theatre === "all" || event.theatre_id === theatre),
      ),
    [events, type, theatre],
  );

  const grouped = useMemo(() => {
    const map = new Map<string, HistoryEvent[]>();
    for (const event of filtered.slice(0, limit)) {
      const key = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(event.created_at));
      const list = map.get(key) ?? [];
      list.push(event);
      map.set(key, list);
    }
    return Array.from(map.entries());
  }, [filtered, limit]);

  const firstListing = useMemo(
    () => [...events].reverse().find((event) => event.type === "theatre_listed" || event.type === "first_show"),
    [events],
  );

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const event of events) map.set(event.type, (map.get(event.type) ?? 0) + 1);
    return map;
  }, [events]);

  return (
    <div className="space-y-5">
      <div>
        <p className="label text-flame/80">Audit trail</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Availability history</h1>
        <p className="mt-1 max-w-2xl text-sm text-ash">
          Every hourly run is committed to the repository. Changes are compared against the previous snapshot,
          and seat counts are stored as <em>source-reported availability</em> — never as confirmed sales.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Recorded runs", value: String(runs.length), note: "Hourly snapshots in history" },
          { label: "Change events", value: String(events.length), note: "All event types, never pruned" },
          { label: "First release seen", value: firstListing ? relativeTime(firstListing.created_at) : "—", note: firstListing ? firstListing.theatre_name : "Waiting for the first show" },
          { label: "Last check", value: snapshot ? relativeTime(snapshot.checked_at) : "—", note: snapshot ? formatDateTime(snapshot.checked_at) : "" },
        ].map((card) => (
          <div key={card.label} className="panel p-4">
            <p className="label">{card.label}</p>
            <p className="mt-1.5 text-2xl font-semibold text-white">{card.value}</p>
            <p className="mt-0.5 truncate text-[11px] text-ash" title={card.note}>{card.note}</p>
          </div>
        ))}
      </div>

      <div className="panel p-4 sm:p-5">
        <SectionHeading
          eyebrow="Trend"
          title="Shows and formats per hourly check"
          description="Runs where a source was blocked carry the previous totals forward, so the line flattens rather than pretending a drop."
          right={
            runs.length >= 2 ? (
              <div className="flex flex-wrap gap-2 text-[11px]">
                <Chip tone="ember"><StatusDot tone="ember" pulse={false} /> Shows</Chip>
                <Chip tone="live"><StatusDot tone="live" pulse={false} /> 3D</Chip>
                <Chip tone="muted"><StatusDot tone="muted" pulse={false} /> Infinity Vision 3D</Chip>
              </div>
            ) : undefined
          }
        />
        <ChartCard runs={runs} />
        {runs.length < 6 && (
          <p className="mt-1 text-[11px] leading-relaxed text-ash">
            Only {runs.length} stored run{runs.length === 1 ? "" : "s"} so far. All listed shows are currently 3D and
            Infinity Vision 3D, so the lines overlap until more formats appear.
          </p>
        )}
      </div>

      <div className="panel p-4 sm:p-5">
        <SectionHeading
          eyebrow="Change log"
          title="Timeline"
          description="Newest first. Each entry maps to a real diff between two stored snapshots."
          right={
            <div className="flex flex-wrap gap-2">
              <select
                aria-label="Filter events by type"
                value={type}
                onChange={(e) => { setType(e.target.value); setLimit(PAGE); }}
                className="rounded-lg border border-white/10 bg-graphite px-2.5 py-2 text-[12px] text-sand"
              >
                <option value="all">All event types</option>
                {Object.entries(eventLabels).map(([key, label]) => (
                  <option key={key} value={key}>{label} ({counts.get(key) ?? 0})</option>
                ))}
              </select>
              <select
                aria-label="Filter events by theatre"
                value={theatre}
                onChange={(e) => { setTheatre(e.target.value); setLimit(PAGE); }}
                className="rounded-lg border border-white/10 bg-graphite px-2.5 py-2 text-[12px] text-sand"
              >
                <option value="all">All theatres</option>
                {theatres.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </div>
          }
        />

        {loading ? (
          <p className="py-8 text-center text-sm text-ash">Loading history…</p>
        ) : error ? (
          <p className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-200">
            {error}. History appears after the first monitor run creates <code>data/history/events.jsonl</code>.
          </p>
        ) : filtered.length === 0 ? (
          <p className="py-8 text-center text-sm text-ash">No events match this filter yet.</p>
        ) : (
          <>
            {grouped.map(([day, dayEvents]) => (
              <div key={day} className="mb-5 last:mb-0">
                <p className="label mb-2 sticky top-[120px] z-10 w-fit rounded-full border border-white/10 bg-charcoal/90 px-2.5 py-1 backdrop-blur">
                  {formatDate(day, { weekday: "long" })}
                  <span className="ml-2 text-ash/70">{dayEvents.length} change{dayEvents.length === 1 ? "" : "s"}</span>
                </p>
                <ul>
                  {dayEvents.map((event) => <TimelineEvent key={event.id} event={event} />)}
                </ul>
              </div>
            ))}
            {filtered.length > limit && (
              <button type="button" className="btn mx-auto mt-2 block" onClick={() => setLimit((current) => current + PAGE)}>
                Show more ({filtered.length - limit} older)
              </button>
            )}
          </>
        )}
      </div>

      <p className="text-center text-[11px] leading-relaxed text-ash/70">
        Seat drops are availability signals from the source. They can mean sales, temporary blocks, or released holds —
        the tracker does not guess which. Confirm on the booking platform.
      </p>
    </div>
  );
}
