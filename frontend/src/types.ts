/** Shapes mirror data/latest.json produced by the Python monitor. */

export type Platform = "district" | "bookmyshow";
export type AvailabilityStatus = "bookable" | "filling_fast" | "few_left" | "sold_out" | "unknown";
export type PlatformStatus =
  | "ok"
  | "not_listed"
  | "blocked"
  | "error"
  | "unavailable"
  | "skipped"
  | "stale";

export interface ShowFormat {
  key: string;
  label: string;
  family: string;
  is_3d: boolean | null;
  is_premium: boolean;
  is_large_format: boolean;
  confidence: "explicit" | "inferred" | "unknown";
  raw: string;
}

export interface SeatArea {
  label: string;
  code?: string | null;
  price: number | null;
  total_seats: number | null;
  available_seats: number | null;
  status: AvailabilityStatus;
  status_raw?: string | null;
  bookable?: boolean;
}

export interface ShowAvailability {
  status: AvailabilityStatus;
  total_seats: number | null;
  available_seats: number | null;
  status_raw?: string | null;
  areas: SeatArea[];
  source_exposes_seat_count?: boolean;
}

export interface Show {
  id: string;
  platform: Platform;
  theatre_id: string;
  date: string;
  start: string;
  start_iso: string;
  screen: string | null;
  format: ShowFormat;
  languages: string[];
  price: { currency: string; min: number | null; max: number | null };
  availability: ShowAvailability;
  booking_url: string | null;
  source_time?: string | null;
  tags: string[];
  notes: string[];
  platforms?: Platform[];
}

export interface Venue {
  id?: string | null;
  name?: string | null;
  url?: string | null;
  address?: string | null;
  verified_name?: boolean;
  distance_km?: number | null;
}

export interface DateSummary {
  listed: boolean;
  shows: Show[];
  show_count: number;
  formats: { key: string; label: string; is_3d: boolean | null; is_premium: boolean; show_count: number }[];
  booking_status: AvailabilityStatus;
  seats_available: number | null;
  price_min: number | null;
  price_max: number | null;
  first_show: string | null;
  last_show: string | null;
  booking_links: { platform: Platform; url: string | null }[];
}

export interface PlatformObservation {
  platform: Platform;
  theatre_id: string;
  status: PlatformStatus;
  listed: boolean | null;
  venue: Venue;
  shows: Show[];
  dates: Record<string, { listed: boolean; shows: Show[] }>;
  error?: string | null;
  checked_at?: string;
  notes: string[];
  stale?: boolean;
  data_age_minutes?: number | null;
  last_success_at?: string | null;
  current_error?: string | null;
}

export type SeatRecommendation =
  | {
      mode: "layout";
      label: string;
      screen?: string | null;
      total_seats: number;
      available_seats: number;
      best: { row: string; number: string; x: number; y: number; type: string; score: number; reasons: string[] }[];
      second_best: { row: string; number: string; x: number; y: number; type: string; score: number; reasons: string[] }[];
      avoid: { row: string; number: string; x: number; y: number; reasons: string[] }[];
      depth_note: string;
      notes: string[];
      disclaimer: string;
      layout_file?: string;
    }
  | {
      mode: "heuristic";
      label: string;
      show_id: string;
      show_start: string;
      show_date: string;
      screen?: string | null;
      format: string;
      best: { area: string; price: number | null; available_seats: number; total_seats: number; fill_percent: number | null; status: AvailabilityStatus }[];
      second_best: { area: string; price: number | null; available_seats: number; total_seats: number; fill_percent: number | null; status: AvailabilityStatus }[];
      avoid: { area?: string; price?: number | null; reason: string }[];
      target_zone: { horizontal: string; depth_percent: number[]; depth_note: string };
      notes: string[];
      disclaimer: string;
    };

