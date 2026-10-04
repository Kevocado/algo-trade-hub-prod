import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import Journal from "@/pages/Journal";

/**
 * Two headlines whose market skill DELIBERATELY DIFFER -- +0.25 against -0.08 -- because a test whose
 * two sides carry the same number cannot tell a rendered value from a hardcoded one. That trap has
 * produced six vacuous tests in this repo.
 */
const BASE = {
  forecasters: 2, calibrated: 2, frozen_calibrated: 400, settled_calibrated: 400, promoted: 0,
};

const SCORED = {
  forecaster: "sports_nfl", forecaster_version: "feed-v1", n_settled: 400, n_targets: 500,
  brier: 0.15, brier_baseline: 0.2, bss: 0.25, up_rate: 0.5, baseline: "market",
  gate_status: "SHADOW", calibration_ready: true, reliability: [], gate_reasons: [], murphy: {},
  cadence: "daily",
};

function stub(marketSkill: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ as_of: "x", forecasters: [SCORED], headline: { ...BASE, market_skill: marketSkill } }),
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Brier skill vs market headline", () => {
  it("leads with the pooled skill the server computed", async () => {
    // Spec §1: "Hero copy leads with settled-ledger stats (N settled, Brier skill vs market)".
    // §11: "(1) ledger hero -- N settled, Brier skill vs market, per-forecaster tiles".
    // The number existed nowhere in the codebase until now.
    stub({ n: 400, brier: 0.15, brier_baseline: 0.2, bss: 0.25 });
    render(<Journal />);
    const totals = await screen.findByLabelText("Totals");
    expect(within(totals).getByText("Brier skill vs market").previousSibling).toHaveTextContent("+0.25");
  });

  it("shows the sign the server sent, not one it recomputes", async () => {
    // The control: +0.25 and -0.08 must not both come out the same sign. If the page derived the
    // value from `bss` on the card, this would render +0.25 twice.
    stub({ n: 400, brier: 0.216, brier_baseline: 0.2, bss: -0.08 });
    render(<Journal />);
    const totals = await screen.findByLabelText("Totals");
    expect(within(totals).getByText("Brier skill vs market").previousSibling).toHaveTextContent("-0.08");
  });

  it("says it is not measured rather than showing 0.00", async () => {
    // No market-linked evidence means no number. A hero reading "0.00" for "never measured" is a
    // fabricated figure -- the same lie as the deleted equity curve in #102.
    stub(null);
    render(<Journal />);
    const totals = await screen.findByLabelText("Totals");
    const cell = within(totals).getByText("Brier skill vs market").previousSibling;
    expect(cell).toHaveTextContent("—");
    expect(cell).not.toHaveTextContent("0.00");
  });
});
