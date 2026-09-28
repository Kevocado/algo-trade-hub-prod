import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import PredictionLab from "@/pages/PredictionLab";
import { DISPLAY_ONLY_REASON } from "@/lib/displayOnlyEngines";

/**
 * THE REMAINING WORK, and this file is it. Read this before assuming Task 1 finished the job.
 *
 * Where Task 1 actually landed:
 *   - `scan_cpi` no longer writes CPI edges (tradehub/scripts/scan.py).
 *   - The historical rows are NOT deleted -- no migration, per the ruling. The prune is
 *     deliberately disabled for cpi_nowcast so an absent writer cannot delete them by omission.
 *   - `useMarketEdges` splits its read: CPI rows go to `withheld`, labelled with the reason, and
 *     `edges` never contains one. Proven in useMarketEdges.test.tsx.
 *
 * What is NOT done, and cannot be done from Task 1: NOTHING RENDERS `withheld`. Both consumers of
 * the hook are under src/pages/, which this task was scoped out of. So today a reader who clicks
 * the MACRO tab sees a quieter tab and no statement that CPI exists and is display-only. The
 * withholding is correct and the rows are conserved, but the relabelling is invisible -- which is
 * the silent half of Ruling 1 that Task 2 / Task 3 has to close.
 *
 * WHY `it.fails` RATHER THAN A RED TEST: a permanently failing test would take the suite with it
 * and hide every future regression behind a known-red. `it.fails` inverts the assertion instead --
 * the suite stays green, the intent is written down, and the moment someone implements the
 * relabelling this test FAILS, forcing the marker to be removed rather than silently rotting into
 * a test that asserts nothing.
 *
 * To implement: render `withheld` on the MACRO tab (PredictionLab.tsx) and on the War Room's
 * edge list, with DISPLAY_ONLY_REASON and the row's nowcast context, then delete this file and
 * drop the `it.fails` wrapper in useMarketEdges.test.tsx that guards the same contract at the
 * data layer.
 */

const cpiRow = {
  id: "cpi-1",
  market_id: "KXCPI-26SEP09-T0.3",
  market_title: "Will CPI be above 3.0%?",
  edge_type: "MACRO" as const,
  engine: "cpi_nowcast",
  engine_version: "cpi-v1",
  gate_status: "SHADOW" as const,
  market_prob: 0.32,
  our_prob: 0.52,
  edge_pct: 20.0,
  discovered_at: "2026-09-27T12:00:00Z",
  raw_payload: {},
};

function stubHook(withheld: unknown[], edges: unknown[] = []) {
  vi.mock("@/hooks/useMarketEdges", () => ({
    useMarketEdges: () => ({ edges, withheld, loading: false }),
  }));
}

describe("PredictionLab must say that cpi_nowcast exists and is not an edge engine", () => {
  it.fails(
    "shows the withheld CPI row with the 'not an edge engine' reason, rather than an empty tab",
    () => {
      stubHook([{ edge: cpiRow, engine: "cpi_nowcast", reason: DISPLAY_ONLY_REASON.cpi_nowcast }]);

      render(<PredictionLab />);

      // The row is read, so it must be accounted for on screen: either presented with the label, or
      // explicitly accounted for. Today it is neither -- it is simply absent.
      expect(screen.getByText(/not an edge engine/i)).toBeTruthy();
      expect(screen.getByText(/KXCPI-26SEP09-T0\.3/)).toBeTruthy();
    },
  );

  it.fails("never renders a cpi_nowcast row through the opportunity EdgeCard", () => {
    // The failure this guards: the EdgeCard prints `{edge_pct}% EDGE` for anything in `edges`, so
    // a CPI row reaching it claims a 20.0% edge on an engine that has none. The data-layer tests
    // prove the hook withholds it; this proves the page cannot reintroduce it.
    stubHook([], [cpiRow]);

    render(<PredictionLab />);

    expect(screen.queryByText(/20\.0% EDGE/)).toBeNull();
  });
});
