import { Suspense, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, lazy } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import type { HistoryEvent, Meta, Snapshot } from "./types";
import { loadDashboard, loadEvents, relativeTime, toneClasses } from "./lib/data";
import { alertOnNewEvents, ensurePermission } from "./lib/notifications";
import { defaultSettings, loadSettings, saveSettings, type Settings } from "./lib/settings";
import { StatusDot } from "./components/ui";
import Dashboard from "./pages/Dashboard";

// Recharts only ships with the history route, so keep it out of the first load.
const History = lazy(() => import("./pages/History"));
const Sources = lazy(() => import("./pages/Sources"));
const SettingsPage = lazy(() => import("./pages/Settings"));

interface AppState {
  snapshot: Snapshot | null;
  meta: Meta | null;
  fromCache: boolean;
  savedAt: string | null;
  loading: boolean;
  error: string | null;
  refresh: (force?: boolean) => Promise<void>;
  settings: Settings;
  updateSettings: (patch: Partial<Settings>) => void;
}

const AppContext = createContext<AppState | null>(null);

export function useAppData(): AppState {
  const value = useContext(AppContext);
  if (!value) throw new Error("useAppData must be used inside AppProvider");
  return value;
}

function Brand() {
  return (
    <NavLink to="/" className="group flex min-w-0 items-center gap-2.5 sm:gap-3" aria-label="Doomsday Watch dashboard">
      <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-ember/30 bg-ember/10 shadow-ember sm:h-10 sm:w-10">
        <svg width="22" height="22" viewBox="0 0 64 64" aria-hidden="true">
          <path
            d="M32 6l5.2 16.4L54 17l-9.6 14.6L60 40l-16.4 4.6L46 60 32 49.4 18 60l2.4-15.4L4 40l15.6-8.4L10 17l16.8 5.4z"
            fill="#e2571e"
          />
        </svg>
      </span>
      <span className="min-w-0 leading-none">
        <span className="block whitespace-nowrap font-display text-[15px] tracking-[0.13em] text-white sm:text-xl sm:tracking-[0.16em]">
          DOOMSDAY WATCH
        </span>
        <span className="mt-1 block whitespace-nowrap text-[8.5px] font-medium uppercase tracking-[0.2em] text-ash sm:text-[10px] sm:tracking-[0.28em]">
          Bengaluru · hourly watch
        </span>
      </span>
    </NavLink>
  );
}

const NAV = [
  { to: "/", label: "Dashboard", end: true, icon: "dashboard" },
  { to: "/history", label: "History", end: false, icon: "history" },
  { to: "/sources", label: "Sources", end: false, icon: "sources" },
  { to: "/settings", label: "Settings", end: false, icon: "settings" },
] as const;

function NavIcon({ name }: { name: (typeof NAV)[number]["icon"] }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" {...common}>
      {name === "dashboard" && <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>}
      {name === "history" && <><path d="M3 12a9 9 0 109-9 9 9 0 00-7.2 3.6L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>}
      {name === "sources" && <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></>}
      {name === "settings" && <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.6v.2h-4v-.2a1.7 1.7 0 00-1-1.6 1.7 1.7 0 00-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.6-1H2.8v-4H3a1.7 1.7 0 001.6-1 1.7 1.7 0 00-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 009 4.6a1.7 1.7 0 001-1.6v-.2h4V3a1.7 1.7 0 001 1.6 1.7 1.7 0 001.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 00-.3 1.9 1.7 1.7 0 001.6 1h.2v4H21a1.7 1.7 0 00-1.6 1z" /></>}
    </svg>
  );
}

function Shell() {
  const { snapshot, fromCache, refresh, loading, settings, updateSettings } = useAppData();
  const [refreshing, setRefreshing] = useState(false);
  const statusTone =
    fromCache || !snapshot ? "warn" : snapshot.status === "ok" ? "live" : snapshot.status === "partial" ? "ember" : "danger";
  const statusLabel = !snapshot ? "No data" : fromCache ? "Cached" : snapshot.status === "ok" ? "Live" : snapshot.status === "partial" ? "Partial" : "Degraded";

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refresh(true);
    } finally {
      setRefreshing(false);
    }
  };

  const enableNotifications = async () => {
    const permission = await ensurePermission();
    if (permission === "granted") updateSettings({ notifyBrowser: true });
  };

  return (
    <div className="relative min-h-[100dvh]">
      <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.5] [background:radial-gradient(900px_500px_at_15%_-5%,rgba(226,87,30,0.16),transparent_60%)]" />
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink/90 pt-[env(safe-area-inset-top)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-2 sm:gap-4 sm:px-6 sm:py-3">
          <Brand />
          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-2 text-sm font-medium transition ${
                    isActive ? "bg-white/[0.07] text-white" : "text-ash hover:bg-white/[0.04] hover:text-sand"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex shrink-0 items-center gap-2">
            {!settings.notifyBrowser && (
              <button type="button" onClick={enableNotifications} className="btn hidden !px-3 !py-1.5 text-xs sm:inline-flex">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  <path d="M10.3 21a1.9 1.9 0 003.4 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
                Alerts
              </button>
            )}
            <span className={`chip ${toneClasses[statusTone]} !px-2.5 !py-1.5 sm:!px-3`} title={fromCache ? "Showing cached data" : "Latest snapshot"}>
              <StatusDot tone={statusTone} pulse={!fromCache} />
              {statusLabel}
            </span>
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing || loading}
              className="btn !h-11 !min-w-11 !px-2.5 !py-1.5 sm:!h-auto sm:!min-w-0"
              aria-label="Refresh data"
              title={snapshot ? `Last check ${relativeTime(snapshot.checked_at)}` : "Refresh"}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true" className={refreshing ? "animate-spin" : ""}>
                <path d="M20 11a8 8 0 10-2.3 5.7M20 5v6h-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-7xl px-3 pb-28 pt-4 sm:px-6 sm:pb-16 sm:pt-8">
        <Suspense fallback={<p className="py-16 text-center text-sm text-ash">Loading view…</p>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/history" element={<History />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Dashboard />} />
          </Routes>
        </Suspense>
      </main>

      <footer className="relative z-10 border-t border-white/[0.06] bg-charcoal/60 pb-[calc(4.75rem+env(safe-area-inset-bottom))] md:pb-0">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-5 text-xs text-ash sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:py-6">
          <p>
            Doomsday Watch · free hourly tracker · data from public District pages
            {snapshot ? ` · snapshot ${relativeTime(snapshot.checked_at)}` : ""}
          </p>
          <p className="text-ash/80">
            Unavailable seats are not confirmed sales. Verify on the booking page before paying.
          </p>
        </div>
      </footer>
      <MobileNav />
      <Toasts />
    </div>
  );
}

