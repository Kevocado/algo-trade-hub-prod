import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SportsEdges from "@/pages/SportsEdges";

/** One edge row; the board reads these fields and renders `title`. */
const ROW = {
  market_id: "M", title: "Recovered game", our_prob: 0.7, market_prob: 0.5, edge_pct: 0.2,
  market_url: "https://k", source_url: "https://p", sport: "nfl", kind: "winner", side: "yes",
  entry_price: 0.4, maker: true, home: "A", away: "B", start_utc: "2026-10-03T16:00:00+00:00",
  game_id: "g1", tier: "flagged", candidate: true, reject_reasons: [], review: null,
  engine: "sports_nfl", engine_version: null, gate_status: "SHADOW",
};

afterEach(() => vi.unstubAllGlobals());

describe("sports board, recoverable failure", () => {
  it("lets the visitor retry after a failure instead of being stuck on the error", async () => {
    // The reachable half of CodeRabbit's #66 finding. `if (error) return <red text/>` replaced the
    // WHOLE page, including the sport selector, and `error` was never cleared. So one transient 500
    // bricked the board: no retry, no way to change sport, nothing but a full page reload. A stale
    // error surviving a good response is the same defect seen from the other side.
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        call += 1;
        if (call === 1) {
          return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ edges: [ROW], total: 1, limit: 200, offset: 0 }),
        });
      }),
    );

    render(<SportsEdges />);
    await waitFor(() => expect(screen.queryByText(/boom/)).toBeTruthy());

    // The page offers a way forward.
    fireEvent.click(screen.getByRole("button", { name: /retry|try again/i }));

    await waitFor(() => expect(screen.queryByText(/Recovered game/)).toBeTruthy());
    expect(screen.queryByText(/boom/)).toBeNull();
    expect(call).toBe(2);
  });
});
