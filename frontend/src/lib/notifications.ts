import type { HistoryEvent } from "../types";
import type { Settings } from "./settings";
import { formatClock, formatDate, legacyEventClock } from "./data";
import { rememberEventIds, seenEventIds } from "./settings";

const HIGH_VALUE_TYPES = new Set([
  "theatre_listed",
  "first_show",
  "format_added",
  "booking_opened",
]);

const RAMAYANA_DATES = new Set([
  "2026-11-18",
  "2026-11-19",
  "2026-11-21",
  "2026-11-22",
  "2026-11-28",
  "2026-11-29",
  "2026-12-05",
  "2026-12-06",
  "2026-12-12",
  "2026-12-13",
]);

const RAMAYANA_4DX_VENUES = new Set([
  "cinepolis-nexus-shantiniketan",
  "bhartiya-mall",
  "nexus-koramangala",
  "central-spirit-mall",
  "orion-mall",
  "superplex-forum-kanakapura",
  "global-mall-mysore-road",
  "vega-city",
]);

const LAST_NOTIFICATION_KEY = "dw:last-notification:v1";

export interface LastNotification {
  at: string;
  title: string;
  body: string;
  url: string;
  kind: "event" | "test";
  via: "service-worker" | "page" | "none";
  ok: boolean;
  error?: string;
}

export interface NotificationDiagnostics {
  supported: boolean;
  permission: NotificationPermission | "unsupported";
  serviceWorker: "unsupported" | "unregistered" | "installing" | "waiting" | "active" | "error";
  scope: string | null;
  controlled: boolean;
  push: "unsupported" | "unregistered" | "not-subscribed" | "subscribed";
  backgroundPush: false;
  last: LastNotification | null;
}

interface NotificationContent {
  title: string;
  body: string;
  tag: string;
  url: string;
  kind: "event" | "test";
  eventId?: string;
}

interface DeliveryResult {
  ok: boolean;
  via: "service-worker" | "page" | "none";
  error?: string;
}

function mapFormat(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const compact = value.trim().toLowerCase().replace(/[-_]+/g, " ");
  if (compact.includes("infinity") && compact.includes("4dx")) return null;
  if (compact.includes("4dx") && compact.includes("3d")) return "4DX 3D";
  if (compact.includes("imax") && compact.includes("3d")) return "IMAX 3D";
  if (compact.includes("infinity") && compact.includes("3d")) return "Infinity Vision 3D";
  if (/^(3d|3 d)$/.test(compact)) return "3D";
  return null;
}

/** The exact format label carried by the source event, never guessed from movie. */
export function eventFormat(event: HistoryEvent): string | null {
  const data = event.data ?? {};
  const direct = mapFormat(data.format) ?? mapFormat(data.format_label);
  if (direct) return direct;
  const key = mapFormat(data.format_key);
  if (key) return key;
  const message = event.message.match(/\b(4DX[-\s]?3D|IMAX[-\s]?3D|Infinity Vision 3D|3D)\b/i);
  if (message) return mapFormat(message[1]);
  return null;
}

function notificationLabel(event: HistoryEvent): string {
  switch (event.type) {
    case "theatre_listed":
      return event.movie_id === "ramayana" ? "New qualifying Bengaluru venue" : "New theatre venue";
    case "first_show":
      return "First show for this date";
    case "show_added":
      return "New show published";
    case "format_added":
      return "Qualifying format published";
    case "booking_opened":
      return "Booking opened";
    case "sold_out":
      return "Source reports sold out";
    case "seats_dropped":
      return "Availability dropped";
    default:
      return "Show update";
  }
}

function displayClock(event: HistoryEvent): { date: string; time: string } | null {
  if (!event.date || !event.start) return null;
  if (event.time_basis === "ist") {
    const iso = /^\d{2}:\d{2}$/.test(event.start)
      ? `${event.date}T${event.start}:00+05:30`
      : event.start;
    const time = formatClock(iso);
    if (time === "—") return null;
    return { date: event.date, time };
  }
  const legacy = legacyEventClock(event.date, event.start);
  return legacy ? { date: legacy.date, time: legacy.start } : null;
}

export function eventQualifiesForBrowser(event: HistoryEvent): boolean {
  if (!displayClock(event)) return false;
  if (!eventFormat(event)) return false;
  if (event.movie_id === "ramayana") {
    return Boolean(
      event.date &&
        RAMAYANA_DATES.has(event.date) &&
        RAMAYANA_4DX_VENUES.has(event.theatre_id) &&
        eventFormat(event) === "4DX 3D",
    );
  }
  return true;
}

