import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import Journal from "@/pages/Journal";

/**
 * A forecaster with a real reliability table. `predicted` and `observed` DELIBERATELY DIFFER on every
 * bucket, and one bucket straddles 50%: a marker test whose two sides carry the same numbers proves
 * nothing, which has bitten this repo six times.
 */
const SCORED = {
  forecaster: "spy_quant", forecaster_version: "spy-wf-v1", n_settled: 240, n_targets: 300,
  brier: 0.2, brier_baseline: 0.21, bss: 0.04, up_rate: 0.5, baseline: "market",
  gate_status: "SHADOW", calibration_ready: true, cadence: "daily",
  gate_reasons: [], murphy: {},
  reliability: [
    { bucket: 0.1, n: 12, predicted: 0.1, observed: 0.14 },
    { bucket: 0.4, n: 40, predicted: 0.4, observed: 0.33 },
    { bucket: 0.5, n: 88, predicted: 0.5, observed: 0.52 },
    { bucket: 0.7, n: 60, predicted: 0.7, observed: 0.61 },
    { bucket: 0.9, n: 40, predicted: 0.9, observed: 0.78 },
  ],
};

function stubJournal(forecasters: unknown[] = [SCORED]) {
  vi.stubGlobal(
    "fetch",
    vi.fn((arguments0: unknown) =>
      Promise.resolve({
        ok: true,
        status: 200,
        // The detail also fetches /api/journal/feed. Answering that with the journal body was making
        // it render nonsense, so route by URL the way the real client does.
        json: () =>
          Promise.resolve(
            String(arguments0).includes("/feed")
              ? { forecaster: "spy_quant", forecaster_version: "spy-wf-v1", generated_at: "x",
                  forecasts: [], calibration: [], gate_status: "SHADOW", provisional: false }
              : { as_of: "2026-10-04T00:00:00+00:00", forecasters,
                  headline: { forecasters: 1, calibrated: 1, frozen_calibrated: 300, settled_calibrated: 240, promoted: 0 } },
          ),
      }),
    ),
  );
}

async function openDetail() {
  stubJournal();
  render(<Journal />);
  fireEvent.click(await screen.findByRole("button", { name: /S&P 500 tomorrow: model/ }));
  await screen.findByLabelText(/^Calibration curve /);
  return document.querySelector('table[aria-label^="Calibration"]') as HTMLElement;
}

afterEach(() => vi.unstubAllGlobals());

describe("calibration shows its reference points", () => {
  it("draws the reliability curve with a 50% baseline marker", async () => {
    // Spec §11: "calibration curves — reliability diagrams per forecaster, 50%-baseline markers,
    // bias readouts". The bias readout shipped; the curve and the marker did not. Without a 50%
    // reference a visitor cannot tell whether a forecaster saying "60%" is right about its own
    // calibration or merely averaging out, so the table is not readable on its own.
    const table = await openDetail();
    const curve = document.querySelector('[aria-label^="Calibration curve"]');
    expect(curve).not.toBeNull();
    // The references, named in text. Asserting on recharts' own `ReferenceLine` label proved
    // unreliable: under jsdom `ResponsiveContainer` reports no size and the SVG never renders, so
    // the assertion passed or failed on the mock rather than on the code.
    const legend = within(curve as HTMLElement).getByText(/coin flip/i);
    expect(legend.textContent).toMatch(/50%/);
    expect(legend.textContent).toMatch(/over-confident/i);
    // The diagonal is a SECOND reference and needs its own pin: renaming "perfect calibration" to
    // "perfect" left every assertion above still passing, which is how a reference quietly dies.
    expect(legend.textContent).toMatch(/perfect calibration/i);
  });

  it("marks 50% in the table too, so the reference survives without the chart", async () => {
    // The table is the accessible fallback and the thing that works when the diagram does not. The
    // marker has to be here as well, or a screen-reader user loses the reference entirely.
    const table = await openDetail();
    expect(within(table).getByText("50%")).toBeInTheDocument();
  });

  it("still shows the numbers the marker sits among", async () => {
    // The guard on the guard: a marker that replaced the table would satisfy both tests above.
    const table = await openDetail();
    expect(within(table).getByText("Said")).toBeInTheDocument();
    expect(within(table).getByText("Happened")).toBeInTheDocument();
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBeGreaterThan(3));
  });

  it("says nothing scored yet rather than drawing an empty curve", async () => {
    stubJournal([{ ...SCORED, reliability: [] }]);
    render(<Journal />);
    fireEvent.click(await screen.findByRole("button", { name: /S&P 500 tomorrow: model/ }));
    expect(await screen.findByText("Nothing scored yet.")).toBeInTheDocument();
    expect(document.querySelector('[aria-label^="Calibration curve"]')).toBeNull();
  });
});

describe("the curve's x axis is numeric, not categorical", () => {
  it("declares a numeric x axis, so distance means probability", async () => {
    // CodeRabbit Major on #104: `XAxis` defaults to a CATEGORY axis, so buckets were spaced equally
    // regardless of their numeric values and `domain={[0, 1]}` was ignored -- the curve and the
    // perfect-calibration diagonal were not on a shared probability scale, which is the diagram's only
    // job.
    //
    // Asserted on the source, not the rendered SVG. I tried the rendered axis first: under jsdom the
    // container has no usable width, so recharts emits one tick whether the axis is numeric or
    // categorical, and the assertion tested the mock rather than the code. A prop check is weaker but
    // honest about what it proves; this is the same trade I made in #102 and I would rather name it
    // than dress a flaky DOM assertion up as coverage.
    stubJournal();
    render(<Journal />);
    fireEvent.click(await screen.findByRole("button", { name: /S&P 500 tomorrow: model/ }));
    await screen.findByLabelText(/^Calibration curve /);

    const source = readFileSync(resolve(process.cwd(), "src/components/JournalDetail.tsx"), "utf8");
    expect(source).toMatch(/<XAxis type="number" dataKey="predicted"/);
  });
});
