import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";

import { JournalDetail } from "@/components/JournalDetail";
import type { ViewRow } from "@/lib/journalView";
import type { JournalFeed } from "@/lib/journal";

function row(over: Partial<ViewRow> = {}): ViewRow {
  return {
    key: "spy_quant@spy-wf-v1",
    label: "S&P 500 tomorrow: model",
    forecaster: "spy_quant",
    experimental: false,
    frozen: 300, scored: 240, needed: 200, skill: 0.04, against: "the Kalshi price",
    baseline: "market", status: "behind", score: {
      forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily", baseline: "market",
      n_targets: 300, n_settled: 240, brier: 0.2, brier_baseline: 0.21, bss: 0.04,
      reliability: [], murphy: {}, calibration_ready: true, gate_status: "SHADOW",
      gate_reasons: [], computed_at: "x",
    },
    market: null, ...over,
  } as ViewRow;
}

/** Two rows differing ONLY in `rebuilt`, so the marker cannot pass as a blanket badge. */
function feed(rebuilt: boolean): JournalFeed {
  return {
    forecaster: "spy_quant", forecaster_version: "spy-wf-v1", generated_at: "x",
    forecasts: [
      { target: "spy:2026-10-05", probability: 0.61, market_prob: 0.55, frozen_at: "2026-10-04T13:00:00Z", rebuilt },
    ],
    calibration: [], gate_status: "SHADOW", provisional: false,
  } as JournalFeed;
}

function serve(f: JournalFeed) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(f) })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("rebuilt rows are marked as rebuilt", () => {
  it("says a rebuilt row was found invalid, under a heading that admits it", async () => {
    // CodeRabbit, on #66: `/api/journal/feed` returned `rebuilt` rows as ordinary locked-in
    // forecasts. `rebuilt` was in the TypeScript type and read nowhere.
    //
    // What it actually means, from migration 20260428000014: "`rebuilt` may flip false -> true (a
    // row found invalid is kept and shown, never counted)". So the row is one that was RETRACTED as
    // wrong. Rendering it in a table headed "Latest locked-in forecasts", styled identically to a real
    // one, presents a retracted number as a forecast that was locked in before the event.
    //
    // Kept and shown -- the migration requires that -- but never as ordinary.
    serve(feed(true));
    render(<JournalDetail row={row()} />);
    const table = await screen.findByLabelText(/Frozen forecasts/);
    await waitFor(() => expect(within(table).getByText("spy:2026-10-05")).toBeInTheDocument());
    expect(within(table).getByText(/rebuilt/i)).toBeInTheDocument();

    // The heading must not claim that every row beneath it was locked in. My first version of this
    // test was NAMED "under a heading that admits it" and never asserted the heading at all -- so
    // reverting it to "Latest locked-in forecasts" passed. A test whose name promises a claim must
    // check it, or the name is decoration.
    expect(screen.queryByText("Latest locked-in forecasts")).toBeNull();
    expect(screen.getByText("Latest forecasts")).toBeInTheDocument();
  });

  it("does not mark a row that was genuinely frozen", async () => {
    // The control. Identical data except `rebuilt`, so a blanket badge cannot pass this.
    serve(feed(false));
    render(<JournalDetail row={row()} />);
    const table = await screen.findByLabelText(/Frozen forecasts/);
    await waitFor(() => expect(within(table).getByText("spy:2026-10-05")).toBeInTheDocument());
    expect(within(table).queryByText(/rebuilt/i)).toBeNull();
  });

  it("still shows the probability, because the migration says kept and shown", async () => {
    // A rebuilt row must not simply vanish: it is the record that a forecast existed and was found
    // invalid, which is exactly what an auditor wants. Dropping it would lose the trail.
    serve(feed(true));
    render(<JournalDetail row={row()} />);
    const table = await screen.findByLabelText(/Frozen forecasts/);
    await waitFor(() => expect(within(table).getByText("61.0%")).toBeInTheDocument());
  });
});
