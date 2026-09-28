import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import WithheldEdgesNotice, {
  RETENTION_SENTENCE,
  RETENTION_UNCONDITIONAL,
} from "@/components/WithheldEdgesNotice";
import { DISPLAY_ONLY_REASON, EDGES_READ_LIMIT, type WithheldEdge } from "@/lib/displayOnlyEngines";
// Type-only, deliberately: a value import would execute `@/lib/supabase`, which calls
// createClient() at module scope and throws in a test with no URL.
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
    expect(screen.getByText(new RegExp(`2 rows of the ${EDGES_READ_LIMIT} rows read`))).toBeTruthy();
  });

  it("states that the rows are not opportunities, and bounds their retention to the market's life", () => {
    // THE CRITICAL FIX. This used to assert `/not deleted/i` against a sentence that said "they are
    // not deleted either, so the record of what the scan did survives". That was false on screen:
    // `remove_closed_cpi_edges` deletes every cpi_nowcast row whose `expires_at` has passed, on
    // every hourly scan, so a row is gone within the hour its market closes. The claim had to be
    // bounded to what the data supports.
    const { container } = render(<WithheldEdgesNotice withheld={withheld([cpiEdge()])} />);
    const text = container.textContent ?? "";

    expect(text).toContain(RETENTION_SENTENCE);
    expect(text).toMatch(/while its market is still open/i);
    expect(text).toMatch(/deleted when that market closes/i);
    expect(screen.getByText(/shown for context, not as an opportunity/i)).toBeTruthy();
  });

  it("can never again claim the rows are not deleted", () => {
    // The anti-drift assertion, and the reason this test file is worth reading. It fails on the
    // old copy, so the overclaim cannot be reintroduced by a well-meaning edit to the paragraph.
    for (const phrase of RETENTION_UNCONDITIONAL) {
      const { container, unmount } = render(<WithheldEdgesNotice withheld={withheld([cpiEdge()])} />);
      expect(container.textContent?.toLowerCase()).not.toContain(phrase);
      unmount();
    }
  });

  it("counts the READ, not the table, and says so when the read is truncated", () => {
    // `useMarketEdges` reads the newest 100 rows. A heading reading "3 rows" is a claim about the
    // table and is not one -- the same hazard `/api/cpi-display` answers with its own `truncated`.
    const { container, unmount } = render(<WithheldEdgesNotice withheld={withheld([cpiEdge("a")])} />);
    expect(container.textContent).toContain(`1 row of the ${EDGES_READ_LIMIT} rows read`);
    expect(container.textContent).not.toMatch(/the table holds more/);
    unmount();

    const truncated = render(
      <WithheldEdgesNotice withheld={withheld([cpiEdge("a")])} truncated />,
    );
    expect(truncated.container.textContent).toContain(
      `1 row of the newest ${EDGES_READ_LIMIT} rows read`,
    );
    expect(truncated.container.textContent).toContain("the table holds more");
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
    expect(screen.getByText(new RegExp(`2 rows of the ${EDGES_READ_LIMIT}`))).toBeTruthy();
  });
});

/**
 * The failed read. This is the ambiguity the withholding rule was built to remove, reintroduced one
 * layer up: a Supabase error used to be swallowed into `console.error`, leaving both buckets empty,
 * so the notice rendered `null` -- which reads as "nothing was withheld", the one thing a reader
 * cannot be allowed to infer from a read that never happened.
 */
describe("WithheldEdgesNotice on a failed read", () => {
  it("renders a distinct could-not-read line rather than nothing at all", () => {
    render(<WithheldEdgesNotice withheld={[]} readError="relation kalshi_edges does not exist" />);

    expect(screen.getByTestId("edges-read-failure")).toBeTruthy();
    expect(screen.getByText(/could not read the edge ledger/i)).toBeTruthy();
    expect(screen.getByText("relation kalshi_edges does not exist")).toBeTruthy();
    expect(screen.getByText(/failed read, not an empty one/i)).toBeTruthy();
  });

  it("SUPPRESSES the authoritative copy entirely, so absence is not claimed", () => {
    // The critical half. "Nothing was withheld" is true only of a read that succeeded.
    const { container } = render(
      <WithheldEdgesNotice withheld={[]} readError="network request failed" />,
    );
    const text = container.textContent ?? "";

    expect(text).not.toContain(RETENTION_SENTENCE);
    for (const phrase of RETENTION_UNCONDITIONAL) {
      expect(text.toLowerCase()).not.toContain(phrase);
    }
    expect(text).not.toMatch(/rows read/i);
  });

  it("outranks a non-empty bucket: claim nothing rather than claim from a failed read", () => {
    // Defensive. The hook clears both buckets on failure, so this state should be unreachable -- but
    // if it ever is reachable, the failure has to win, because a row from a previous successful
    // read is a claim about the current one.
    render(<WithheldEdgesNotice withheld={withheld([cpiEdge()])} readError="boom" />);

    expect(screen.getByTestId("edges-read-failure")).toBeTruthy();
    expect(screen.queryByText(/KXCPI-26SEP09-T0\.3/)).toBeNull();
    expect(screen.queryByText(/not an edge engine/i)).toBeNull();
  });
});
