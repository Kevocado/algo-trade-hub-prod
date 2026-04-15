import { describe, expect, it } from "vitest";

import {
  filterShadowSeriesByAsset,
  getShadowAssets,
  getShadowMarkerColor,
  getShadowMarkerRadius,
  getShadowThresholdValue,
  type ShadowPerformancePoint,
} from "@/lib/shadowPerformance";

const SERIES: ShadowPerformancePoint[] = [
  {
    timestamp: "2026-04-15T10:00:00Z",
    asset: "BTC",
    market_ticker: "BTC-1",
    probability_yes: 0.61,
    threshold_side: "YES",
    threshold_triggered: true,
    current_price: 63100,
    next_hour_price: 63220,
    realized_yes: 1,
    shadow_outcome: "win",
    correct: true,
    virtual_return_pct: 0.19,
  },
  {
    timestamp: "2026-04-15T11:00:00Z",
    asset: "ETH",
    market_ticker: "ETH-1",
    probability_yes: 0.43,
    threshold_side: "NO",
    threshold_triggered: true,
    current_price: 3180,
    next_hour_price: 3205,
    realized_yes: 1,
    shadow_outcome: "loss",
    correct: false,
    virtual_return_pct: -0.79,
  },
  {
    timestamp: "2026-04-15T12:00:00Z",
    asset: "BTC",
    market_ticker: "BTC-2",
    probability_yes: 0.52,
    threshold_side: null,
    threshold_triggered: false,
    current_price: 63220,
    next_hour_price: 63240,
    realized_yes: 1,
    shadow_outcome: "loss",
    correct: false,
    virtual_return_pct: 0,
  },
];

describe("shadowPerformance helpers", () => {
  it("extracts sorted asset symbols from series", () => {
    expect(getShadowAssets(SERIES)).toEqual(["BTC", "ETH"]);
  });

  it("filters series by asset", () => {
    expect(filterShadowSeriesByAsset(SERIES, "BTC")).toHaveLength(2);
    expect(filterShadowSeriesByAsset(SERIES, "ETH")).toHaveLength(1);
  });

  it("returns marker styling for win, loss, and hidden points", () => {
    expect(getShadowMarkerColor(SERIES[0])).toBe("#10b981");
    expect(getShadowMarkerColor(SERIES[1])).toBe("#f43f5e");
    expect(getShadowMarkerColor(SERIES[2])).toBe("transparent");
    expect(getShadowMarkerRadius(SERIES[0])).toBe(5);
    expect(getShadowMarkerRadius(SERIES[2])).toBe(0);
  });

  it("returns the yes threshold for the requested asset", () => {
    expect(getShadowThresholdValue({ BTC: { yes: 0.5751, no: 0.4249 } }, "BTC")).toBe(0.5751);
    expect(getShadowThresholdValue({ BTC: { yes: 0.5751, no: 0.4249 } }, "ETH")).toBeNull();
  });
});
