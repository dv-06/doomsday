import type { HistoryEvent, Meta, RunRecord, Snapshot } from "../types";

const env = import.meta.env as Record<string, string | undefined>;
export const DATA_BASE = (env.VITE_DATA_BASE ?? "./data").replace(/\/$/, "");
export const API_BASE = env.VITE_API_BASE?.replace(/\/$/, "") ?? "";

const CACHE_KEY = "dw:cache:v1";

export interface CacheShape {
  savedAt: string;
  snapshot: Snapshot;
  meta: Meta | null;
}

export interface DashboardData {
  snapshot: Snapshot;
  meta: Meta | null;
  fromCache: boolean;
  savedAt: string | null;
}

async function fetchJson<T>(path: string, cacheBust = false): Promise<T> {
  const url = `${DATA_BASE}/${path}${cacheBust ? `?t=${Date.now()}` : ""}`;
  const response = await fetch(url, { cache: cacheBust ? "no-store" : "default" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

async function fetchJsonl<T>(path: string): Promise<T[]> {
  const response = await fetch(`${DATA_BASE}/${path}`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  const text = await response.text();
  const rows: T[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      rows.push(JSON.parse(trimmed) as T);
    } catch {
      // A partially written last line is skipped; the next run rewrites history.
    }
  }
  return rows;
}

function readCache(): CacheShape | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as CacheShape) : null;
  } catch {
    return null;
  }
}

function writeCache(next: CacheShape): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(next));
  } catch {
    // Storage full or disabled: the app still works from the network.
  }
}

export async function loadDashboard(force = false): Promise<DashboardData> {
  try {
    const [snapshot, meta] = await Promise.all([
      fetchJson<Snapshot>("latest.json", force),
      fetchJson<Meta>("meta.json", force).catch(() => null),
    ]);
    writeCache({ savedAt: new Date().toISOString(), snapshot, meta });
    return { snapshot, meta, fromCache: false, savedAt: null };
  } catch (error) {
    const cached = readCache();
    if (cached) {
      return { snapshot: cached.snapshot, meta: cached.meta, fromCache: true, savedAt: cached.savedAt };
    }
    throw error;
  }
}

export async function loadEvents(): Promise<HistoryEvent[]> {
  if (API_BASE) {
    const response = await fetch(`${API_BASE}/api/history/events?limit=5000`);
    if (response.ok) {
      const payload = (await response.json()) as { events: HistoryEvent[] };
      return payload.events;
    }
  }
  const rows = await fetchJsonl<HistoryEvent>("history/events.jsonl");
  return rows.reverse();
}

export async function loadRuns(): Promise<RunRecord[]> {
  if (API_BASE) {
    const response = await fetch(`${API_BASE}/api/history/runs?limit=2000`);
    if (response.ok) {
      const payload = (await response.json()) as { runs: RunRecord[] };
      return payload.runs;
    }
  }
  return fetchJsonl<RunRecord>("history/runs.jsonl");
}

/* ---------- formatting ---------- */

const IST = "Asia/Kolkata";

export function formatDate(date: string, opts: Intl.DateTimeFormatOptions = {}): string {
  const parsed = new Date(`${date}T12:00:00+05:30`);
  return new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: IST,
    ...opts,
  }).format(parsed);
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: IST,
  }).format(parsed).toUpperCase();
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: IST,
  }).format(parsed);
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "unknown";
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function timeUntil(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(diff)) return "—";
  if (diff <= 0) return "due now";
  const minutes = Math.round(diff / 60000);
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `in ${hours}h${rest ? ` ${rest}m` : ""}`;
}

export function countdown(target: string): string {
  const diff = new Date(`${target}T00:00:00+05:30`).getTime() - Date.now();
  if (diff <= 0) return "released";
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  return `${days}d ${hours}h`;
}

export function inr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN")}`;
}

/* ---------- design helpers ---------- */

export type Tone = "live" | "warn" | "danger" | "muted" | "ember";

export const availabilityTone: Record<string, Tone> = {
  bookable: "live",
  filling_fast: "ember",
  few_left: "warn",
  sold_out: "danger",
  unknown: "muted",
};

export const availabilityLabel: Record<string, string> = {
  bookable: "Bookable",
  filling_fast: "Filling fast",
  few_left: "Few left",
  sold_out: "Unavailable",
  unknown: "Unknown",
};

export const platformLabel: Record<string, string> = {
  district: "District",
  bookmyshow: "BookMyShow",
};

export const toneClasses: Record<Tone, string> = {
  live: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  warn: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  danger: "bg-red-500/10 text-red-300 border-red-500/25",
  muted: "bg-white/5 text-ash border-white/10",
  ember: "bg-ember/10 text-flame border-ember/30",
};

export const severityClasses: Record<string, string> = {
  high: "bg-ember/15 text-flame border-ember/30",
  medium: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  low: "bg-white/5 text-ash border-white/10",
};

export function formatBadgeClass(key: string): string {
  if (key.startsWith("imax")) return "bg-sky-500/10 text-sky-300 border-sky-500/30";
  if (key.startsWith("infinity_vision")) return "bg-ember/12 text-flame border-ember/35";
  if (key.includes("4dx")) return "bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/30";
  if (key.endsWith("3d") || key === "3d") return "bg-emerald-500/10 text-emerald-300 border-emerald-500/25";
  return "bg-white/5 text-ash border-white/10";
}

export const eventLabels: Record<string, string> = {
  theatre_listed: "Theatre listed",
  first_show: "First show",
  show_added: "New show",
  show_removed: "Show removed",
  format_added: "New format",
  booking_opened: "Booking opened",
  sold_out: "Sold out",
  seats_dropped: "Seats dropped",
  price_changed: "Price changed",
  date_added: "New date",
  source_blocked: "Source blocked",
  source_recovered: "Source recovered",
};

export const eventIcons: Record<string, string> = {
  theatre_listed: "🎬",
  first_show: "🎟️",
  show_added: "🕒",
  show_removed: "➖",
  format_added: "✨",
  booking_opened: "✅",
  sold_out: "⛔",
  seats_dropped: "📉",
  price_changed: "💸",
  date_added: "📅",
  source_blocked: "🚫",
  source_recovered: "🔁",
};
