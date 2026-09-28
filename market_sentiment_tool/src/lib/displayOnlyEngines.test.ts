import { describe, expect, it } from "vitest";

import {
  DISPLAY_ONLY_ENGINES,
  DISPLAY_ONLY_REASON,
  displayOnlyReason,
  enforceDisplayOnlyPartition,
  isDisplayOnlyEdge,
  isDisplayOnlyEngine,
  partitionDisplayOnly,
} from "@/lib/displayOnlyEngines";

const row = (engine: string | null | undefined, extra: Record<string, unknown> = {}) => ({
  id: `row-${String(engine)}`,
  engine,
  edge_type: "MACRO",
  edge_pct: 12.5,
  ...extra,
});

describe("isDisplayOnlyEngine", () => {
  it("recognises exactly the ruled engines, case- and whitespace-insensitively", () => {
    expect(isDisplayOnlyEngine("cpi_nowcast")).toBe(true);
    expect(isDisplayOnlyEngine("CPI_NOWCAST")).toBe(true);
    expect(isDisplayOnlyEngine("  cpi_nowcast ")).toBe(true);
  });

  it("does not catch the other macro engine, or a row with no engine at all", () => {
    // labor_nowcast is separately ruled and is still an edge engine. A filter that swept the whole
    // MACRO bucket would be quietly removing a live, gated engine's opportunities.
    expect(isDisplayOnlyEngine("labor_nowcast")).toBe(false);
    expect(isDisplayOnlyEngine("weather")).toBe(false);
    expect(isDisplayOnlyEngine("gas")).toBe(false);
    expect(isDisplayOnlyEngine("sports_nfl")).toBe(false);
    expect(isDisplayOnlyEngine(null)).toBe(false);
    expect(isDisplayOnlyEngine(undefined)).toBe(false);
    expect(isDisplayOnlyEngine("")).toBe(false);
    expect(isDisplayOnlyEngine(7 as unknown as string)).toBe(false);
  });

  it("is an engine-level rule, so it does not depend on edge_type", () => {
    // The MACRO bucket also holds labor_nowcast. Keying the filter on edge_type would remove
    // labor's edges too.
    expect(isDisplayOnlyEdge(row("cpi_nowcast", { edge_type: "MACRO" }))).toBe(true);
    expect(isDisplayOnlyEdge(row("labor_nowcast", { edge_type: "MACRO" }))).toBe(false);
    expect(isDisplayOnlyEdge(null)).toBe(false);
    expect(isDisplayOnlyEdge(undefined)).toBe(false);
  });
});

describe("displayOnlyReason", () => {
  it("states in words that this is not an edge engine, and why", () => {
    const reason = displayOnlyReason(row("cpi_nowcast"));
    expect(reason).toBe(DISPLAY_ONLY_REASON.cpi_nowcast);
    expect(reason).toMatch(/not an edge engine/i);
    // The numbers, because "not an edge" without a reason reads as a shrug.
    expect(reason).toMatch(/0\.0710/);
    expect(reason).toMatch(/0\.0677/);
    expect(reason).toMatch(/market/i);
  });

  it("carries no edge figure, because there is not one to report", () => {
    // A reader shown a probability beside a price assumes an edge unless something says otherwise;
    // the label must not then hand them a number that looks like one.
    expect(DISPLAY_ONLY_REASON.cpi_nowcast).not.toMatch(/\b\d+\.\d+ ?pp\b/);
  });

  it("is null for an engine that is still an edge engine", () => {
    expect(displayOnlyReason(row("labor_nowcast"))).toBeNull();
    expect(displayOnlyReason(row(null))).toBeNull();
    expect(displayOnlyReason(undefined)).toBeNull();
  });
});

