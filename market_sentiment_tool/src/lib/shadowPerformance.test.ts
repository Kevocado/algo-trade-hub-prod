import { describe, expect, it } from "vitest";

import {
  NOT_THE_SCOREBOARD,
  NO_FIGURE,
  filterShadowSeriesByAsset,
  formatBrier4,
  formatHitRate,
  formatHours,
  formatSignedPct,
  getShadowAssets,
  getShadowMarkerColor,
  getShadowMarkerRadius,
  getShadowThresholdValue,
  shadowUnavailable,
  type ShadowPerformancePoint,
} from "@/lib/shadowPerformance";

const SERIES: ShadowPerformancePoint[] = [
  {
    timestamp: "2026-04-15T10:00:00Z",
    asset: "BTC",
    market_ticker: "BTC-1",
    probability_yes: 0.61,
    threshold_side: "YES",
    threshold_triggered: true,
    current_price: 63100,
    next_hour_price: 63220,
    realized_yes: 1,
    shadow_outcome: "win",
    correct: true,
    virtual_return_pct: 0.19,
  },
  {
    timestamp: "2026-04-15T11:00:00Z",
    asset: "ETH",
    market_ticker: "ETH-1",
    probability_yes: 0.43,
    threshold_side: "NO",
    threshold_triggered: true,
    current_price: 3180,
    next_hour_price: 3205,
    realized_yes: 1,
    shadow_outcome: "loss",
    correct: false,
    virtual_return_pct: -0.79,
  },
  {
    timestamp: "2026-04-15T12:00:00Z",
    asset: "BTC",
    market_ticker: "BTC-2",
    probability_yes: 0.52,
    threshold_side: null,
    threshold_triggered: false,
    current_price: 63220,
    next_hour_price: 63240,
    realized_yes: 1,
    shadow_outcome: "loss",
    correct: false,
    virtual_return_pct: 0,
  },
];

describe("shadowPerformance helpers", () => {
  it("extracts sorted asset symbols from series", () => {
    expect(getShadowAssets(SERIES)).toEqual(["BTC", "ETH"]);
  });

  it("filters series by asset", () => {
    expect(filterShadowSeriesByAsset(SERIES, "BTC")).toHaveLength(2);
    expect(filterShadowSeriesByAsset(SERIES, "ETH")).toHaveLength(1);
  });

  it("returns marker styling for win, loss, and hidden points", () => {
    expect(getShadowMarkerColor(SERIES[0])).toBe("#10b981");
    expect(getShadowMarkerColor(SERIES[1])).toBe("#f43f5e");
    expect(getShadowMarkerColor(SERIES[2])).toBe("transparent");
    expect(getShadowMarkerRadius(SERIES[0])).toBe(5);
    expect(getShadowMarkerRadius(SERIES[2])).toBe(0);
  });

  it("returns the yes threshold for the requested asset", () => {
    expect(getShadowThresholdValue({ BTC: { yes: 0.5751, no: 0.4249 } }, "BTC")).toBe(0.5751);
    expect(getShadowThresholdValue({ BTC: { yes: 0.5751, no: 0.4249 } }, "ETH")).toBeNull();
  });
});

/**
 * The failed read, worded.
 *
 * The real sentence is the one `tradehub/api/main.py:246` builds via
 * `_missing_table_message`, pasted in verbatim below. It is quoted rather than
 * reconstructed so that a change to the server's wording is visible here as a
 * change to a test, and so that this file is not a second copy of the table ->
 * migration mapping. If the server stops naming the file, the classification
 * below has to change with it, deliberately.
 */
const MIGRATION_SENTENCE =
  "table 'signal_events' is not in the database. Apply " +
  "market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql " +
  "and redeploy. The database still has crypto_signal_events under its old name.";

