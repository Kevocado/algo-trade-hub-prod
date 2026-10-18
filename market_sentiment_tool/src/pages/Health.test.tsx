import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Health from "@/pages/Health";

const REPORT = {
  status: "degraded",
  generated_at: "2026-10-17T12:00:00+00:00",
  frozen_window_hours: 24,
  stale_after_hours: 2,
  timers: {
    scan: { last_success: null, age_seconds: null, status: "not_tracked", tracked: false },
    journal: { last_success: null, age_seconds: null, status: "never", tracked: true },
  },
  untracked_timers: ["scan"],
  tracked_timer_count: 1,
  families: {
    weather_high: { frozen_24h: 20, cadence: "daily", expected_daily: true, silent: false },
  },
  orderbook: { newest_file_age_seconds: null, status: "missing" },
  problems: ["timer journal is never"],
};

function mockFetch(payload: unknown, ok = true, contentType = "application/json") {
  return vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    headers: { get: () => contentType },
    json: async () => payload,
  });
}

describe("Health page", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch({ status: "ok", report: REPORT }));
  });

  it("shows the timer, family and order-book facts and a dash for a missing age", async () => {
    render(<Health />);
    await waitFor(() => expect(screen.getByText("Timers fresh")).toBeTruthy());
    expect(screen.getByText("0/1")).toBeTruthy(); // only journal is tracked, and it never ran
    expect(screen.getByText("Never ran")).toBeTruthy(); // journal chip
    expect(screen.getByText("Not tracked")).toBeTruthy(); // scan chip, not "Never ran"
    expect(screen.getByText("Missing")).toBeTruthy(); // order-book chip
    // A never-run timer and a missing file render as a dash, not 0.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("weather_high")).toBeTruthy();
    expect(screen.getByText("Degraded")).toBeTruthy();
  });

  it("shows a healthy report as Healthy with no problems", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        status: "ok",
        report: {
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
          families: {
            weather_high: { frozen_24h: 12, cadence: "daily", expected_daily: true, silent: false },
          },
          orderbook: { newest_file_age_seconds: 1200, status: "ok" },
          problems: [],
        },
      }),
    );
    render(<Health />);
    await waitFor(() => expect(screen.getByText("2/2")).toBeTruthy());
    // The whole point: a healthy system with two untracked jobs must not read as degraded.
    expect(screen.queryByText("Degraded")).toBeNull();
    expect(screen.queryByText("Never ran")).toBeNull();
    expect(screen.queryByText("Problems:")).toBeNull();
    expect(screen.getByText("Problems")).toBeTruthy();
    // The untracked jobs are named and explained rather than dropped from the page.
    expect(screen.getByText(/write no record of each run/)).toBeTruthy();
    expect(screen.getAllByText("Not tracked").length).toBe(2);
    expect(screen.getByText("2 not tracked")).toBeTruthy();
  });

  it("reports an absent report as an error rather than a healthy page", async () => {
    vi.stubGlobal("fetch", mockFetch({ status: "ok", report: null }));
    render(<Health />);
    await waitFor(() => expect(screen.getByText(/has no health report/)).toBeTruthy());
  });

  it("reports the status when a non-JSON response comes back", async () => {
    vi.stubGlobal("fetch", mockFetch({}, false, "text/html"));
    render(<Health />);
    await waitFor(() => expect(screen.getByText(/status 500/)).toBeTruthy());
  });
});
