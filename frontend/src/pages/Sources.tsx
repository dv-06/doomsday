import { useAppData } from "../App";
import { formatDateTime, platformLabel, relativeTime, toneClasses } from "../lib/data";
import { Chip, ExternalLink, SectionHeading, StatusDot } from "../components/ui";

const sourceNotes: Record<string, { headline: string; detail: string; evidenceKeys: [string, string][] }> = {
  district: {
    headline: "Public movie pages, parsed once per run",
    detail:
      "District server-renders each Bengaluru movie page with session, screen, format, price and area-wise seat counts. We request one page per tracked movie once an hour and parse the embedded JSON. No private API, no login, no browser automation.",
    evidenceKeys: [
      ["http_status", "HTTP"],
      ["latency_ms", "Latency"],
      ["attempts", "Attempts"],
      ["session_groups", "Cinemas in session list"],
      ["dates_with_sessions", "Dates with sessions"],
    ],
  },
};

function valueOf(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function Sources() {
  const { snapshot } = useAppData();

  if (!snapshot) {
    return <p className="panel p-8 text-sm text-ash">No snapshot loaded yet.</p>;
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="label text-flame/80">Transparency</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Sources &amp; access</h1>
        <p className="mt-1 max-w-3xl text-sm text-ash">
          Where every number comes from, what each platform allows, and what the tracker deliberately refuses to do.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {snapshot.sources.map((source) => {
          const tone = source.status === "ok" ? "live" : source.status === "partial" ? "ember" : "danger";
          const notes = sourceNotes[source.source];
          return (
            <div key={source.source} className="panel p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-white">{platformLabel[source.source] ?? source.source}</h2>
                  <p className="text-[11px] text-ash">checked {relativeTime(source.checked_at)} · last success {relativeTime(source.last_success_at)}</p>
                </div>
                <span className={`chip ${toneClasses[tone]}`}>
                  <StatusDot tone={tone} pulse={false} />
                  {source.status}
                </span>
              </div>
              <p className="mt-3 text-[13px] leading-relaxed text-sand/90">{notes.headline}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-ash">{notes.detail}</p>
              <p className="mt-3 rounded-lg border border-white/[0.06] bg-black/25 p-2.5 text-[12px] leading-relaxed text-sand/85">
                {source.message}
              </p>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
                {notes.evidenceKeys.map(([key, label]) => (
                  <div key={key} className="col-span-1 min-w-0">
                    <dt className="text-ash">{label}</dt>
                    <dd className="truncate font-mono text-[11px] text-sand" title={valueOf(source.evidence?.[key])}>
                      {valueOf(source.evidence?.[key])}
                    </dd>
                  </div>
                ))}
                {source.evidence?.blocked_reason ? (
                  <div className="col-span-2">
                    <dt className="text-ash">Blocked reason</dt>
                    <dd className="text-[11px] leading-relaxed text-amber-200/90">{String(source.evidence.blocked_reason)}</dd>
                  </div>
                ) : null}
              </dl>
              {source.movie?.url && <div className="mt-2"><ExternalLink href={source.movie.url}>Open the public movie page</ExternalLink></div>}
              {source.notes && source.notes.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {source.notes.map((note) => <li key={note} className="text-[11px] leading-relaxed text-ash/80">· {note}</li>)}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <div className="panel p-4 sm:p-5">
        <SectionHeading
          eyebrow="Verification"
          title="Theatre identity check"
          description="Each row is matched by the platform's own venue ID — not by name similarity alone. Similar-named malls are explicitly excluded below."
        />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[12px]">
            <thead>
              <tr className="border-b border-white/[0.08] text-[10px] uppercase tracking-wider text-ash">
                <th className="py-2 pr-3 font-medium">Your watchlist</th>
                <th className="py-2 pr-3 font-medium">Source venue name</th>
                <th className="py-2 pr-3 font-medium">Venue ID</th>
                <th className="py-2 pr-3 font-medium">Match</th>
                <th className="py-2 font-medium">Link</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.theatres.map((theatre) => {
                const observation = theatre.platforms.district;
                const verification = theatre.verification.district;
                return (
                  <tr key={theatre.id} className="border-b border-white/[0.04] align-top last:border-0">
                    <td className="py-2.5 pr-3">
                      <p className="font-medium text-sand">{theatre.name}</p>
                      <p className="text-[10px] text-ash">{theatre.area}</p>
                    </td>
                    <td className="py-2.5 pr-3 text-sand/90">{observation?.venue?.name ?? verification?.source_name ?? "—"}</td>
                    <td className="py-2.5 pr-3 font-mono text-[11px] text-ash">{observation?.venue?.id ?? "—"}</td>
                    <td className="py-2.5 pr-3">
                      <Chip tone={verification?.status === "verified" ? "live" : "warn"} className="!px-2 !py-0.5 text-[10px]">
                        {verification?.status ?? "unverified"}
                      </Chip>
                    </td>
                    <td className="py-2.5">
                      {observation?.venue?.url ? <ExternalLink href={observation.venue.url}>Venue</ExternalLink> : <span className="text-ash">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-ash">
          Last verification run {formatDateTime(snapshot.checked_at)} IST. Verifications refresh at least once a day from the
          platform&apos;s public Bengaluru cinema directory.
        </p>
      </div>

      {snapshot.excluded_lookalikes && snapshot.excluded_lookalikes.length > 0 && (
        <div className="panel p-4 sm:p-5">
          <SectionHeading
            eyebrow="Avoided confusion"
            title="Similar names we deliberately do not track"
            description="These venues are easy to mix up with your six. They are excluded unless you add them to config/monitor.json yourself."
          />
          <ul className="space-y-2">
            {snapshot.excluded_lookalikes.map((item) => (
              <li key={item.name} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
                <p className="text-[13px] font-medium text-sand">{item.name} {item.district_id && <span className="font-mono text-[10px] text-ash">#{item.district_id}</span>}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ash">{item.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {[
          {
            title: "What we request",
            body: "One District page per tracked movie per hour (Avengers and Ramayana). A descriptive User-Agent identifies this as a personal tracker. robots.txt is checked before each request and cached for a day.",
          },
          {
            title: "What we never do",
            body: "No CAPTCHA solving, no login or queue manipulation, no proxy/identity rotation, no private API reverse engineering, no fabricated showtimes or seat numbers.",
          },
          {
            title: "When a source blocks us",
            body: "The run is marked blocked/partial, the last successful platform snapshot is preserved with its age, and the dashboard says so. Other theatres and sources keep running.",
          },
        ].map((card) => (
          <div key={card.title} className="panel p-4">
            <p className="label text-flame/80">{card.title}</p>
            <p className="mt-2 text-[12px] leading-relaxed text-ash">{card.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
