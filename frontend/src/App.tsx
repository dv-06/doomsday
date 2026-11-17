import { Suspense, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, lazy } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import type { HistoryEvent, Meta, Snapshot } from "./types";
import { loadDashboard, loadEvents, relativeTime, timeUntil, toneClasses } from "./lib/data";
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
    <NavLink to="/" className="group flex items-center gap-3">
      <span className="relative grid h-10 w-10 place-items-center rounded-xl border border-ember/30 bg-ember/10 shadow-ember">
        <svg width="22" height="22" viewBox="0 0 64 64" aria-hidden="true">
          <path
            d="M32 6l5.2 16.4L54 17l-9.6 14.6L60 40l-16.4 4.6L46 60 32 49.4 18 60l2.4-15.4L4 40l15.6-8.4L10 17l16.8 5.4z"
            fill="#e2571e"
          />
        </svg>
      </span>
      <span className="leading-none">
        <span className="block font-display text-xl tracking-[0.16em] text-white">DOOMSDAY WATCH</span>
        <span className="mt-1 block text-[10px] font-medium uppercase tracking-[0.28em] text-ash">
          Bengaluru · Dec 2026
        </span>
      </span>
    </NavLink>
  );
}

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/history", label: "History" },
  { to: "/sources", label: "Sources" },
  { to: "/settings", label: "Settings" },
];

function Shell() {
  const { snapshot, meta, fromCache, refresh, loading, settings, updateSettings } = useAppData();
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
    <div className="relative min-h-screen">
      <div className="pointer-events-none fixed inset-0 z-0 opacity-[0.5] [background:radial-gradient(900px_500px_at_15%_-5%,rgba(226,87,30,0.16),transparent_60%)]" />
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
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
          <div className="flex items-center gap-2">
            {!settings.notifyBrowser && (
              <button type="button" onClick={enableNotifications} className="btn hidden !px-3 !py-1.5 text-xs sm:inline-flex">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  <path d="M10.3 21a1.9 1.9 0 003.4 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
                Alerts
              </button>
            )}
            <span className={`chip ${toneClasses[statusTone]} !px-3 !py-1.5`} title={fromCache ? "Showing cached data" : "Latest snapshot"}>
              <StatusDot tone={statusTone} pulse={!fromCache} />
              {statusLabel}
            </span>
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing || loading}
              className="btn !px-2.5 !py-1.5"
              aria-label="Refresh data"
              title={snapshot ? `Last check ${relativeTime(snapshot.checked_at)}` : "Refresh"}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true" className={refreshing ? "animate-spin" : ""}>
                <path d="M20 11a8 8 0 10-2.3 5.7M20 5v6h-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
        <div className="border-t border-white/[0.04] md:hidden">
          <nav className="hide-scrollbar mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-3 py-1.5">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium transition ${
                    isActive ? "bg-white/[0.07] text-white" : "text-ash"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <span className="ml-auto hidden whitespace-nowrap pl-2 text-[11px] text-ash sm:inline">
              Next {timeUntil(meta?.monitoring.next_check_at)}
            </span>
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-7xl px-4 pb-16 pt-6 sm:px-6 sm:pt-8">
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

      <footer className="relative z-10 border-t border-white/[0.06] bg-charcoal/60">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-xs text-ash sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            Doomsday Watch · free hourly tracker · data from public District pages
            {snapshot ? ` · snapshot ${relativeTime(snapshot.checked_at)}` : ""}
          </p>
          <p className="text-ash/80">
            Unavailable seats are not confirmed sales. Verify on the booking page before paying.
          </p>
        </div>
      </footer>
      <Toasts />
    </div>
  );
}

function Toasts() {
  const { notifications } = useToastState();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2">
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
