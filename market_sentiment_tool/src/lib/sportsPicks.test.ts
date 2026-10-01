import { describe, expect, it } from "vitest";

import { board, gapPoints, gapText, LARGE_GAP_POINTS, toPicks } from "@/lib/sportsPicks";
import type { SportsEdge } from "@/lib/sportsEdges";

function edge(over: Partial<SportsEdge> = {}): SportsEdge {
  return {
    market_id: "M1", title: "UConn wins", our_prob: 0.7, market_prob: 0.55, edge_pct: 0.1, market_url: "k", source_url: "p",
    sport: "cfb", kind: "winner", side: "yes", entry_price: 0.55, maker: true, home: "UConn", away: "Syracuse",
    start_utc: "2026-10-03T16:00:00+00:00", game_id: "g1", tier: "flagged", candidate: true, reject_reasons: [],
    review: null, engine: "sports_cfb", engine_version: null, gate_status: "SHADOW", ...over,
  };
}

describe("gap", () => {
  it("is the model minus the market for the side you would take", () => {
    expect(gapPoints(edge({ side: "yes", our_prob: 0.78, market_prob: 0.32 }))).toBeCloseTo(46);
    expect(gapPoints(edge({ side: "no", our_prob: 0.18, market_prob: 0.43 }))).toBeCloseTo(25);
    expect(gapText(46.3)).toBe("+46");
    expect(gapText(-4.2)).toBe("-4");
  });
});

describe("one pick per game", () => {
  it("folds the two sides of a winner market into one pick, naming the team to win", () => {
    const yes = edge({ market_id: "A", title: "UConn wins", side: "yes", our_prob: 0.78, market_prob: 0.32 });
    const no = edge({ market_id: "B", title: "Syracuse wins", side: "no", our_prob: 0.22, market_prob: 0.68 });
    const picks = toPicks([no, yes]);
    expect(picks).toHaveLength(1);
    expect(picks[0].call).toBe("UConn to win");
    expect(picks[0].model).toBe(78);
    expect(picks[0].market).toBe(32);
  });

  it("names the OTHER team when the kept row is the NO side, matching 'Iowa St.' to 'Iowa State'", () => {
    const pick = toPicks([edge({ title: "West Virginia wins", side: "no", home: "Iowa State", away: "West Virginia",
                                  our_prob: 0.18, market_prob: 0.41 })])[0];
    expect(pick.call).toBe("Iowa State to win");
    expect(pick.model).toBe(82);
    expect(pick.market).toBe(59);
    const abbrev = toPicks([edge({ title: "Iowa St. wins", side: "yes", home: "Iowa State", away: "West Virginia" })])[0];
    expect(abbrev.call).toBe("Iowa St. to win");
  });

  it("keeps a spread and a winner on the same game as two different bets", () => {
    const picks = toPicks([edge({ market_id: "W" }), edge({ market_id: "S", kind: "spread", title: "UConn by 6.5" })]);
    expect(picks.map((p) => p.kind).sort()).toEqual(["spread", "winner"]);
  });
});

describe("the board", () => {
  it("features only reviewed, plausible picks; a huge gap is shown as flagged, not featured", () => {
    const edges = [
      edge({ game_id: "a", market_id: "a", tier: "top_pick", our_prob: 0.62, market_prob: 0.5 }),
      edge({ game_id: "b", market_id: "b", tier: "top_pick", our_prob: 0.9, market_prob: 0.4 }),
      edge({ game_id: "c", market_id: "c", tier: "flagged" }),
      edge({ game_id: "d", market_id: "d", tier: "unreviewed" }),
      edge({ game_id: "e", market_id: "e", tier: "filtered", edge_pct: null, candidate: false }),
    ];
    const b = board(edges);
    expect(b.topPicks.map((p) => p.gameId)).toEqual(["a"]);
    expect(b.flagged.map((p) => p.gameId).sort()).toEqual(["b", "c"]);
    expect(b.unreviewed.map((p) => p.gameId)).toEqual(["d"]);
    expect(b.noEdge).toBe(1);
    expect(LARGE_GAP_POINTS).toBe(25);
  });

  it("says there is nothing to feature when nothing passed review, rather than inventing a list", () => {
    const b = board([edge({ tier: "flagged" })]);
    expect(b.topPicks).toEqual([]);
  });
});
