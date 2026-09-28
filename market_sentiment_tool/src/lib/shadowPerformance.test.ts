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
  SHADOW_ERROR_CODE_HEADER,
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
 * 424: the table is fine and a credential is not set.
 *
 * The sentence below is the real one, quoted out of `tradehub/api/main.py:_missing_credential_message`
 * with the real arguments (`sp.MissingCredentialError("Alpaca API", ("ALPACA_API_KEY",
 * "ALPACA_SECRET_KEY"))`), not reconstructed. That matters twice over: the page is not allowed a
 * second copy of an instruction, and a test that retyped the instruction would keep passing after
 * the server stopped sending it -- which is the state where the reader is told to set a variable the
 * server no longer names.
 *
 * `vps-stack/compose.yml` passes no `ALPACA_*` to the tradehub service, so this is the live state
 * and not a hypothetical: once the migration is applied, this is the read every reader gets.
 */
const CREDENTIAL_SENTENCE =
  "This service has no Alpaca API credentials, so the shadow timeline cannot be read. " +
  "The database is fine -- this is not a migration. " +
  "Set ALPACA_API_KEY and ALPACA_SECRET_KEY in the stack's .env file, beside " +
  "vps-stack/compose.yml. Then add 'ALPACA_API_KEY: ${ALPACA_API_KEY:-}' and " +
  "'ALPACA_SECRET_KEY: ${ALPACA_SECRET_KEY:-}' to the tradehub service's environment: block, " +
  "and redeploy.";

/** What a real bug in the builder produces, and the one thing no operator step closes. */
const BUG_SENTENCE = "unsupported operand type(s) for +: 'int' and 'NoneType'";

describe("the three failed reads, told apart by status", () => {
  it("presents a 424 as an operator step, not as a fault", () => {
    const notice = shadowUnavailable(424, CREDENTIAL_SENTENCE, "missing_credentials");

    // Not a red alarm. "set these two variables" and "something is broken" are different claims.
    expect(notice.tone).toBe("operator_step");
    expect(notice.waiting_on_operator).toBe(true);
    expect(notice.failure).toBe("missing_credentials");
    expect(notice.title).toBe("Waiting on environment variables");
    expect(notice.title.toLowerCase()).not.toContain("unavailable");
    expect(notice.title).not.toMatch(/could not be read/i);
    // The same four beats as the migration notice: not broken, why there is nothing to read, only
    // an operator can finish it, and here is the step. The panel reads as a to-do, not an apology.
    expect(notice.lead).toMatch(/not broken/i);
    expect(notice.lead).toMatch(/nothing is wrong with the charts or with the database/i);
    expect(notice.lead).toMatch(/only an operator can finish this/i);
  });

  it("quotes the 424 sentence verbatim, because it is the whole instruction", () => {
    const notice = shadowUnavailable(424, CREDENTIAL_SENTENCE, "missing_credentials");

    expect(notice.body).toBe(CREDENTIAL_SENTENCE);
    // What, where, and the second place it has to be named. The page must not have to guess.
    for (const needed of ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "vps-stack/compose.yml", "environment:"]) {
      expect(notice.body).toContain(needed);
    }
  });

  it("does not put a digit on the credential panel, so nothing on it can be read as a figure", () => {
    // The server's instruction happens to contain no digits, so this is exact rather than "none of
    // the summary cards": it fails on a `0.00h` freshness line or a `424` printed as a figure too.
    const notice = shadowUnavailable(424, CREDENTIAL_SENTENCE, "missing_credentials");

    for (const field of [notice.title, notice.lead, notice.body ?? ""]) {
      expect(field).not.toMatch(/[0-9]/);
    }
  });

  it("still presents a 503 as a migration, and the 424 does not change that", () => {
    const notice = shadowUnavailable(503, MIGRATION_SENTENCE, "missing_table");

    expect(notice.tone).toBe("waiting");
    expect(notice.title).toBe("Waiting on a database migration");
    expect(notice.body).toBe(MIGRATION_SENTENCE);
  });

  it("still presents a 500 as a fault, and a fault stays a fault whatever it says", () => {
    const notice = shadowUnavailable(500, BUG_SENTENCE, "internal_error");

    expect(notice.tone).toBe("fault");
    expect(notice.waiting_on_operator).toBe(false);
    expect(notice.failure).toBe("internal_error");
    expect(notice.title).toBe("The shadow timeline could not be read");
  });

  it("classifies on the status when the response carried no X-Error-Code", () => {
    // A proxy that does not forward custom headers is an ordinary thing, and it must not turn an
    // operator step back into a red fault. The status alone is enough, so the fallback is the status.
    expect(shadowUnavailable(424, CREDENTIAL_SENTENCE).tone).toBe("operator_step");
    expect(shadowUnavailable(503, MIGRATION_SENTENCE).tone).toBe("waiting");
    expect(shadowUnavailable(500, BUG_SENTENCE).tone).toBe("fault");
    expect(shadowUnavailable(424, CREDENTIAL_SENTENCE).error_code).toBeNull();
  });

  it("prefers X-Error-Code over the status, because it is the narrower claim", () => {
    // The header and the status are the same answer twice from the server, so a disagreement means
    // one of them is stale. The name is what a reader and a log read, and it is more specific than
    // the number, so it wins. This is also what stops a future credential class -- a third
    // credentialed service behind its own status -- from needing a second branch here.
    expect(shadowUnavailable(503, CREDENTIAL_SENTENCE, "missing_credentials").tone).toBe("operator_step");
    expect(shadowUnavailable(424, MIGRATION_SENTENCE, "missing_table").tone).toBe("waiting");
  });

  it("treats a code it has never met as a fault rather than as an operator step", () => {
    // The safe direction to be wrong in. A new code is a new fact this client has not been taught
    // to word, and promising an operator a step that may not exist is the mistake being fixed.
    const notice = shadowUnavailable(418, "I am a teapot", "i_am_a_teapot");

    expect(notice.tone).toBe("fault");
    expect(notice.waiting_on_operator).toBe(false);
  });

  it("says something on a 424 that arrived with no body at all", () => {
    // A gateway that drops the payload is a real 424. The class came from the status, so the panel
    // still says what the reader has to do; only the quoted sentence is missing.
    const notice = shadowUnavailable(424, "   ", "missing_credentials");

    expect(notice.tone).toBe("operator_step");
    expect(notice.body).toBeTruthy();
    expect(notice.body).not.toContain("undefined");
  });
});