function MobileNav() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-white/[0.08] bg-ink/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden"
      aria-label="Primary"
    >
      <div className="mx-auto grid max-w-lg grid-cols-4 px-1.5">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `relative flex min-h-[56px] flex-col items-center justify-center gap-1 rounded-lg px-1 py-1.5 text-[10px] font-medium transition ${
                isActive ? "text-flame" : "text-ash active:bg-white/[0.06]"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute top-0 h-0.5 w-7 rounded-full bg-flame" aria-hidden="true" />}
                <NavIcon name={item.icon} />
                <span>{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

function Toasts() {
  const { notifications } = useToastState();
  return (
    <div className="pointer-events-none fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom))] right-3 z-50 flex w-[min(92vw,380px)] flex-col gap-2 md:bottom-4 md:right-4">
      {notifications.map((toast) => (
        <div key={toast.id} className="pointer-events-auto panel-warm grain relative animate-rise p-3.5">
          <p className="label mb-1 text-flame">New change detected</p>
          <p className="text-sm leading-snug text-sand">{toast.message}</p>
          <p className="mt-1.5 text-[11px] text-ash">
            {toast.theatre_name} · {relativeTime(toast.created_at)}
          </p>
        </div>
      ))}
    </div>
  );
}

interface ToastState {
  notifications: HistoryEvent[];
  push: (events: HistoryEvent[]) => void;
}

const ToastContext = createContext<ToastState>({ notifications: [], push: () => undefined });
const useToastState = () => useContext(ToastContext);

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [notifications, setNotifications] = useState<HistoryEvent[]>([]);
  const seeded = useRef(false);

  const push = useCallback((events: HistoryEvent[]) => {
    if (!events.length) return;
    setNotifications((current) => [...events, ...current].slice(0, 2));
    window.setTimeout(() => {
      setNotifications((current) => current.filter((item) => !events.some((event) => event.id === item.id)));
    }, 9000);
  }, []);

  const refresh = useCallback(async (force = false) => {
    try {
      const data = await loadDashboard(force);
      setSnapshot(data.snapshot);
      setMeta(data.meta);
      setFromCache(data.fromCache);
      setSavedAt(data.savedAt);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load monitoring data");
    } finally {
      setLoading(false);
    }
  }, []);

  const updateSettings = useCallback((patch: Partial<Settings>) => {
    setSettings((current) => {
      const next = { ...current, ...patch };
      saveSettings(next);
      return next;
    });
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(true), 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const events = await loadEvents();
        if (cancelled) return;
        const seed = !seeded.current;
        seeded.current = true;
        const fresh = alertOnNewEvents(events, settings, { seed });
        if (!seed) push(fresh.filter((event) => event.severity !== "low"));
      } catch {
        // History may not exist yet on a fresh repo; not fatal for the dashboard.
      }
    };
    void poll();
    const timer = window.setInterval(poll, 5 * 60 * 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [settings, push]);

  const value = useMemo<AppState>(
    () => ({ snapshot, meta, fromCache, savedAt, loading, error, refresh, settings, updateSettings }),
    [snapshot, meta, fromCache, savedAt, loading, error, refresh, settings, updateSettings],
  );

  return (
    <AppContext.Provider value={value}>
      <ToastContext.Provider value={{ notifications, push }}>
        <HashRouter>
          <Shell />
        </HashRouter>
      </ToastContext.Provider>
    </AppContext.Provider>
  );
}

export { defaultSettings };
