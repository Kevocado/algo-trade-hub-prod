import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Health from "@/pages/Health";

const REPORT = {
  status: "degraded",
  generated_at: "2026-10-17T12:00:00+00:00",
  frozen_window_hours: 24,
  stale_after_hours: 2,
  timers: {
    scan: { last_success: "2026-10-17T11:50:00+00:00", age_seconds: 600, status: "ok" },
    journal: { last_success: null, age_seconds: null, status: "never" },
  },
  families: {
    weather_high: { frozen_24h: 20, cadence: "daily", expected_daily: true, silent: false },
  },
  orderbook: { newest_file_age_seconds: null, status: "missing" },
  problems: ["timer journal is never"],
};

function mockFetch(payload: unknown, ok = true) {
  return vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
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
    expect(screen.getByText("1/2")).toBeTruthy(); // timers fresh
    expect(screen.getByText("Never ran")).toBeTruthy(); // journal chip
    expect(screen.getByText("Missing")).toBeTruthy(); // order-book chip
    // A never-run timer and a missing file render as a dash, not 0.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("weather_high")).toBeTruthy();
    expect(screen.getByText("Degraded")).toBeTruthy();
  });

  it("reports a missing report as an error rather than a healthy page", async () => {
    vi.stubGlobal("fetch", mockFetch({ status: "ok", report: null }));
    render(<Health />);
    await waitFor(() => expect(screen.getByText(/No health report available/)).toBeTruthy());
  });
});
