import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { WeatherPanel } from "@/components/WeatherPanel";
import type { WeatherPanelResponse } from "@/components/WeatherPanel";

const contract = (over: Partial<WeatherPanelResponse["contracts"][number]> = {}): WeatherPanelResponse["contracts"][number] => ({
  target: "KXHIGHNY-26OCT18",
  forecaster: "weather_high",
  our_prob: 0.7,
  market_prob: 0.65,
  outcome: 1,
  ...over,
});

function stubFetch(body: WeatherPanelResponse) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })));
}

afterEach(() => vi.unstubAllGlobals());

describe("WeatherPanel", () => {
  it("renders a 45-degree scatter with points coloured by outcome", async () => {
    stubFetch({
      as_of: "2026-10-18T12:00:00+00:00",
      settled_date: "26OCT18",
      contracts: [
        contract({ our_prob: 0.7, market_prob: 0.65, outcome: 1 }), // our > 0.5 and outcome = 1 => correct (green)
        contract({ our_prob: 0.3, market_prob: 0.45, outcome: 1 }), // our < 0.5 and outcome = 1 => missed (red)
        contract({ our_prob: 0.8, market_prob: 0.3, outcome: 0 }), // our > 0.5 and outcome = 0 => missed (red)
      ],
    });
    render(<WeatherPanel />);
    await waitFor(() => expect(screen.getByText("Weather & ERCOT")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Latest settled: 26OCT18")).toBeInTheDocument());
  });

  it("renders missing figures as dash, never zero", async () => {
    stubFetch({
      as_of: "2026-10-18T12:00:00+00:00",
      settled_date: "26OCT18",
      contracts: [
        contract({ our_prob: null, market_prob: 0.65, outcome: 1 }),
        contract({ our_prob: 0.7, market_prob: null, outcome: 0 }),
      ],
    });
    render(<WeatherPanel />);
    await waitFor(() => expect(screen.getByText("Weather & ERCOT")).toBeInTheDocument());
    // Both contracts should be filtered out since they have null figures
    await waitFor(() => expect(screen.getByText("No settled weather/ERCOT contracts yet.")).toBeInTheDocument());
  });

  it("renders empty state when there are no contracts", async () => {
    stubFetch({
      as_of: "2026-10-18T12:00:00+00:00",
      settled_date: null,
      contracts: [],
    });
    render(<WeatherPanel />);
    await waitFor(() => expect(screen.getByText("Weather & ERCOT")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("No settled weather/ERCOT contracts yet.")).toBeInTheDocument());
  });

  it("renders error message when API fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "weather panel unavailable" }) })));
    render(<WeatherPanel />);
    await waitFor(() => expect(screen.getAllByText(/weather panel unavailable/i)).toHaveLength(2));
  });
});