describe("shadowUnavailable", () => {
  it("calls a read that names a migration a wait on an operator, not a fault", () => {
    const notice = shadowUnavailable(503, MIGRATION_SENTENCE);

    expect(notice.waiting_on_operator).toBe(true);
    expect(notice.tone).toBe("waiting");
    // Not a red alarm. "apply this file" and "something is broken" are different claims and a
    // page that makes the second one when the first is true sends an operator looking in the
    // wrong place.
    expect(notice.title).toBe("Waiting on a database migration");
    expect(notice.title.toLowerCase()).not.toContain("unavailable");
    expect(notice.lead).toMatch(/operator/i);
  });

  it("quotes the server's sentence verbatim, because it names the file to apply", () => {
    const notice = shadowUnavailable(503, MIGRATION_SENTENCE);

    expect(notice.body).toBe(MIGRATION_SENTENCE);
    // The one thing a reader needs in order to act. If the server stops saying it, this fails.
    expect(notice.body).toContain("20260415090000_signal_events_unification.sql");
  });

  it("treats a failure that names no migration as a fault, not as an operator step", () => {
    const notice = shadowUnavailable(500, "Upstream connect error or disconnect/quit before query completion");

    expect(notice.waiting_on_operator).toBe(false);
    expect(notice.tone).toBe("fault");
    expect(notice.body).toBe("Upstream connect error or disconnect/quit before query completion");
  });

  it("does not promise an operator step on the strength of a status code alone", () => {
    // `_missing_table_message` forwards any non-PGRST runtime error through the same 503, so the
    // code is not evidence of a migration. This is the case that makes that a real constraint
    // rather than a comment.
    const notice = shadowUnavailable(503, "cannot read the timeline: 42");

    expect(notice.waiting_on_operator).toBe(false);
    expect(notice.tone).toBe("fault");
  });

  it("says something when the server sent no explanation at all", () => {
    for (const [status, detail] of [
      [502, null],
      [502, "   "],
      [null, null],
    ] as const) {
      const notice = shadowUnavailable(status, detail);
      expect(notice.body).toBeTruthy();
      expect(notice.body).not.toContain("undefined");
      expect(notice.body).not.toContain("null");
    }
  });

  it("names the operator step even when there is no status to classify on", () => {
    // A transport failure carries `status: null` and still, here, a sentence from the server.
    const notice = shadowUnavailable(null, MIGRATION_SENTENCE);
    expect(notice.waiting_on_operator).toBe(true);
  });
});

/**
 * A missing figure has no number in it. Not zero, and not a dash -- a dash in a
 * figure column is a figure, and it reads as zero the moment anyone screenshots
 * the board. So every one of these strings is checked for digits that would put
 * a quantity back into a slot that has none.
 */
describe("the words a missing figure is given", () => {
  it("gives NO_FIGURE no digits, so it cannot be miscounted as a quantity", () => {
    expect(NO_FIGURE).toMatch(/no completed signal/i);
    expect(NO_FIGURE).not.toMatch(/[0-9]/);
  });

  it("points the crypto page at the scoreboard by name, not by resemblance", () => {
    expect(NOT_THE_SCOREBOARD).toMatch(/crypto shadow timeline/i);
    expect(NOT_THE_SCOREBOARD).toMatch(/not the engine scoreboard/i);
    // "Engine Scoreboard", and NOT "Shadow Scoreboard". The sentence sends a reader to the
    // page, so its name has to be that page's actual name -- and it must not reintroduce the word
    // that caused the collision in the one place a reader is most likely to copy it from.
    expect(NOT_THE_SCOREBOARD).toMatch(/Engine Scoreboard/);
    expect(NOT_THE_SCOREBOARD).not.toMatch(/Shadow Scoreboard/);
  });
});

describe("figure formatting", () => {
  it("formats a hit rate as a percentage and a brier at the server's four places", () => {
    expect(formatHitRate(0.6153)).toBe("61.5%");
    expect(formatBrier4(0.1148)).toBe("0.1148");
  });

  it("keeps a zero a real figure, and gives a pnl its sign", () => {
    // The server computes a real 0.0 for an empty window -- a sum over no signals IS zero -- so
    // this is a measurement and stays. What may not happen is a MISSING figure arriving here.
    expect(formatHitRate(0)).toBe("0.0%");
    expect(formatSignedPct(0)).toBe("+0.00%");
    expect(formatSignedPct(1.5)).toBe("+1.50%");
    expect(formatSignedPct(-0.79)).toBe("-0.79%");
  });

  it("formats an age in hours", () => {
    expect(formatHours(0.25)).toBe("0.25h");
  });
});
