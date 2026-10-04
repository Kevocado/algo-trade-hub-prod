import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import Journal from "@/pages/Journal";

/**
 * One calibrated card and one provisional card, with DELIBERATELY DIFFERENT numbers on each side of
 * the comparison. That difference is the whole point: a test whose two sides carry the same values
 * passes whether or not the gate is honoured. Six of those have bitten this repo already.
 */
const CALIBRATED = {
  forecaster: "spy_quant", forecaster_version: "spy-wf-v1", n_settled: 120, n_targets: 200,
  brier: 0.2, brier_baseline: 0.21, bss: 0.04, up_rate: 0.5, baseline: "market",
  gate_status: "SHADOW", calibration_ready: true, reliability: [], cadence: "daily",
};

/** Big numbers, deliberately: if the page sums these, the hero is visibly wrong. */
const PROVISIONAL = {
  ...CALIBRATED,
  forecaster: "vix_direction", forecaster_version: "vix-wf-v1", n_settled: 999, n_targets: 888,
  calibration_ready: false, baseline: "climatology",
};

function stubJournal(headline: Record<string, number>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            as_of: "2026-10-04T00:00:00+00:00",
            forecasters: [CALIBRATED, PROVISIONAL],
            headline,
          }),
      }),
    ),
  );
}

const hero = (label: string) =>
  within(screen.getByLabelText("Totals")).getByText(label).previousSibling;

afterEach(() => vi.unstubAllGlobals());

describe("journal hero honours the calibration gate", () => {
  it("shows the server's calibrated numbers, not a sum over every card", async () => {
    // Spec §3 step 4: "The frontend reads precomputed scores through the REST contract. It never
    // recomputes a number." Spec §10: "headline stats aggregate ONLY post-calibration forecasters."
    //
    // The page called `totals(rows)`, which summed `n_settled` over EVERY card. A provisional card
    // with 999 settled rows inflated the hero to 1119. The server has gated this number the whole
    // time at `scoring.py:headline()`; `data.headline` was destructured nowhere.
    stubJournal({ forecasters: 2, calibrated: 1, frozen_calibrated: 200, settled_calibrated: 120, promoted: 0 });

    render(<Journal />);
    await screen.findByLabelText("Totals");

    expect(hero("scored so far")).toHaveTextContent("120");
    expect(hero("forecasts locked in")).toHaveTextContent("200");
  });

  it("does not recompute: a hero number the server sent is shown verbatim", async () => {
    // The stronger form of the guard. If the page summed the cards, the fixture's own 120/200 would
    // be reproduced and this would pass -- so the server is given a number no client sum could
    // produce (777), and the page must show 777.
    stubJournal({ forecasters: 2, calibrated: 1, frozen_calibrated: 777, settled_calibrated: 777, promoted: 0 });

    render(<Journal />);
    await screen.findByLabelText("Totals");

    expect(hero("scored so far")).toHaveTextContent("777");
    expect(hero("forecasts locked in")).toHaveTextContent("777");
  });

  it("still shows the provisional card in the list -- only the aggregate is gated", async () => {
    // Spec §10: "any forecaster appears from its first frozen row". Gating the hero must not hide a
    // forecaster, or the page would be hiding the very thing it is being honest about.
    stubJournal({ forecasters: 2, calibrated: 1, frozen_calibrated: 200, settled_calibrated: 120, promoted: 0 });

    render(<Journal />);
    // It carries 999 settled rows, so `split` files it under Results. Either table proves the point:
    // the gate hides it from the AGGREGATE, never from the page.
    const results = await screen.findByLabelText("Results");
    expect(within(results).getByRole("button", { name: /Volatility \(VIX\) tomorrow/ })).toBeInTheDocument();
  });
});
