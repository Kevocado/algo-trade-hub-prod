import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Weather from "@/pages/Weather";
import type { WeatherTodayRow, WeatherSettledRow } from "@/lib/weather";

const baseTodayRow = {
  strike_type: null as string | null,
  floor_strike: null as number | null,
  cap_strike: null as number | null,
  yes_sub_title: null as string | null,
  no_sub_title: null as string | null,
};

const TODAY: WeatherTodayRow[] = [
  { target: "kalshi:KXHIGHNY-26OCT18-T75", date: "26OCT18", ensemble: 0.65, kalshi: 0.6, climatology: 0.55, ...baseTodayRow },
  { target: "kalshi:KXHIGHLAX-26OCT18-T80", date: "26OCT18", ensemble: 0.45, kalshi: 0.5, climatology: 0.52, ...baseTodayRow },
];

const SETTLED: WeatherSettledRow[] = [
  {
    target: "kalshi:KXHIGHNY-26OCT17-T70",
    date: "26OCT17",
    ensemble: 0.7,
    kalshi: 0.72,
    climatology: 0.6,
    outcome: 1,
    realized_value: 92.0,
    settled_at: "2026-10-18T00:00:00+00:00",
    ...baseTodayRow,
  },
];

function mockWeather(today: WeatherTodayRow[], settled: WeatherSettledRow[]) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => ({ as_of: "2026-10-18T12:00:00+00:00", today, settled }),
  });
}

const renderWeather = () =>
  render(
    <MemoryRouter>
      <Weather />
    </MemoryRouter>,
  );

describe("weather page", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the city grid with all three probabilities", async () => {
    vi.stubGlobal("fetch", mockWeather(TODAY, SETTLED));
    renderWeather();
    await waitFor(() =>
      expect(screen.getByText(/ens 65%/)).toBeTruthy()
    );
    expect(screen.getByText(/kalshi 60%/)).toBeTruthy();
    expect(screen.getByText(/clim 55%/)).toBeTruthy();
    // Both cities appear with parsed labels (neutral fallback since no market metadata)
    expect(screen.getByText(/NYC high tail at 75°F/)).toBeTruthy();
    expect(screen.getByText(/Los Angeles high tail at 80°F/)).toBeTruthy();
  });

  it("shows settled history with outcome", async () => {
    vi.stubGlobal("fetch", mockWeather(TODAY, SETTLED));
    renderWeather();
    await waitFor(() => expect(screen.getByText("YES")).toBeTruthy());
    expect(screen.getByText(/92/)).toBeTruthy();
  });

  it("renders dashes for missing probabilities", async () => {
    const incomplete: WeatherTodayRow[] = [
      { target: "kalshi:KXHIGHNY-26OCT18-T75", date: "26OCT18", ensemble: null, kalshi: 0.6, climatology: null, ...baseTodayRow },
    ];
    vi.stubGlobal("fetch", mockWeather(incomplete, []));
    renderWeather();
    await waitFor(() => expect(screen.getByText(/ens —/)).toBeTruthy());
    expect(screen.getByText(/clim —/)).toBeTruthy();
  });

  it("shows empty state when no data", async () => {
    vi.stubGlobal("fetch", mockWeather([], []));
    renderWeather();
    await waitFor(() => expect(screen.getByText(/no weather data/i)).toBeTruthy());
  });

  it("reports an error when the API fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        headers: { get: () => "text/html" },
        json: async () => ({}),
      }),
    );
    renderWeather();
    await waitFor(() => expect(screen.getByText(/status 503/)).toBeTruthy());
  });
});