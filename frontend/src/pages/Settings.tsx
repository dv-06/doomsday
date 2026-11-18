import { useCallback, useEffect, useMemo, useState } from "react";
import { useAppData } from "../App";
import { exportMonitorConfig } from "../lib/settings";
import {
  ensurePermission,
  notificationDiagnostics,
  notificationSupport,
  sendTestNotification,
  type NotificationDiagnostics,
} from "../lib/notifications";
import { formatDateTime, relativeTime, timeUntil } from "../lib/data";
import { Chip, SectionHeading, Toggle } from "../components/ui";
function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn !min-h-[40px] !px-3 !py-1.5 text-[11px]"
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

export default function SettingsPage() {
  const { snapshot, meta, settings, updateSettings } = useAppData();
  const [permission, setPermission] = useState<NotificationPermission | null>(
    typeof Notification !== "undefined" ? Notification.permission : null,
  );
  const [diagnostics, setDiagnostics] = useState<NotificationDiagnostics | null>(null);
  const [testState, setTestState] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const support = notificationSupport();
  const effectivePermission = permission ?? (support.permission === "unsupported" ? null : support.permission);

  const refreshDiagnostics = useCallback(async () => {
    const next = await notificationDiagnostics();
    setDiagnostics(next);
    setPermission(next.permission === "unsupported" ? null : next.permission);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void refreshDiagnostics();
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.ready
        .then(() => {
          if (!cancelled) void refreshDiagnostics();
        })
        .catch(() => undefined);
    }
    const onNotification = () => void refreshDiagnostics();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshDiagnostics();
    };
    window.addEventListener("dw:notification", onNotification);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.removeEventListener("dw:notification", onNotification);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refreshDiagnostics]);

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
    await refreshDiagnostics();
  };

  const runTestNotification = async () => {
    setTesting(true);
    setTestState(null);
    try {
      const result = await sendTestNotification();
      setTestState({
        ok: result.ok,
        text: result.ok
          ? `Test notification sent via ${result.via === "service-worker" ? "the service worker" : "the page Notification API"}.`
          : result.error ?? "The browser refused the test notification.",
      });
    } catch (error) {
      setTestState({
        ok: false,
        text: error instanceof Error ? error.message : "Could not send the test notification.",
      });
    } finally {
      setTesting(false);
      await refreshDiagnostics();
    }
  };

  const permissionLabel = !support.supported
    ? "Unsupported"
    : effectivePermission === "granted"
      ? "Granted"
      : effectivePermission === "denied"
        ? "Blocked"
        : effectivePermission === "default"
          ? "Not requested"
          : "Unknown";
  const workerLabel = !diagnostics
    ? "Checking…"
    : diagnostics.serviceWorker === "active"
      ? "Active"
      : diagnostics.serviceWorker === "installing"
        ? "Installing"
        : diagnostics.serviceWorker === "waiting"
          ? "Waiting to activate"
          : diagnostics.serviceWorker === "unsupported"
            ? "Unsupported"
            : diagnostics.serviceWorker === "error"
              ? "Registration error"
              : "Not registered";
  const pushLabel = !diagnostics
    ? "Checking…"
    : diagnostics.push === "subscribed"
      ? "Subscribed"
      : diagnostics.push === "not-subscribed"
        ? "Not subscribed"
        : diagnostics.push === "unregistered"
          ? "Waiting for worker"
          : "Unsupported";
  const canTest = support.supported && effectivePermission === "granted";
  const testButtonLabel = testing
    ? "Sending…"
    : effectivePermission === "denied"
      ? "Blocked in browser settings"
      : !support.supported
        ? "Notifications unsupported"
        : !canTest
          ? "Enable notifications first"
          : "Send test notification";

  return (
    <div className="space-y-4 sm:space-y-5">
      <div>
        <p className="label text-flame/80">Configuration</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Settings</h1>
        <p className="mt-1 max-w-3xl text-sm text-ash">
          Display and alert preferences are stored in this browser. The monitoring schedule itself lives in the
          repository, so it keeps running when this browser — and your computer — is closed.
        </p>
      </div>

      <div className="grid min-w-0 gap-3 sm:gap-4 lg:grid-cols-2">
        <div className="panel min-w-0 p-3 sm:p-5">
          <SectionHeading
            eyebrow="Schedule"
            title="Hourly monitoring"
            description="The Indian-egress OpenWrt collector pushes District data hourly; GitHub Actions validates, ingests and commits it. The schedule is managed on the router, not in this browser."
          />
          <dl className="space-y-2.5 text-sm">
            <div className="flex flex-col gap-0.5 border-b border-white/[0.05] pb-2 last:border-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <dt className="text-ash">Interval</dt>
              <dd className="font-medium text-white">Every {meta?.monitoring.interval_minutes ?? 60} minutes</dd>
            </div>
            <div className="flex flex-col gap-0.5 border-b border-white/[0.05] pb-2 last:border-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <dt className="text-ash">Next check</dt>
              <dd className="font-medium text-white sm:text-right">{timeUntil(meta?.monitoring.next_check_at)}<span className="block text-[11px] font-normal leading-snug text-ash">{meta?.monitoring.schedule_note}</span></dd>
            </div>
            <div className="flex flex-col gap-0.5 border-b border-white/[0.05] pb-2 last:border-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <dt className="text-ash">Last successful run</dt>
              <dd className="font-medium text-white">{relativeTime(meta?.last_success_at ?? snapshot?.checked_at)}</dd>
            </div>
            <div className="flex flex-col gap-0.5 border-b border-white/[0.05] pb-2 last:border-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <dt className="text-ash">Locale</dt>
              <dd className="font-medium text-white">Asia/Kolkata (IST)</dd>
            </div>
          </dl>
          <div className="mt-4 rounded-xl border border-white/[0.06] bg-black/30 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="label">To change the schedule</p>
              <CopyButton text={cronSnippet} />
            </div>
            <pre className="mt-2 max-w-full overflow-x-auto whitespace-pre text-[10px] leading-relaxed text-ash sm:text-[10.5px]"><code>{cronSnippet}</code></pre>
            <p className="mt-2 text-[11px] leading-relaxed text-ash/80">
              GitHub&apos;s scheduler is best-effort: runs can be delayed by several minutes during peak load, and
              scheduled workflows are disabled after 60 days without repository activity. This project commits every
              hour, which keeps the workflow alive.
            </p>
          </div>
        </div>

        <div className="panel min-w-0 p-3 sm:p-5">
          <SectionHeading
            eyebrow="Notifications"
            title="Android browser alerts"
            description="Browser notifications are opt-in. Permission is requested only when you press the Enable control, never on page load."
          />
          <div className="mb-3 rounded-xl border border-white/[0.06] bg-black/30 p-2.5 text-[11px] leading-relaxed sm:p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="label">Status</span>
              <Chip tone={effectivePermission === "granted" && settings.notifyBrowser ? "live" : "muted"}>
                {!support.supported
                  ? "Unsupported browser"
                  : effectivePermission === "granted" && settings.notifyBrowser
                    ? "On (dashboard open)"
                    : effectivePermission === "denied"
                      ? "Blocked"
                      : effectivePermission === "granted"
                        ? "Permission granted, alerts off"
                        : "Off (default)"}
              </Chip>
            </div>
            <p className="mt-1.5 text-ash">
              {!support.supported
                ? "This browser has no Notification API. Use a current Chrome, Edge, Firefox or Safari release."
                : effectivePermission === "denied"
                  ? "Notifications are blocked for this site. Open the browser's site settings, allow notifications, then reload this page."
                  : effectivePermission === "default"
                    ? "Permission has not been requested. Turn on Browser notifications below; Android Chrome will show its own permission prompt."
                    : "Permission is granted. Alerts are checked every five minutes while this dashboard is open."}
            </p>
          </div>

          <dl className="mb-3 space-y-2 rounded-xl border border-white/[0.06] bg-black/20 p-3 text-[11px]">
            <div className="flex items-start justify-between gap-3">
              <dt className="text-ash">Permission</dt>
              <dd className="text-right font-medium text-white">{permissionLabel}</dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className="text-ash">Service worker</dt>
              <dd className="min-w-0 text-right font-medium text-white">
                {workerLabel}
                {diagnostics?.scope ? (
                  <span className="mt-0.5 block break-all font-normal text-ash">{diagnostics.scope}</span>
                ) : null}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className="text-ash">Push subscription</dt>
              <dd className="text-right font-medium text-white">{pushLabel}</dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className="text-ash">Background delivery</dt>
              <dd className="text-right font-medium text-sand">Unavailable — no push sender</dd>
            </div>
          </dl>

          <div className="rounded-xl border border-white/[0.06] bg-black/20 p-2.5">
            <p className="label mb-1.5">Last notification event</p>
            {diagnostics?.last ? (
              <div className="space-y-1">
                <p className="break-words text-[11px] font-medium text-white">{diagnostics.last.title}</p>
                <p className="break-words text-[11px] leading-relaxed text-ash">{diagnostics.last.body}</p>
                <p className="text-[10px] text-ash/80">
                  {formatDateTime(diagnostics.last.at)} · {diagnostics.last.ok ? "Delivered" : "Not delivered"} via{" "}
                  {diagnostics.last.via === "service-worker" ? "service worker" : diagnostics.last.via === "page" ? "page API" : "no channel"}
                </p>
                {diagnostics.last.error ? (
                  <p className="break-words text-[10.5px] text-red-300">{diagnostics.last.error}</p>
                ) : null}
              </div>
            ) : (
              <p className="text-[11px] text-ash">No notification has been sent from this browser yet.</p>
            )}
          </div>

          <div className="mt-3">
            <button
              type="button"
              className="btn min-h-[44px] w-full !py-2 text-xs"
              disabled={!canTest || testing}
              onClick={() => void runTestNotification()}
            >
              {testButtonLabel}
            </button>
            <p className="mt-1.5 text-[10.5px] leading-relaxed text-ash/80">
              The test is a harmless sample. It uses the same title, movie, cinema, date, IST time, format and event-type
              formatter as real session alerts.
            </p>
            {testState ? (
              <p
                role="status"
                aria-live="polite"
                className={`mt-1.5 break-words text-[11px] ${testState.ok ? "text-emerald-300" : "text-red-300"}`}
              >
                {testState.text}
              </p>
            ) : null}
          </div>

          <div className="mt-3 space-y-2">
            <Toggle
              label="Browser notifications"
              description={
                effectivePermission === "denied"
                  ? "Blocked in your browser settings. Re-enable notifications for this site, then reload."
                  : "Requests permission only when switched on. Alerts are delivered while a dashboard tab is open."
              }
              checked={settings.notifyBrowser && effectivePermission === "granted"}
              onChange={(next) => {
                if (next) void enableBrowser();
                else updateSettings({ notifyBrowser: false });
              }}
            />
            <div className="rounded-xl border border-white/[0.06] bg-black/20 p-2.5">
              <p className="label mb-1.5">Movie preferences</p>
              {(snapshot?.movies ?? []).map((entry) => (
                <Toggle
                  key={entry.movie.id}
                  label={entry.movie.title}
                  description={
                    entry.movie.id === "ramayana"
                      ? "Explicit 4DX 3D sessions only · 8 venues · 10 target dates"
                      : "Configured Bengaluru venues and supported formats"
                  }
                  checked={settings.notifyMovies[entry.movie.id] !== false}
                  onChange={(next) => updateSettings({
                    notifyMovies: { ...settings.notifyMovies, [entry.movie.id]: next },
                  })}
                />
              ))}
            </div>
            <Toggle
              label="New shows and first sessions"
              description="New session at a monitored cinema, or the first session published for a target date."
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
              description="Tracked separately from IMAX 3D and 4DX 3D."
              checked={settings.notifyOn.infinity}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, infinity: next } })}
            />
            <Toggle
              label="Availability changes"
              description="Source-reported seat-count drops and sold-out changes. Availability is never treated as confirmed sales."
              checked={settings.notifyOn.availability}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, availability: next } })}
            />
            <Toggle
              label="Booking opened alerts"
              checked={settings.notifyOn.booking}
              onChange={(next) => updateSettings({ notifyOn: { ...settings.notifyOn, booking: next } })}
            />
          </div>

          <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.05] p-3">
            <p className="label text-sand">Background push is not implemented</p>
            <p className="mt-1 text-[11px] leading-relaxed text-ash">
              GitHub Pages is a static host and cannot act as a push sender. This deployment has no server-side
              subscription store or VAPID private key, so the browser never creates a push subscription. Notifications
              therefore work only while the dashboard tab is open. They stop when the tab is backgrounded long enough
              for Chrome to freeze it, when Chrome is closed, or when the phone is locked.
            </p>
          </div>
        </div>
      </div>

      <div className="panel p-3 sm:p-5">
        <SectionHeading
          eyebrow="Watchlist"
          title="Theatres"
          description="These toggles control what this dashboard displays. To stop monitoring a theatre in the scheduled job, remove it from config/monitor.json (or disable its platform)."
          right={
            <button
              type="button"
              className="btn min-h-[44px] !py-1.5 text-[11px]"
              onClick={() => updateSettings({ enabledTheatres: allOn ? [] : theatreIds })}
            >
              {allOn ? "Hide all" : "Show all"}
            </button>
          }
        />
        <div className="grid gap-1.5 sm:grid-cols-2 sm:gap-2">
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
          <span className="label">Source</span>
          <span className="chip border-emerald-400/20 bg-emerald-400/10 text-emerald-300">District only</span>
          <span className="ml-auto text-[11px] text-ash">
            {settings.enabledTheatres === null ? "All theatres shown" : `${enabledTheatres.length}/${theatreIds.length} theatres shown`}
          </span>
        </div>
      </div>

      <div className="grid min-w-0 gap-3 sm:gap-4 lg:grid-cols-[minmax(0,1.4fr),minmax(0,1fr)]">
        <div className="panel min-w-0 overflow-hidden p-3 sm:p-5">
          <SectionHeading
            eyebrow="Repo config"
            title="Export your preferences"
            description="Commit these values to config/monitor.json so the hourly runner uses the same watchlist and interval. Display-only preferences stay in this browser."
            right={<CopyButton text={configJson} label="Copy JSON" />}
          />
          <pre className="max-h-64 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/[0.06] bg-black/40 p-2.5 text-[10.5px] leading-relaxed text-sand/90 sm:max-h-72 sm:p-3 sm:text-[11px]">
            <code>{configJson}</code>
          </pre>
          <p className="mt-1 text-[10.5px] text-ash/80">Scroll inside the box to see the full file. It contains no secrets.</p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-ash">
            <Chip tone="muted">{enabledTheatres.length} theatres</Chip>
            <Chip tone="muted">{settings.enabledPlatforms.join(" + ") || "no platforms"}</Chip>
            {(snapshot?.movies ?? []).map((entry) => (
              <Chip key={entry.movie.id} tone="muted">
                {entry.movie.title}: {entry.movie.target_dates.length} dates
              </Chip>
            ))}
            {!snapshot?.movies && <Chip tone="muted">{snapshot?.movie.target_dates.length ?? 0} target dates</Chip>}
          </div>
        </div>

        <div className="panel p-3 sm:p-5">
          <SectionHeading eyebrow="Local data" title="Reset this browser" />
          <p className="text-[12px] leading-relaxed text-ash">
            Clears cached snapshots, alert history and display preferences. Monitoring data on the server is untouched.
          </p>
          <button
            type="button"
            className="btn mt-3 min-h-[44px] w-full"
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
