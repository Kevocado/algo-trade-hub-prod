import { describe, expect, it } from "vitest";

import { edgeGate } from "@/lib/edgeGate";
import type { SportsEdge } from "@/lib/sportsEdges";

/** A sports edge as the API returns it. Sports rows must badge exactly like weather/gas. */
const edge = (over: Partial<SportsEdge> = {}): SportsEdge => ({
  market_id: "KXNFLGAME-26SEP27HOUIND-IND",
  title: "IND or KC",
  our_prob: 0.2954,
  market_prob: 0.3,
  edge_pct: 0.04,
  market_url: "https://kalshi.com/markets/kxnflgame",
  source_url: "https://example.invalid/?sport=nfl",
  sport: "nfl",
  kind: "winner",
  side: "yes",
  entry_price: 0.27,
  maker: true,
  home: "IND",
  away: "HOU",
  start_utc: "2026-09-27T23:20:00+00:00",
  game_id: "2026_03_HOU_IND",
  tier: "top_pick",
  candidate: true,
  reject_reasons: [],
  review: null,
  engine: "sports_nfl",
  engine_version: "feed:ridge@2026-09-04T22:12:49.750941+00:00",
  gate_status: "SHADOW",
  ...over,
});

describe("sports edge gate badge", () => {
  it("shows Shadow for a SHADOW sports edge", () => {
    expect(edgeGate(edge())).toEqual({ isShadow: true, label: "Shadow" });
  });

  it("shows Promoted once the (engine, engine_version) pair is promoted", () => {
    expect(edgeGate(edge({ gate_status: "PROMOTED" }))).toEqual({ isShadow: false, label: "Promoted" });
  });

  it("fails closed on a missing or unknown gate_status", () => {
    // Legacy rows written before the gate field existed must read as Shadow, never Promoted.
    expect(edgeGate(edge({ gate_status: null })).isShadow).toBe(true);
    expect(edgeGate(edge({ gate_status: undefined as unknown as string })).isShadow).toBe(true);
    expect(edgeGate(edge({ gate_status: "promoted " })).isShadow).toBe(false);
    expect(edgeGate(edge({ gate_status: "weird" })).isShadow).toBe(true);
  });
});