export interface Theatre {
  id: string;
  name: string;
  area: string;
  notes?: string;
  aliases?: string[];
  platforms: Partial<Record<Platform, PlatformObservation>>;
  dates: Record<string, DateSummary>;
  shows: Show[];
  formats: { key: string; label: string; is_3d: boolean | null; is_premium: boolean; count: number }[];
  format_keys: string[];
  listed: boolean;
  booking: {
    url: string | null;
    source_urls: { platform: Platform; url?: string | null }[];
    status: AvailabilityStatus;
    platforms: Platform[];
  };
  best_seats: SeatRecommendation | null;
  verification: Record<string, { status: string; source_name?: string | null; matched_alias?: string | null; note: string }>;
  health: {
    status: "live" | "partial" | "stale" | "unavailable" | "error";
    age_minutes: number | null;
    platforms_live?: string[];
    platforms_stale?: string[];
  };
  other_dates_seen?: string[];
}

export interface SourceInfo {
  source: Platform;
  status: "ok" | "partial" | "blocked" | "error";
  message: string;
  checked_at: string;
  last_success_at?: string | null;
  evidence: Record<string, unknown>;
  movie?: {
    title?: string;
    release_date?: string;
    url?: string | null;
    content_id?: string;
    event_code?: string;
    show_dates?: string[];
  };
  notes?: string[];
}

export interface Totals {
  theatres_monitored: number;
  theatres_with_listings: number;
  shows_total: number;
  shows_3d: number;
  shows_infinity_vision_3d: number;
  shows_imax_3d: number;
  shows_4dx: number;
  shows_4dx_3d: number;
  movies_tracked?: number;
  bookable_shows: number;
  seats_available_total: number;
  dates: Record<
    string,
    { shows: number; theatres: number; shows_3d: number; shows_infinity_vision_3d: number; shows_4dx_3d?: number }
  >;
  theatre_errors: { theatre_id: string; error: string }[];
}

export interface MovieInfo {
  id: string;
  title: string;
  release_date: string;
  target_dates: string[];
  required_format_keys?: string[];
  district_content_id: string;
  district_url: string | null;
  poster: string | null;
  duration_minutes: number | null;
}

/** One tracked film inside a multi-movie snapshot. */
export interface MovieSnapshot {
  schema_version: number;
  run_id: string;
  checked_at: string;
  status: "ok" | "partial" | "degraded";
  movie: MovieInfo;
  totals: Totals;
  theatres: Theatre[];
  sources: SourceInfo[];
  events: HistoryEvent[];
  provenance?: Record<string, unknown>;
}

export interface Snapshot {
  schema_version: number;
  run_id: string;
  checked_at: string;
  started_at: string;
  duration_ms: number;
  status: "ok" | "partial" | "degraded";
  movie: MovieInfo;
  movies?: MovieSnapshot[];
  totals: Totals;
  theatres: Theatre[];
  sources: SourceInfo[];
  excluded_lookalikes?: { name: string; district_id?: string; reason: string }[];
  events: HistoryEvent[];
  notifications?: { channels: string[]; sent: unknown[]; errors: unknown[] };
}

export interface Meta {
  schema_version: number;
  generated_at: string;
  run_id: string;
  run_status: string;
  trigger: string;
  monitoring: {
    interval_minutes: number;
    timezone: string;
    next_check_at: string;
    schedule_note: string;
  };
  last_success_at: string | null;
  counts: Totals;
  events_last_run: number;
  sources: Record<string, { status: string; message: string; checked_at: string; last_success_at?: string | null }>;
  notifications: { channels: string[]; sent: number; errors: unknown[] };
}

export interface HistoryEvent {
  movie_id?: string;
  movie_title?: string;
  id: string;
  type: string;
  severity: "high" | "medium" | "low";
  theatre_id: string;
  theatre_name: string;
  platform: string;
  date: string | null;
  start: string | null;
  screen: string | null;
  message: string;
  data: Record<string, unknown>;
  time_basis?: "ist";
  created_at: string;
}

export interface RunRecord {
  run_id: string;
  checked_at: string;
  status: string;
  totals: Totals;
  duration_ms: number;
  sources?: Record<string, string>;
}