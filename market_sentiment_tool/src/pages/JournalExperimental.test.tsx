import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import Journal from "@/pages/Journal";

/**
 * Two cards whose labels differ in exactly one way: one is in the EXPERIMENTAL set, one is not.
 * Identical data on both sides is the shape that lets a test pass against the bug it was written
 * for -- six of those have bitten this repo. So the two cards must NOT be interchangeable.
 */
const FOMC = {
  forecaster: "fomc_mapped", forecaster_version: "fomc-v1", n_settled: 40, n_targets: 60,
  brier: 0.2, brier_baseline: 0.21, bss: 0.02, up_rate: 0.5, baseline: "market",
  gate_status: "SHADOW", calibration_ready: true, reliability: [], cadence: "meeting",
};

const CPI = {
  ...FOMC,
  forecaster: "cpi_nowcast", forecaster_version: "cpi-core-v1", baseline: "market",
};

function stubJournal(forecasters: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            as_of: "2026-10-04T00:00:00+00:00",
            forecasters,
            headline: { forecasters: 2, calibrated: 2, frozen_calibrated: 120, settled_calibrated: 80, promoted: 0 },
          }),
      }),
    ),
  );
}

const rowFor = (name: RegExp) =>
  screen.getByRole("button", { name }).closest("tr") as HTMLElement;

afterEach(() => vi.unstubAllGlobals());

describe("experimental forecasters are labelled", () => {
  it("marks the FOMC forecaster experimental and leaves other forecasters unlabelled", async () => {
    // Spec §5: fomc_mapped "ships alongside the Kalshi pseudo-forecaster (§8) from its first row,
    // labelled experimental". Ruling Q5 repeats it. `EXPERIMENTAL = new Set(["fomc_mapped"])`
    // existed in `lib/journal.ts` and was imported by NOTHING -- the set was written, the label was
    // never rendered, and nothing failed.
    stubJournal([FOMC, CPI]);
    render(<Journal />);
    await screen.findByLabelText("Results");

    expect(within(rowFor(/Fed rate decision/)).getByText("Experimental")).toBeInTheDocument();
    // The control: the label must be per-forecaster, not a blanket badge on every row.
    expect(within(rowFor(/Core inflation/)).queryByText("Experimental")).toBeNull();
  });

  it("labels a provisional experimental forecaster too, not only a scored one", async () => {
    // "from its FIRST row" -- so the label cannot depend on having any settled evidence. With
    // n_settled 0 the card lands in Waiting, which is a different code path with its own markup.
    stubJournal([{ ...FOMC, n_settled: 0, n_targets: 3 }]);
    render(<Journal />);
    const waiting = await screen.findByLabelText("Waiting");
    expect(within(waiting).getByText(/Fed rate decision/)).toBeInTheDocument();
    expect(within(waiting).getByText("Experimental")).toBeInTheDocument();
  });
});
