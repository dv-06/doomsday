import type { Meta, Snapshot } from "../types";

const SETTINGS_KEY = "dw:settings:v1";
const SEEN_KEY = "dw:seen-events:v1";

export interface Settings {
  enabledTheatres: string[] | null;
  enabledPlatforms: ("district" | "bookmyshow")[];
  notifyBrowser: boolean;
  notifyOn: {
    shows: boolean;
    threeD: boolean;
    infinity: boolean;
    booking: boolean;
    sourceIssues: boolean;
  };
}

export const defaultSettings: Settings = {
  enabledTheatres: null,
  enabledPlatforms: ["district", "bookmyshow"],
  notifyBrowser: false,
  notifyOn: { shows: true, threeD: true, infinity: true, booking: true, sourceIssues: true },
};

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return defaultSettings;
    return { ...defaultSettings, ...(JSON.parse(raw) as Partial<Settings>) };
  } catch {
    return defaultSettings;
  }
}

export function saveSettings(settings: Settings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export function seenEventIds(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export function rememberEventIds(ids: string[]): void {
  const merged = Array.from(new Set([...seenEventIds(), ...ids])).slice(-3000);
  localStorage.setItem(SEEN_KEY, JSON.stringify(merged));
}

/** The JSON to paste into config/monitor.json so GitHub Actions picks it up. */
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
      target_dates: snapshot.movie.target_dates,
    },
    null,
    2,
  );
}