export function wantsNotification(event: HistoryEvent, settings: Settings): boolean {
  if (!settings.notifyBrowser) return false;
  if (event.movie_id && settings.notifyMovies[event.movie_id] === false) return false;
  if (!eventQualifiesForBrowser(event)) return false;

  if (event.type === "seats_dropped" || event.type === "sold_out") {
    return settings.notifyOn.availability;
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

export function notificationContent(event: HistoryEvent): NotificationContent | null {
  const clock = displayClock(event);
  const format = eventFormat(event);
  if (!clock || !format) return null;
  const movie = event.movie_title ?? "Doomsday Watch";
  const title = `${movie} — ${event.theatre_name}`;
  const date = formatDate(clock.date, { weekday: "short", day: "numeric", month: "short" });
  let body = `${date} — ${clock.time} IST — ${format} — ${notificationLabel(event)}.`;
  if (event.type === "seats_dropped") {
    const before = event.data?.before;
    const after = event.data?.after;
    if (typeof before === "number" && typeof after === "number") {
      body += ` Source reports ${before} → ${after} seats available; not confirmed sales.`;
    }
  }
  return {
    title,
    body,
    tag: `dw:event:${event.id}`,
    url: notificationLink(event),
    kind: "event",
    eventId: event.id,
  };
}

export async function ensurePermission(): Promise<NotificationPermission> {
  if (!("Notification" in window)) return "denied";
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  try {
    return await Notification.requestPermission();
  } catch {
    return "denied";
  }
}

/**
 * Alert on events that appeared since the last visit.
 * `seed` = true marks current events as seen without firing (first load).
 * Seen IDs and stable source event IDs make repeated snapshots idempotent.
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
  const batch = worthTelling.slice(0, 3);
  // Deliver at most three per poll to avoid an Android notification storm. Any
  // remainder stays unseen and is delivered on the next poll, never duplicated.
  const deferred = new Set(worthTelling.slice(3).map((event) => event.id));
  rememberEventIds(fresh.filter((event) => !deferred.has(event.id)).map((event) => event.id));
  for (const event of batch) {
    const content = notificationContent(event);
    if (content) void deliverNotification(content);
  }
  return worthTelling;
}

export function notificationLink(event: HistoryEvent): string {
  const params = new URLSearchParams();
  if (event.movie_id) params.set("movie", event.movie_id);
  if (event.date) params.set("date", event.date);
  return `./#/history${params.size ? `?${params.toString()}` : ""}`;
}

function waitForReady(timeoutMs = 3500): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return Promise.resolve(null);
  return new Promise((resolve) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true;
        resolve(null);
      }
    }, timeoutMs);
    navigator.serviceWorker.ready
      .then((registration) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve(registration);
      })
      .catch(() => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve(null);
      });
  });
}

function saveLast(result: DeliveryResult, content: NotificationContent): void {
  const last: LastNotification = {
    at: new Date().toISOString(),
    title: content.title,
    body: content.body,
    url: content.url,
    kind: content.kind,
    via: result.via,
    ok: result.ok,
    ...(result.error ? { error: result.error } : {}),
  };
  try {
    localStorage.setItem(LAST_NOTIFICATION_KEY, JSON.stringify(last));
  } catch {
    // The notification still succeeded; only diagnostics are unavailable.
  }
  window.dispatchEvent(new CustomEvent<LastNotification>("dw:notification", { detail: last }));
}

async function deliverNotification(content: NotificationContent): Promise<DeliveryResult> {
  if (!("Notification" in window)) {
    return { ok: false, via: "none", error: "Notification API is not supported in this browser." };
  }
  if (Notification.permission !== "granted") {
    return { ok: false, via: "none", error: `Notification permission is ${Notification.permission}.` };
  }

  const options: NotificationOptions = {
    body: content.body,
    tag: content.tag,
    icon: "./icon.svg",
    lang: "en-IN",
    data: { url: content.url, kind: content.kind, event_id: content.eventId ?? null },
  };

  const registration = await waitForReady();
  if (registration) {
    try {
      await registration.showNotification(content.title, options);
      const result: DeliveryResult = { ok: true, via: "service-worker" };
      saveLast(result, content);
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Service worker refused the notification.";
      const result: DeliveryResult = { ok: false, via: "none", error: message };
      saveLast(result, content);
      return result;
    }
  }

  try {
    const notification = new Notification(content.title, options);
    notification.onclick = () => {
      window.focus();
      window.location.hash = content.url.replace("./", "");
      notification.close();
    };
    const result: DeliveryResult = { ok: true, via: "page" };
    saveLast(result, content);
    return result;
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : "No active service worker and the page Notification API is unavailable.";
    const result: DeliveryResult = { ok: false, via: "none", error: message };
    saveLast(result, content);
    return result;
  }
}

export async function sendTestNotification(): Promise<DeliveryResult> {
  const content: NotificationContent = {
    title: "Test notification — Ramayana — PVR Orion Mall",
    body: "Thu, 19 Nov — 10:20 PM IST — 4DX 3D — Sample notification.",
    tag: `dw:test:${Date.now()}`,
    url: "./#/history?movie=ramayana&date=2026-11-19",
    kind: "test",
  };
  return deliverNotification(content);
}

export function lastNotification(): LastNotification | null {
  try {
    const raw = localStorage.getItem(LAST_NOTIFICATION_KEY);
    return raw ? (JSON.parse(raw) as LastNotification) : null;
  } catch {
    return null;
  }
}

export async function notificationDiagnostics(): Promise<NotificationDiagnostics> {
  const supported = "Notification" in window;
  const serviceWorkerSupported = "serviceWorker" in navigator;
  let serviceWorker: NotificationDiagnostics["serviceWorker"] = serviceWorkerSupported
    ? "unregistered"
    : "unsupported";
  let scope: string | null = null;
  let registration: ServiceWorkerRegistration | null = null;

  if (serviceWorkerSupported) {
    try {
      registration = (await navigator.serviceWorker.getRegistration()) ?? null;
      if (registration) {
        scope = registration.scope;
        if (registration.active) serviceWorker = "active";
        else if (registration.waiting) serviceWorker = "waiting";
        else if (registration.installing) serviceWorker = "installing";
      }
    } catch {
      serviceWorker = "error";
    }
  }

  let push: NotificationDiagnostics["push"] = "unsupported";
  if (serviceWorkerSupported && typeof PushManager !== "undefined") {
    if (!registration) {
      push = "unregistered";
    } else {
      try {
        const subscription = await registration.pushManager.getSubscription();
        push = subscription ? "subscribed" : "not-subscribed";
      } catch {
        push = "unsupported";
      }
    }
  }

  return {
    supported,
    permission: supported ? Notification.permission : "unsupported",
    serviceWorker,
    scope,
    controlled: serviceWorkerSupported ? Boolean(navigator.serviceWorker.controller) : false,
    push,
    backgroundPush: false,
    last: lastNotification(),
  };
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
