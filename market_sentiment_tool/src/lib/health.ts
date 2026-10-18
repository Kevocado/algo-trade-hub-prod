/**
 * Health page formatting. All counting, verdicts, and wording live here so the page (TSX) renders
 * and never computes a score. A missing figure is a dash, never a 0: a timer that never ran and a
 * timer that ran 0 seconds ago are different facts and must not look the same on screen.
 */

export interface HealthTimer {
  last_success: string | null;
  age_seconds: number | null;
  status: "ok" | "stale" | "never" | "not_tracked";
  /** False when the job writes no run marker, so there is nothing to read. See `not_tracked`. */
  tracked: boolean;
}

export interface HealthFamily {
  frozen_24h: number;
  cadence: string | null;
  expected_daily: boolean;
  silent: boolean;
}

export interface HealthOrderbook {
  newest_file_age_seconds: number | null;
  status: "ok" | "stale" | "missing";
}

export interface HealthReport {
  status: "ok" | "degraded";
  generated_at: string;
  frozen_window_hours: number;
  stale_after_hours: number;
  timers: Record<string, HealthTimer>;
  /** Timer names with no run marker. Listed, not hidden, and not counted as faults. */
  untracked_timers: string[];
  tracked_timer_count: number;
  families: Record<string, HealthFamily>;
  orderbook: HealthOrderbook;
  problems: string[];
}

/** Intro copy. Kept under the word budget and asserted by test. */
export const HEALTH_INTRO = "Freshness of every timer and forecaster. Read-only; nothing here is a forecast.";

export interface Chip {
  label: string;
  tone: "ok" | "warn" | "bad";
}

/** One- or two-word verdict for a status word. */
export function statusChip(status: string): Chip {
  switch (status) {
    case "ok":
      return { label: "OK", tone: "ok" };
    case "stale":
      return { label: "Stale", tone: "warn" };
    case "never":
      return { label: "Never ran", tone: "bad" };
    case "missing":
      return { label: "Missing", tone: "bad" };
    case "not_tracked":
      // A distinct word from "Never ran" on purpose. `not_tracked` means nobody is watching this job;
      // `never` means we watched and it has not succeeded. Both jobs run fine -- they just write no
      // row recording the run -- so calling them "never" made a healthy system read as degraded.
      return { label: "Not tracked", tone: "warn" };
    case "degraded":
      return { label: "Degraded", tone: "warn" };
    default:
      return { label: "—", tone: "warn" };
  }
}

/** Age in a short human unit. `null` is a dash, never 0. */
export function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export function healthSummary(report: HealthReport) {
  // Only tracked timers are in the denominator. "2/4 fresh" would read as two faults on a healthy
  // system; the two untracked jobs are reported by their own count so the gap stays visible.
  const timers = Object.values(report.timers).filter((t) => t.tracked);
  const okTimers = timers.filter((t) => t.status === "ok").length;
  const silentFamilies = Object.values(report.families).filter((f) => f.silent).length;
  const verdict = report.status === "ok" ? "Healthy" : "Degraded";
  return {
    totalTimers: timers.length,
    okTimers,
    untrackedTimers: Object.values(report.timers).filter((t) => !t.tracked).length,
    silentFamilies,
    problemCount: report.problems.length,
    verdict,
  };
}

/** Plain names for the timers; the key is the machine name and stays visible for grep. */
export const TIMER_LABELS: Record<string, string> = {
  scan: "Scan",
  settle: "Settle",
  journal: "Journal",
  orderbooks: "Order books",
};

export function timerRows(report: HealthReport) {
  return Object.entries(report.timers).map(([name, t]) => ({
    name,
    label: TIMER_LABELS[name] ?? name,
    chip: statusChip(t.status),
    age: formatAge(t.age_seconds),
    lastSuccess: t.last_success,
  }));
}

export function familyRows(report: HealthReport) {
  return Object.entries(report.families).map(([name, f]) => ({
    name,
    frozen: f.frozen_24h,
    cadence: f.cadence ?? "—",
    expectedDaily: f.expected_daily,
    silent: f.silent,
  }));
}
