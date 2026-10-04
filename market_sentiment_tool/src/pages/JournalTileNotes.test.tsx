import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import Journal from "@/pages/Journal";

/** A scored row so it lands in the results table, where the tile note is rendered. */
function scored(forecaster: string, version: string) {
  return {
    forecaster, forecaster_version: version, n_settled: 250, brier: 0.2, brier_baseline: 0.21,
    bss: 0.04, up_rate: 0.5, baseline: "climatology", gate_status: "SHADOW",
    calibration_ready: true, reliability: [],
  };
}

const ROWS = [
  scored("gold_direction", "gold-wf-v1"),
  scored("housing_direction", "housing-wf-v1"),
  scored("vix_direction", "vix-wf-v1"),
];

afterEach(() => vi.unstubAllGlobals());

function stubJournal() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ as_of: "2026-10-04T00:00:00+00:00", forecasters: ROWS, headline: {} }),
      }),
    ),
  );
}

describe("journal tile notes", () => {
  it("names the gold ETF, because gold settles on GLD and not on COMEX futures", async () => {
    // 2026-09-30-wave2-daily-directions.md, Global Constraint 2: "Gold settles on the GLD ETF (raw
    // close), not COMEX GC=F: a continuous futures series jumps at every contract roll and would grade
    // roll artefacts as 'direction'. The tile must say `GLD (gold ETF)`."
    //
    // It never said it. `source` is "yahoo:GLD" on the payload and the API serves `source_hash`, not
    // `source`, so nothing anywhere rendered the instrument. A visitor comparing gold against a
    // futures-based expectation has no way to see which series was graded.
    stubJournal();
    render(<Journal />);
    expect(await screen.findByText(/GLD \(gold ETF\)/)).toBeTruthy();
  });

  it("states the housing data lag, so a two-month-old print is not read as stale news", async () => {
    // 2026-09-30-wave3-housing.md: "Data lag stated on the tile: the index for month m is published
    // about two months later." The phrase existed only in a docstring.
    stubJournal();
    render(<Journal />);
    expect(await screen.findByText(/two months behind/)).toBeTruthy();
  });

  it("renders a note only where one exists, and invents none", async () => {
    // The guard on the guard. My first version of this matched /GLD|months behind/, which a blanket
    // fallback string never contains -- so mutating `tileNote` to return "Sourced from market data"
    // for every unknown forecaster PASSED. Same vacuous shape as five earlier tests this session.
    // Counting the rendered notes is what actually bites: 3 forecasters, only 2 with a note.
    stubJournal();
    const { container } = render(<Journal />);
    await screen.findByText(/GLD \(gold ETF\)/);
    const notes = [...container.querySelectorAll("[data-tile-note]")].map((n) => n.textContent);
    expect(notes.sort()).toEqual(["GLD (gold ETF)", "two months behind"]);
  });
});
