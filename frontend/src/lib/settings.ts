import type { Meta, Snapshot } from "../types";

const SETTINGS_KEY = "dw:settings:v1";
const SEEN_KEY = "dw:seen:v1";
const LEGACY_SEEN_KEY = "dw:seen-events:v1";

export interface Settings {
  enabledTheatres: string[] | null;
  enabledPlatforms: ("district" | "bookmyshow")[];
  notifyBrowser: boolean;
  notifyMovies: Record<string, boolean>;
  notifyOn: {
    shows: boolean;
    threeD: boolean;
    infinity: boolean;
    booking: boolean;
    availability: boolean;
    sourceIssues: boolean;
  };
}

export const defaultSettings: Settings = {
  enabledTheatres: null,
  enabledPlatforms: ["district"],
  notifyBrowser: false,
  notifyMovies: { "avengers-doomsday": true, ramayana: true },
  notifyOn: {
    shows: true, threeD: true, infinity: true, booking: true,
    availability: true, sourceIssues: true,
  },
};

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return defaultSettings;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      ...defaultSettings,
      ...parsed,
      enabledPlatforms: (parsed.enabledPlatforms ?? defaultSettings.enabledPlatforms)
        .filter((p) => p === "district"),
      notifyMovies: { ...defaultSettings.notifyMovies, ...(parsed.notifyMovies ?? {}) },
      notifyOn: { ...defaultSettings.notifyOn, ...(parsed.notifyOn ?? {}) },
    };
  } catch {
    return defaultSettings;
  }
}

export function saveSettings(settings: Settings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export function seenEventIds(): Set<string> {
  try {
    const raw = localStorage.getItem(SEEN_KEY) ?? localStorage.getItem(LEGACY_SEEN_KEY) ?? "[]";
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}

export function rememberEventIds(ids: string[]): void {
  const merged = Array.from(new Set([...seenEventIds(), ...ids])).slice(-3000);
  localStorage.setItem(SEEN_KEY, JSON.stringify(merged));
}

/** The JSON to paste into config/monitor.json so the collector pipeline picks it up. */
export function exportMonitorConfig(settings: Settings, snapshot: Snapshot, meta: Meta | null, allTheatreIds: string[]): string {
  const enabled = settings.enabledTheatres ?? allTheatreIds;
  return JSON.stringify(
    {
      _note: "Paste these values into config/monitor.json, commit, and the next hourly run uses them.",
      monitoring: {
        interval_minutes: meta?.monitoring.interval_minutes ?? 60,
        timezone: "Asia/Kolkata",
      },
      enabled_theatres: enabled,
      enabled_platforms: settings.enabledPlatforms,
      movies: snapshot.movies?.length
        ? snapshot.movies.map(({ movie }) => ({ id: movie.id, title: movie.title, target_dates: movie.target_dates }))
        : [{ id: snapshot.movie.id, title: snapshot.movie.title, target_dates: snapshot.movie.target_dates }],
    },
    null,
    2,
  );
}