/**
 * The obligation this whole change is: `detail` is OUTPUT.
 *
 * PR #43 gave the endpoint a machine-readable code precisely so a client would not have to read the
 * English. Every test below pairs a status with prose that argues for the OTHER classification, so
 * a `shadowUnavailable` that regressed to matching on `detail` fails rather than passing quietly.
 * The pairing is what makes these tests worth anything -- a test with a neutral detail would pass
 * under both implementations.
 */
describe("classification does not read the detail", () => {
  it("calls a 424 an operator step even when its detail says nothing about credentials", () => {
    // Under a prose matcher this is a fault, because none of these words name a variable. The
    // status is the evidence, and 424 on this endpoint means exactly one thing.
    const notice = shadowUnavailable(424, "upstream dependency did not answer", "missing_credentials");

    expect(notice.tone).toBe("operator_step");
  });

  it("keeps a 500 a fault even when its detail is the credential sentence word for word", () => {
    // The sharp form. Under a prose matcher this reads as an operator step, because the sentence
    // names two variables and a file -- and that is precisely how a 500 from this endpoint used to
    // send an operator to set environment variables when the code was the thing that was broken.
    // Same text as the passing 424 case above, opposite status, opposite presentation.
    const notice = shadowUnavailable(500, CREDENTIAL_SENTENCE, "internal_error");

    expect(notice.tone).toBe("fault");
    expect(notice.waiting_on_operator).toBe(false);
    expect(notice.title).toBe("The shadow timeline could not be read");
  });

  it("keeps a 500 a fault even when its detail is the migration sentence word for word", () => {
    const notice = shadowUnavailable(500, MIGRATION_SENTENCE);

    expect(notice.tone).toBe("fault");
    expect(notice.title).not.toBe("Waiting on a database migration");
  });

  it("calls a 424 an operator step even when its detail names a migration", () => {
    // The status beats the prose in the other direction too. A 424 whose body happens to contain a
    // migration path is still a credential problem, and "apply this file" would be a step that does
    // not fix it.
    const notice = shadowUnavailable(424, MIGRATION_SENTENCE, "missing_credentials");

    expect(notice.tone).toBe("operator_step");
    expect(notice.title).not.toMatch(/migration/i);
  });

  it("keeps a 503 without a migration path a fault, because the panel would claim something untrue", () => {
    // The one place `detail` is still read, and the asymmetry is deliberate: `_missing_table_message`
    // forwards any non-PGRST runtime error through the same 503, so 503 alone cannot promise a
    // migration. Unchanged by this PR -- it is the behaviour that was already right.
    const notice = shadowUnavailable(503, "cannot read the timeline: 42", "missing_table");

    expect(notice.tone).toBe("fault");
    expect(notice.waiting_on_operator).toBe(false);
  });

  it("keeps the migration path as a last resort, and does not widen it to credentials", () => {
    // With no status and no code -- a transport failure -- the path is the only non-English thing
    // in the body, so it can still name a step. A sentence naming a variable cannot, because that
    // IS English, and a 424 that arrived here with no status is a shape this client cannot claim
    // anything about. Pinning the narrowness matters: widening step 3 to a credential regex is
    // exactly the regression the rest of this block exists to catch, done quietly.
    expect(shadowUnavailable(null, MIGRATION_SENTENCE).tone).toBe("waiting");
    expect(shadowUnavailable(null, CREDENTIAL_SENTENCE).tone).toBe("fault");
  });

  it("exposes the header name it classifies on, so the hook cannot drift from it", () => {    // The hook and the classifier have to agree on the spelling of the header, and the only way to
    // notice when they do not is to write the header out in both places and have a test hold them
    // to it. This is the server's spelling: `tradehub/api/main.py:_table_fault`.
    expect(SHADOW_ERROR_CODE_HEADER).toBe("X-Error-Code");
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
