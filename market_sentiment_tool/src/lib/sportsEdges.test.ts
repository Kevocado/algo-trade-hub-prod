import { describe, expect, it } from "vitest";

import { formatEdgePct, groupByTier, rejectReasonLabel, type SportsEdge } from "@/lib/sportsEdges";

const base: SportsEdge = {
  market_id: "KXNFLGAME-26SEP27HOUIND-IND", title: "IND wins", our_prob: 0.3, market_prob: 0.25, edge_pct: 0.075,
  market_url: "https://kalshi.com/markets/kxnflgame/professional-football-game/kxnflgame-26sep27houind",
  source_url: "https://sports.example.com/?sport=nfl&game=2026_03_HOU_IND", sport: "nfl", kind: "winner",
  side: "yes", entry_price: 0.25, maker: true, home: "IND", away: "HOU", start_utc: "2026-09-27T17:00:00+00:00",
  game_id: "2026_03_HOU_IND", tier: "top_pick", candidate: true, reject_reasons: [], review: null,
};

describe("sports edges", () => {
  it("groups edges into the four tiers in display order", () => {
    const groups = groupByTier([
      { ...base, market_id: "f", tier: "filtered" },
      { ...base, market_id: "t", tier: "top_pick" },
      { ...base, market_id: "u", tier: "unreviewed" },
      { ...base, market_id: "x", tier: "flagged" },
    ]);
    expect(groups.map((g) => g.tier)).toEqual(["top_pick", "flagged", "unreviewed", "filtered"]);
    expect(groups[0].edges.map((e) => e.market_id)).toEqual(["t"]);
  });

  it("drops empty tiers", () => {
    expect(groupByTier([base]).map((g) => g.tier)).toEqual(["top_pick"]);
  });

  it("formats edges as percentage points", () => {
    expect(formatEdgePct(0.075)).toBe("+7.5 pp");
  });

  it("labels reject reasons in plain words", () => {
    expect(rejectReasonLabel("calibration_insufficient")).toBe("predictor not yet calibrated here");
    expect(rejectReasonLabel("something_new")).toBe("something_new");
  });
});
