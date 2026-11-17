import { useMemo, useState } from "react";
import { useAppData } from "../App";
import { exportMonitorConfig } from "../lib/settings";
import { ensurePermission } from "../lib/notifications";
import { relativeTime, timeUntil } from "../lib/data";
import { Chip, SectionHeading, Toggle } from "../components/ui";
import type { Platform } from "../types";

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn !px-2.5 !py-1.5 text-[11px]"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1800);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

const ALL_PLATFORMS: Platform[] = ["district", "bookmyshow"];

export default function SettingsPage() {
  const { snapshot, meta, settings, updateSettings } = useAppData();
  const [permission, setPermission] = useState<NotificationPermission | null>(
    typeof Notification !== "undefined" ? Notification.permission : null,
  );

  const theatreIds = useMemo(() => snapshot?.theatres.map((theatre) => theatre.id) ?? [], [snapshot]);
  const enabledTheatres = settings.enabledTheatres ?? theatreIds;
  const allOn = enabledTheatres.length === theatreIds.length;

  const configJson = useMemo(
    () => (snapshot ? exportMonitorConfig(settings, snapshot, meta, theatreIds) : ""),
    [settings, snapshot, meta, theatreIds],
  );

  const cronSnippet = `# .github/workflows/monitor.yml
on:
  schedule:
    - cron: "0 * * * *"   # hourly, UTC
  workflow_dispatch:

# config/monitor.json
"monitoring": { "interval_minutes": 60 }`;

  const toggleTheatre = (id: string, next: boolean) => {
    const current = new Set(enabledTheatres);
    if (next) current.add(id);
    else current.delete(id);
    updateSettings({ enabledTheatres: Array.from(current) });
  };

  const enableBrowser = async () => {
    const result = await ensurePermission();
    setPermission(result);
    if (result === "granted") updateSettings({ notifyBrowser: true });
  };

  return (
    <div className="space-y-5">
      <div>
        <p className="label text-flame/80">Configuration</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Settings</h1>
        <p className="mt-1 max-w-3xl text-sm text-ash">
          Display and alert preferences are stored in this browser. The monitoring schedule itself lives in the
          repository, so it keeps running when this browser — and your computer — is closed.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-4 sm:p-5">
          <SectionHeading
            eyebrow="Schedule"
            title="Hourly monitoring"
            description="The Indian-egress OpenWrt collector pushes District data hourly; GitHub Actions validates, ingests and commits it. The schedule is managed on the router, not in this browser."
          />
          <dl className="space-y-2.5 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ash">Interval</dt>
              <dd className="font-medium text-white">Every {meta?.monitoring.interval_minutes ?? 60} minutes</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ash">Next check</dt>
              <dd className="text-right font-medium text-white">{timeUntil(meta?.monitoring.next_check_at)}<span className="block text-[11px] font-normal text-ash">{meta?.monitoring.schedule_note}</span></dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ash">Last successful run</dt>
              <dd className="font-medium text-white">{relativeTime(meta?.last_success_at ?? snapshot?.checked_at)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ash">Locale</dt>
              <dd className="font-medium text-white">Asia/Kolkata (IST)</dd>
            </div>
          </dl>
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-black/30 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="label">To change the schedule</p>
              <CopyButton text={cronSnippet} />
            </div>
            <pre className="mt-2 overflow-x-auto text-[10.5px] leading-relaxed text-ash"><code>{cronSnippet}</code></pre>
            <p className="mt-2 text-[11px] leading-relaxed text-ash/80">
              GitHub&apos;s scheduler is best-effort: runs can be delayed by several minutes during peak load, and
              scheduled workflows are disabled after 60 days without repository activity. This project commits every
              hour, which keeps the workflow alive.
            </p>
          </div>
        </div>

        <div className="panel p-4 sm:p-5">
          <SectionHeading
            eyebrow="Notifications"
            title="Alert channels"
            description="Browser alerts only fire while this tab is open. For phone alerts with your computer off, use Telegram or ntfy — both free."
          />
          <div className="space-y-2">
            <Toggle
              label="Browser notifications"
              description={
                permission === "denied"
                  ? "Blocked in your browser settings. Re-enable notifications for this site to use them."
                  : "Fires for new shows, 3D/Infinity Vision releases and booking openings while the tab is open."
              }
              checked={settings.notifyBrowser && permission === "granted"}
              onChange={(next) => {
                if (next) void enableBrowser();
                else updateSettings({ notifyBrowser: false });
              }}
            />
            <Toggle
              label="New shows and theatre releases"
              checked={settings.notifyOn.shows}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, shows: next } })}
            />
            <Toggle
              label="3D show alerts"
              checked={settings.notifyOn.threeD}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, threeD: next } })}
            />
            <Toggle
              label="Infinity Vision 3D alerts"
              description="Tracked separately from IMAX 3D."
              checked={settings.notifyOn.infinity}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, infinity: next } })}
            />
            <Toggle
              label="Booking opened alerts"
              checked={settings.notifyOn.booking}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, booking: next } })}
            />
            <Toggle
              label="Source blocked / recovered"
              checked={settings.notifyOn.sourceIssues}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, sourceIssues: next } })}
            />
          </div>
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-black/30 p-3">
            <p className="label mb-1.5">Phone alerts (free)</p>
            <p className="text-[11px] leading-relaxed text-ash">
              Add repository secrets <code className="text-flame">TELEGRAM_BOT_TOKEN</code> +{" "}
              <code className="text-flame">TELEGRAM_CHAT_ID</code> (or <code className="text-flame">NTFY_TOPIC</code>) in
              GitHub → Settings → Secrets and variables → Actions. Optional Redis-free dedupe is handled in the run state.
            </p>
            <div className="mt-2 flex items-center justify-between gap-2">
              <code className="truncate text-[10.5px] text-sand">gh secret set TELEGRAM_BOT_TOKEN</code>
              <CopyButton text="gh secret set TELEGRAM_BOT_TOKEN" label="Copy" />
            </div>
            <p className="mt-2 text-[11px] text-ash/80">
              Test locally with <code className="text-flame">python -m doomsday_watch notify-test</code> after exporting the
              variables.
            </p>
          </div>
        </div>
      </div>

      <div className="panel p-4 sm:p-5">
        <SectionHeading
          eyebrow="Watchlist"
          title="Theatres and platforms"
          description="These toggles control what this dashboard displays. To stop monitoring a theatre in the scheduled job, remove it from config/monitor.json (or disable its platform)."
          right={
            <button
              type="button"
              className="btn !py-1.5 text-[11px]"
              onClick={() => updateSettings({ enabledTheatres: allOn ? [] : theatreIds })}
            >
              {allOn ? "Hide all" : "Show all"}
            </button>
          }
        />
        <div className="grid gap-2 sm:grid-cols-2">
          {snapshot?.theatres.map((theatre) => (
            <Toggle
              key={theatre.id}
              label={theatre.name}
              description={`${theatre.area} · ${theatre.listed ? "listings found" : "waiting for release"}`}
              checked={enabledTheatres.includes(theatre.id)}
              onChange={(next) => toggleTheatre(theatre.id, next)}
            />
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="label">Platforms</span>
          {ALL_PLATFORMS.map((platform) => {
            const active = settings.enabledPlatforms.includes(platform);
            return (
              <button
                key={platform}
                type="button"
                onClick={() =>
                  updateSettings({
                    enabledPlatforms: active
                      ? settings.enabledPlatforms.filter((item) => item !== platform)
                      : [...settings.enabledPlatforms, platform],
                  })
                }
                className={`chip transition ${active ? "border-ember/30 bg-ember/10 text-flame" : "border-white/10 bg-white/5 text-ash"}`}
              >
                {platform === "bookmyshow" ? "BookMyShow" : "District"} {active ? "on" : "off"}
              </button>
            );
          })}
          <span className="ml-auto text-[11px] text-ash">
            {settings.enabledTheatres === null ? "All theatres shown" : `${enabledTheatres.length}/${theatreIds.length} theatres shown`}
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr,1fr]">
        <div className="panel p-4 sm:p-5">
          <SectionHeading
            eyebrow="Repo config"
            title="Export your preferences"
            description="Commit these values to config/monitor.json so the hourly runner uses the same watchlist and interval. Display-only preferences stay in this browser."
            right={<CopyButton text={configJson} label="Copy JSON" />}
          />
          <pre className="max-h-72 overflow-auto rounded-xl border border-white/[0.06] bg-black/40 p-3 text-[11px] leading-relaxed text-sand/90">
            <code>{configJson}</code>
          </pre>
          <p className="mt-1 text-[10.5px] text-ash/80">Scroll inside the box to see the full file. It contains no secrets.</p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-ash">
            <Chip tone="muted">{enabledTheatres.length} theatres</Chip>
            <Chip tone="muted">{settings.enabledPlatforms.join(" + ") || "no platforms"}</Chip>
            <Chip tone="muted">{snapshot?.movie.target_dates.length ?? 0} target dates</Chip>
          </div>
        </div>

        <div className="panel p-4 sm:p-5">
          <SectionHeading eyebrow="Local data" title="Reset this browser" />
          <p className="text-[12px] leading-relaxed text-ash">
            Clears cached snapshots, alert history and display preferences. Monitoring data on the server is untouched.
          </p>
          <button
            type="button"
            className="btn mt-3 w-full"
            onClick={() => {
              for (const key of Object.keys(localStorage)) {
                if (key.startsWith("dw:")) localStorage.removeItem(key);
              }
              window.location.reload();
            }}
          >
            Clear local settings and cached data
          </button>
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-black/30 p-3 text-[11px] leading-relaxed text-ash">
            <p className="label mb-1">How the pieces fit</p>
            <p>
              Static React dashboard on GitHub Pages · OpenWrt collector → GitHub ingestion → Pages · JSON + SQLite-compatible
              snapshot store committed to git. No paid API, database or host is involved.
            </p>
          </div>
        </div>
      </div>

      <p className="text-center text-[11px] leading-relaxed text-ash/70">
        Preferences are saved in this browser only. Nothing here can weaken the platform access rules: the monitor
        never bypasses a challenge, CAPTCHA or login wall.
      </p>
    </div>
  );
}
