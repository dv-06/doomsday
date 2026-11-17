import type { HistoryEvent } from "../types";
import type { Settings } from "./settings";
import { rememberEventIds, seenEventIds } from "./settings";

const HIGH_VALUE_TYPES = new Set([
  "theatre_listed",
  "first_show",
  "format_added",
  "booking_opened",
]);

export function wantsNotification(event: HistoryEvent, settings: Settings): boolean {
  if (event.type === "source_blocked" || event.type === "source_recovered") {
    return settings.notifyOn.sourceIssues;
  }
  if (event.type === "booking_opened") return settings.notifyOn.booking;
  if (event.type === "theatre_listed" || event.type === "first_show" || event.type === "show_added") {
    return settings.notifyOn.shows;
  }
  if (event.type === "format_added") {
    const key = String(event.data?.format_key ?? "");
    if (key.startsWith("infinity_vision")) return settings.notifyOn.infinity;
    if (key.includes("3d")) return settings.notifyOn.threeD;
    return settings.notifyOn.shows;
  }
  return false;
}

export async function ensurePermission(): Promise<NotificationPermission> {
  if (!("Notification" in window)) return "denied";
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  return Notification.requestPermission();
}

/**
 * Alert on events that appeared since the last visit.
 * `seed` = true marks current events as seen without firing (first load).
 */
export function alertOnNewEvents(
  events: HistoryEvent[],
  settings: Settings,
  options: { seed?: boolean } = {},
): HistoryEvent[] {
  const seen = seenEventIds();
  const fresh = events.filter((event) => !seen.has(event.id));
  if (fresh.length === 0) return [];
  if (options.seed) {
    rememberEventIds(fresh.map((event) => event.id));
    return [];
  }

  const worthTelling = fresh.filter((event) => wantsNotification(event, settings));
  rememberEventIds(fresh.map((event) => event.id));
  if (!settings.notifyBrowser || !worthTelling.length) return worthTelling;
  if (!("Notification" in window) || Notification.permission !== "granted") return worthTelling;

  const top = worthTelling.slice(0, 3);
  for (const event of top) {
    try {
      new Notification(`Doomsday Watch · ${event.theatre_name}`, {
        body: event.message,
        tag: event.id,
        icon: "./favicon.ico",
      });
    } catch {
      // Some mobile browsers only allow notifications from a service worker.
    }
  }
  return worthTelling;
}

export function isHighValue(event: HistoryEvent): boolean {
  return HIGH_VALUE_TYPES.has(event.type) || event.severity === "high";
}
