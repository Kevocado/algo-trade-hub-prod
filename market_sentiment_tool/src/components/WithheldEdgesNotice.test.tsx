import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import WithheldEdgesNotice from "@/components/WithheldEdgesNotice";
import { DISPLAY_ONLY_REASON, type WithheldEdge } from "@/lib/displayOnlyEngines";
import type { KalshiEdge } from "@/hooks/useMarketEdges";

/**
 * The component that makes the withholding visible.
 *
 * The data layer already withholds a display-only row (useMarketEdges.test.tsx). What that cannot do
 * is tell a reader the row exists. A MACRO tab that just gets quieter is indistinguishable from an
 * engine that was retired, and Ruling 1 is explicit that the engine was relabelled, not removed.
 */

const cpiEdge = (id = "cpi-1"): KalshiEdge => ({
  id,
  market_id: "KXCPI-26SEP09-T0.3",
  edge_type: "MACRO",
  engine: "cpi_nowcast",
  gate_status: "SHADOW",
  market_prob: 0.32,
  our_prob: 0.52,
  edge_pct: 20.0,
  discovered_at: "2026-09-27T12:00:00Z",
  market_title: "Will CPI be above 3.0%?",
  raw_payload: {},
});

const withheld = (edges: KalshiEdge[]): WithheldEdge<KalshiEdge>[] =>
  edges.map((edge) => ({
    edge,
    engine: "cpi_nowcast" as const,
    reason: DISPLAY_ONLY_REASON.cpi_nowcast,
  }));

describe("WithheldEdgesNotice", () => {
  it("renders nothing at all for an empty bucket", () => {
    // No "0 display-only engines" line. A placeholder for an absence is the noise this exists to
    // remove, and it would sit on every page that has no CPI rows at all.
    const { container } = render(<WithheldEdgesNotice withheld={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("names the engine, its reason, and every withheld row", () => {
    render(<WithheldEdgesNotice withheld={withheld([cpiEdge("a"), cpiEdge("b")])} />);

    expect(screen.getByText("cpi_nowcast")).toBeTruthy();
    expect(screen.getByText(new RegExp("not an edge engine", "i"))).toBeTruthy();
    // Both rows, so "1 withheld" can never stand in for "2 withheld".
    expect(screen.getAllByText(/KXCPI-26SEP09-T0\.3/)).toHaveLength(2);
    expect(screen.getByText(/2 rows/)).toBeTruthy();
  });

  it("states that the rows are neither an opportunity nor deleted", () => {
    render(<WithheldEdgesNotice withheld={withheld([cpiEdge()])} />);
    expect(screen.getByText(/not deleted/i)).toBeTruthy();
    expect(screen.getByText(/shown for context, not as an opportunity/i)).toBeTruthy();
  });

  it("prints no edge figure, because the number is the thing being withheld", () => {
    // The row still carries edge_pct: 20.0. Printing it with a caveat attached would be the defect
    // with a footnote, so it is not printed at all.
    const { container } = render(<WithheldEdgesNotice withheld={withheld([cpiEdge()])} />);
    expect(container.textContent).not.toMatch(/20\.0/);
    expect(container.textContent).not.toMatch(/\d+(\.\d+)?\s*%\s*edge/i);
    expect(container.textContent).not.toMatch(/execute trade/i);
  });

  it("says not an edge engine exactly once however many rows are withheld", () => {
    // The reason is a paragraph. Repeating it per row would bury the rows it is about, and a
    // duplicated heading is the same noise in a different place.
    render(<WithheldEdgesNotice withheld={withheld([cpiEdge("a"), cpiEdge("b"), cpiEdge("c")])} />);
    expect(screen.getAllByText(/not an edge engine/i)).toHaveLength(1);
  });

  it("groups by engine, so a second display-only engine gets its own reason", () => {
    render(
      <WithheldEdgesNotice
        withheld={[
          ...withheld([cpiEdge("a")]),
          {
            edge: { ...cpiEdge("b"), id: "w-1", engine: "other_engine", market_id: "KXFUEL" },
            engine: "other_engine" as never,
            reason: "Not an edge engine. Fuel is a display engine too.",
          },
        ]}
      />,
    );
    expect(screen.getByText("cpi_nowcast")).toBeTruthy();
    expect(screen.getByText("other_engine")).toBeTruthy();
    expect(screen.getByText(/Fuel is a display engine too/)).toBeTruthy();
    expect(screen.getByText(/2 rows/)).toBeTruthy();
  });
});