describe("partitionDisplayOnly", () => {
  it("withholds cpi_nowcast and keeps every other engine", () => {
    const rows = [
      row("cpi_nowcast"),
      row("weather"),
      row("cpi_nowcast", { id: "row-2" }),
      row("labor_nowcast"),
      row("sports_nfl"),
      row(null),
    ];

    const { edges, withheld } = partitionDisplayOnly(rows);

    expect(edges.map((e) => e.engine)).toEqual(["weather", "labor_nowcast", "sports_nfl", null]);
    expect(withheld.map((w) => w.edge.id)).toEqual(["row-cpi_nowcast", "row-2"]);
    expect(withheld.every((w) => w.engine === "cpi_nowcast")).toBe(true);
  });

  it("conserves every row: nothing is silently dropped", () => {
    // This is the whole reason the function returns two buckets instead of filtering in place. A
    // row that is read and then dropped is indistinguishable from there having been no rows, and
    // the reader would conclude the engine was retired rather than relabelled.
    const rows = [row("cpi_nowcast"), row("weather"), row("labor_nowcast"), row(null)];
    const { edges, withheld } = partitionDisplayOnly(rows);
    expect(edges.length + withheld.length).toBe(rows.length);
  });

  it("gives every withheld row a reason, so none can be dropped without a trace", () => {
    const { withheld } = partitionDisplayOnly([row("cpi_nowcast"), row("cpi_nowcast", { id: "b" })]);
    expect(withheld).toHaveLength(2);
    for (const w of withheld) {
      expect(w.reason).toBeTruthy();
      expect(w.reason).toMatch(/not an edge engine/i);
    }
  });

  it("hands back the row unmodified, so the recorded numbers stay auditable", () => {
    // Typed as the reader's edge shape, not a bag of extras, so the assertions below are checked
    // by tsc rather than by `any` slipping through.
    const original = {
      id: "cpi-1",
      engine: "cpi_nowcast",
      edge_type: "MACRO",
      our_prob: 0.55,
      market_prob: 0.52,
      edge_pct: 3.2,
    };
    const { withheld } = partitionDisplayOnly([original]);
    expect(withheld[0].edge).toBe(original);
    expect(withheld[0].edge.our_prob).toBe(0.55);
    expect(withheld[0].edge.market_prob).toBe(0.52);
  });

  it("handles an empty read", () => {
    expect(partitionDisplayOnly([])).toEqual({ edges: [], withheld: [] });
  });

  it("is additive: a newly ruled engine needs one line, not a new filter", () => {
    expect(DISPLAY_ONLY_ENGINES).toContain("cpi_nowcast");
  });
});

describe("enforceDisplayOnlyPartition", () => {
  it("pulls a display-only row back out of the opportunity bucket", () => {
    // The reader is the last line. `EdgeCard` prints `{edge_pct}% EDGE` for anything in `edges`, so
    // a cpi_nowcast row that arrived there -- from a stub, a new caller, a hook regression -- would
    // claim a 20% edge on an engine that has none.
    const cpi = row("cpi_nowcast", { id: "leaked", edge_pct: 20.0 });
    const result = enforceDisplayOnlyPartition([cpi, row("labor_nowcast")]);

    expect(result.edges.map((e) => e.engine)).toEqual(["labor_nowcast"]);
    expect(result.withheld.map((w) => w.edge.id)).toEqual(["leaked"]);
    expect(result.withheld[0].reason).toBe(DISPLAY_ONLY_REASON.cpi_nowcast);
  });

  it("keeps the rows the read already withheld, rather than replacing them", () => {
    const already = { edge: row("cpi_nowcast", { id: "held" }), engine: "cpi_nowcast" as const,
      reason: DISPLAY_ONLY_REASON.cpi_nowcast };
    const result = enforceDisplayOnlyPartition([row("weather")], [already]);

    expect(result.edges).toHaveLength(1);
    expect(result.withheld.map((w) => w.edge.id)).toEqual(["held"]);
  });

  it("conserves every row it is given, from either bucket", () => {
    const already = { edge: row("cpi_nowcast", { id: "held" }), engine: "cpi_nowcast" as const,
      reason: DISPLAY_ONLY_REASON.cpi_nowcast };
    const opportunities = [row("cpi_nowcast", { id: "leaked" }), row("weather"), row("labor_nowcast")];
    const result = enforceDisplayOnlyPartition(opportunities, [already]);

    expect(result.edges.length + result.withheld.length).toBe(opportunities.length + 1);
  });

  it("is a no-op on a clean bucket", () => {
    expect(enforceDisplayOnlyPartition([row("weather")])).toEqual({
      edges: [row("weather")],
      withheld: [],
    });
    expect(enforceDisplayOnlyPartition([])).toEqual({ edges: [], withheld: [] });
  });
});
