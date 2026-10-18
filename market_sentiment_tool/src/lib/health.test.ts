import { describe, expect, it } from "vitest";

import {
  HEALTH_INTRO,
  familyRows,
  formatAge,
  healthSummary,
  statusChip,
  timerRows,
  type HealthReport,
} from "@/lib/health";

// A consistent degraded report: one stale timer, one never-ran timer, one silent daily family, missing order books.
const REPORT: HealthReport = {
  status: "degraded",
  generated_at: "2026-10-17T12:00:00+00:00",
  frozen_window_hours: 24,
  stale_after_hours: 2,
  untracked_timers: [],
  tracked_timer_count: 3,
  timers: {
    scan: { last_success: "2026-10-17T11:50:00+00:00", age_seconds: 600, status: "ok", tracked: true },
    journal: { last_success: "2026-10-17T06:00:00+00:00", age_seconds: 21600, status: "stale", tracked: true },
    orderbooks: { last_success: null, age_seconds: null, status: "never", tracked: true },
  },
  families: {
    weather_high: { frozen_24h: 20, cadence: "daily", expected_daily: true, silent: false },
    weather_low: { frozen_24h: 0, cadence: "daily", expected_daily: true, silent: true },
    cpi_nowcast: { frozen_24h: 0, cadence: "monthly", expected_daily: false, silent: false },
  },
  orderbook: { newest_file_age_seconds: null, status: "missing" },
  problems: [],
};

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

describe("health formatting", () => {
  it("keeps the intro within the word budget", () => {
    expect(words(HEALTH_INTRO)).toBeLessThanOrEqual(15);
  });

  it("renders a missing age as a dash, never as zero", () => {
    expect(formatAge(null)).toBe("—");
    expect(formatAge(0)).toBe("0s");
  });

  it("renders ages in human units", () => {
    expect(formatAge(600)).toMatch(/m/);
    expect(formatAge(21600)).toMatch(/h/);
  });

  it("uses one- or two-word verdict chips", () => {
    for (const label of [
      statusChip("ok").label,
      statusChip("stale").label,
      statusChip("never").label,
      statusChip("missing").label,
      statusChip("degraded").label,
    ]) {
      expect(words(label)).toBeGreaterThanOrEqual(1);
      expect(words(label)).toBeLessThanOrEqual(2);
    }
  });

  it("summarizes counts for the big stats", () => {
    const s = healthSummary(REPORT);
    expect(s.totalTimers).toBe(3);
    expect(s.okTimers).toBe(1);
    expect(s.silentFamilies).toBe(1); // only the daily one; cpi is monthly and not silent
    expect(s.verdict).toBe("Degraded");
  });

  it("labels timers plainly and pairs each with a chip", () => {
    const rows = timerRows(REPORT);
    expect(rows.map((r) => r.name)).toEqual(["scan", "journal", "orderbooks"]);
    expect(rows[2].chip.label).toBe("Never ran");
  });

  // The healthy case that used to read "degraded": scan and settle run hourly and write no row
  // recording the run, so their marker can never be read. Calling that "never" made a working system
  // look broken on the one page whose only job is to be trusted about faults.
  const HEALTHY: HealthReport = {
    status: "ok",
    generated_at: "2026-10-17T12:00:00+00:00",
    frozen_window_hours: 24,
    stale_after_hours: 2,
    untracked_timers: ["scan", "settle"],
    tracked_timer_count: 2,
    timers: {
      scan: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
      settle: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
      journal: { last_success: "2026-10-17T11:50:00+00:00", age_seconds: 600, status: "ok", tracked: true },
      orderbooks: { last_success: "2026-10-17T11:40:00+00:00", age_seconds: 1200, status: "ok", tracked: true },
    },
    families: { weather_high: { frozen_24h: 12, cadence: "daily", expected_daily: true, silent: false } },
    orderbook: { newest_file_age_seconds: 1200, status: "ok" },
    problems: [],
  };

  it("renders an untracked timer as Not tracked, never as Never ran", () => {
    expect(statusChip("not_tracked").label).toBe("Not tracked");
    const rows = timerRows(HEALTHY);
    const scan = rows.find((r) => r.name === "scan");
    expect(scan?.chip.label).toBe("Not tracked");
    expect(scan?.age).toBe("—");
  });

  it("counts only tracked timers, so a healthy system reads 2/2 not 2/4", () => {
    const s = healthSummary(HEALTHY);
    expect(s.totalTimers).toBe(2);
    expect(s.okTimers).toBe(2);
    expect(s.untrackedTimers).toBe(2);
    expect(s.verdict).toBe("Healthy");
  });

  it("still counts a tracked timer that is stale", () => {
    const stale: HealthReport = {
      ...HEALTHY,
      status: "degraded",
      problems: ["timer journal is stale"],
      timers: {
        ...HEALTHY.timers,
        journal: { ...HEALTHY.timers.journal, status: "stale", age_seconds: 21600 },
      },
    };
    const s = healthSummary(stale);
    expect(s.okTimers).toBe(1); // orderbooks only; the two untracked never entered the denominator
    expect(s.totalTimers).toBe(2);
    expect(s.untrackedTimers).toBe(2);
    expect(s.verdict).toBe("Degraded");
  });

  it("lists families with their freeze counts and a quiet marker", () => {
    const rows = familyRows(REPORT);
    const weatherLow = rows.find((r) => r.name === "weather_low");
    expect(weatherLow?.frozen).toBe(0);
    expect(weatherLow?.silent).toBe(true);
    const cpi = rows.find((r) => r.name === "cpi_nowcast");
    expect(cpi?.silent).toBe(false);
  });
});
