import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SportsEdges from "@/pages/SportsEdges";
import type { SportsEdge } from "@/lib/sportsEdges";
import { copyWords } from "@/test/copyWords";

function edge(over: Partial<SportsEdge>): SportsEdge {
  return {
    market_id: "M", title: "UConn wins", our_prob: 0.78, market_prob: 0.32, edge_pct: 0.46, market_url: "https://k", source_url: "https://p",
    sport: "cfb", kind: "winner", side: "yes", entry_price: 0.31, maker: true, home: "UConn", away: "Syracuse",
    start_utc: "2026-10-03T16:00:00+00:00", game_id: "g1", tier: "flagged", candidate: true, reject_reasons: [], review: null,
    engine: "sports_cfb", engine_version: null, gate_status: "SHADOW", ...over,
  };
}

// Both sides of two games, as the API sends them, plus one game that failed the filter.
const EDGES: SportsEdge[] = [
  edge({ market_id: "a1", title: "UConn wins", side: "yes" }),
  edge({ market_id: "a2", title: "Syracuse wins", side: "no", our_prob: 0.22, market_prob: 0.68 }),
  edge({ market_id: "b1", game_id: "g2", home: "Iowa State", away: "West Virginia", title: "Iowa St. wins", our_prob: 0.82, market_prob: 0.6, tier: "flagged" }),
  edge({ market_id: "c1", game_id: "g3", home: "Army", away: "Temple", title: "Army wins", our_prob: 0.6, market_prob: 0.5, tier: "top_pick" }),
  edge({ market_id: "d1", game_id: "g4", tier: "filtered", edge_pct: null, candidate: false }),
];

function stub(edges: SportsEdge[]) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve({ edges, total: edges.length, limit: 200, offset: 0 }),
  })));
}

afterEach(() => vi.unstubAllGlobals());

describe("SportsEdges", () => {
  it("shows one row per game with the call, both probabilities and the gap", async () => {
    stub(EDGES);
    render(<SportsEdges />);
    expect(await screen.findByText("Army to win")).toBeInTheDocument();
    expect(screen.getAllByText("UConn to win")).toHaveLength(1); // the two sides of one game are one pick
    expect(screen.getAllByText("+46 pts").length).toBeGreaterThan(0);
  });

  it("features only reviewed, plausible picks and says so when there are none", async () => {
    stub(EDGES.filter((e) => e.tier !== "top_pick"));
    render(<SportsEdges />);
    expect(await screen.findByText("No pick passed review today.")).toBeInTheDocument();
    expect(screen.queryByText("Top picks (1)")).not.toBeInTheDocument();
  });

  it("counts the games that had no usable edge instead of listing them", async () => {
    stub(EDGES);
    render(<SportsEdges />);
    expect(await screen.findByText("1 more games had no usable edge.")).toBeInTheDocument();
  });

  it("stays inside its word budget: a page that needs more words should show a number instead", async () => {
    stub(EDGES);
    const { container } = render(<SportsEdges />);
    await screen.findByText("Army to win");
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("asks for another sport when a filter is pressed", async () => {
    stub(EDGES);
    render(<SportsEdges />);
    await screen.findByText("Army to win");
    fireEvent.click(screen.getByRole("button", { name: "NFL" }));
    await waitFor(() => expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(([u]) => String(u).includes("sport=nfl"))).toBe(true));
  });
});
