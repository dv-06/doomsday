import type { ReactNode } from "react";
import { availabilityLabel, availabilityTone, toneClasses, type Tone } from "../lib/data";

export function Chip({
  children,
  tone = "muted",
  className = "",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  title?: string;
}) {
  return (
    <span title={title} className={`chip ${toneClasses[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function StatusDot({ tone = "live", pulse = true }: { tone?: Tone; pulse?: boolean }) {
  const colors: Record<Tone, string> = {
    live: "bg-emerald-400",
    warn: "bg-amber-400",
    danger: "bg-red-400",
    muted: "bg-ash",
    ember: "bg-flame",
  };
  return (
    <span className="relative inline-flex h-2 w-2">
      {pulse && <span className={`absolute inline-flex h-full w-full rounded-full opacity-40 ${colors[tone]} animate-pulse-dot`} />}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${colors[tone]}`} />
    </span>
  );
}

export function AvailabilityChip({ status, raw }: { status: string; raw?: string | null }) {
  const tone = availabilityTone[status] ?? "muted";
  return (
    <Chip tone={tone} title={raw ? `Source status: ${raw}` : undefined}>
      {availabilityLabel[status] ?? status}
    </Chip>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  right,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <p className="label mb-1 text-flame/80">{eyebrow}</p>}
        <h2 className="text-xl font-semibold tracking-tight text-white sm:text-2xl">{title}</h2>
        {description && <p className="mt-1 max-w-2xl text-sm text-ash">{description}</p>}
      </div>
      {right}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex min-h-[56px] cursor-pointer items-start justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 transition hover:border-white/15 active:bg-white/[0.04] ${
        disabled ? "cursor-not-allowed opacity-50" : ""
      }`}
    >
      <span>
        <span className="block text-sm font-medium text-sand">{label}</span>
        {description && <span className="mt-0.5 block text-xs leading-relaxed text-ash">{description}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="relative mt-0.5 h-11 w-12 shrink-0"
      >
        <span
          className={`absolute left-0 top-1/2 h-7 w-12 -translate-y-1/2 rounded-full border transition ${
            checked ? "border-ember bg-ember/80" : "border-white/15 bg-white/10"
          }`}
          aria-hidden="true"
        />
        <span
          className={`absolute top-1/2 h-5 w-5 -translate-y-1/2 rounded-full bg-white shadow-sm transition-all ${
            checked ? "left-[25px]" : "left-1"
          }`}
          aria-hidden="true"
        />
      </button>
    </label>
  );
}

export function Bar({ value, max, tone = "ember" }: { value: number | null; max: number | null; tone?: "ember" | "live" | "danger" }) {
  const pct = max && max > 0 && value !== null ? Math.max(2, Math.min(100, Math.round((value / max) * 100))) : 0;
  const bg = tone === "live" ? "bg-emerald-400/80" : tone === "danger" ? "bg-red-400/70" : "bg-flame/80";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <div className={`h-full rounded-full ${bg}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ExternalLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-1 text-sm font-medium text-flame transition hover:text-ember hover:underline ${className}`}
    >
      {children}
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M7 17L17 7M17 7H9M17 7V15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </a>
  );
}
