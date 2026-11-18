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
  if (!settings.notifyBrowser) return false;
  if (event.movie_id && settings.notifyMovies[event.movie_id] === false) return false;
  if (event.type === "seats_dropped" || event.type === "sold_out") {
    return settings.notifyOn.availability;
  }
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

  for (const event of worthTelling.slice(0, 3)) {
    void showForegroundNotification(event);
  }
  return worthTelling;
}

export function notificationLink(event: HistoryEvent): string {
  const params = new URLSearchParams();
  if (event.movie_id) params.set("movie", event.movie_id);
  if (event.date) params.set("date", event.date);
  return `./#/history${params.size ? `?${params.toString()}` : ""}`;
}

async function showForegroundNotification(event: HistoryEvent): Promise<void> {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const title = `${event.movie_title ?? "Doomsday Watch"} · ${event.theatre_name}`;
  const options: NotificationOptions = {
    body: event.message,
    tag: event.id,
    icon: "./icon.svg",
    badge: "./icon.svg",
    data: { url: notificationLink(event) },
  };
  try {
    const registration = await navigator.serviceWorker?.ready;
    if (registration) {
      await registration.showNotification(title, options);
      return;
    }
  } catch {
    // fall through to the page-level Notification API
  }
  try {
    const notification = new Notification(title, options);
    notification.onclick = () => {
      window.focus();
      window.location.hash = notificationLink(event).replace("./", "");
    };
  } catch {
    // Foreground-only; closed-site delivery needs real Web Push (not configured).
  }
}

export function notificationSupport(): {
  supported: boolean;
  permission: NotificationPermission | "unsupported";
  serviceWorker: boolean;
  backgroundPush: false;
} {
  const supported = "Notification" in window;
  return {
    supported,
    permission: supported ? Notification.permission : "unsupported",
    serviceWorker: "serviceWorker" in navigator,
    backgroundPush: false,
  };
}

export function isHighValue(event: HistoryEvent): boolean {
  return HIGH_VALUE_TYPES.has(event.type) || event.severity === "high";
}
