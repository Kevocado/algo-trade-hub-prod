import { describe, expect, it } from "vitest";

import {
  FOUND_NOTHING_PHRASE,
  HEALTH_UNREAD_REASON,
  QUIET_REASON,
  STOPPED_WORD,
  edgeTypeStateOf,
  edgeTypesText,
  emptyBoard,
  opportunitiesFoundReason,
  opportunitiesFoundText,
  stoppedEngineOf,
  type EdgeTypeState,
  type EngineHealthResponse,
} from "@/lib/engineHealth";
import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The wording half of the stopped-engine ruling, and the two tests that were waiting for it.
 *
 * `emptyBoard` is the only place in the product allowed to say "nothing here" about an empty board,
 * and it may only say it when the server has said the engine ran. Everything else is either a
 * broken engine or an unknown one, and the three branches have to stay apart:
 *
 *   quiet      the engine ran and found nothing. A MEASUREMENT. The finding.
 *   stopped    an engine that feeds this board could not run. Nothing was measured.
 *   unchecked  the ruling itself could not be read, so the emptiness is not established either way.
 *
 * The last branch is the one that is easiest to leave out and the one that makes the other two
 * worth having: without it, a 500 on /api/engine-health is a quiet market, and a label that a
 * server outage can switch off is not a label.
 */

const WEATHER_REASON =
  "Not running. This is the Tier-1 real-edge weather engine, and it prices every market against " +
  "`yes_ask`, which Kalshi's API no longer sends. It skips every market and publishes nothing.";

function stoppedWeather(): EdgeTypeState {
  return {
    edge_type: "WEATHER",
    label: "Weather",
    state: "could_not_run",
    reason: WEATHER_REASON,
    stopped_sites: [
      {
        name: "WeatherEngine",
        module: "tradehub/engines/weather_engine.py",
        site: "tradehub/engines/weather_engine.py:214",
        edge_type: "WEATHER",
        wired_to_a_scanner: true,
        reason: WEATHER_REASON,
      },
      {
        name: "WeatherMaker",
        module: "tradehub/engines/weather_maker.py",
        site: "tradehub/engines/weather_maker.py:258",
        edge_type: "WEATHER",
        wired_to_a_scanner: false,
        reason: "Not running, and not wired to any scanner.",
      },
    ],
    opportunities_found: null,
    opportunities_found_reason:
      "No count, because nothing ran. The engine did not execute, so there is no opportunity count to report -- not a count of zero.",
  };
}

function quietSports(): EdgeTypeState {
  return {
    edge_type: "SPORTS",
    label: "Sports",
    state: "ran",
    reason: null,
    stopped_sites: [],
    opportunities_found: null,
    opportunities_found_reason: "Not counted here. This endpoint reports which engines are stopped.",
  };
}

function health(over: Partial<EngineHealthResponse> = {}): EngineHealthResponse {
  const stopped = stoppedWeather();
  const quiet = quietSports();
  return {
    as_of: "2026-09-28T00:00:00Z",
    edge_types: [stopped, quiet],
    edge_types_total: 2,
    edge_types_could_not_run: 1,
    edge_types_ran: 1,
    board_state: "could_not_run",
    board_reason: WEATHER_REASON,
    sites: stopped.stopped_sites,
    sites_total: 2,
    sites_wired: 1,
    sites_unwired: 1,
    note: "An engine on this list did not run.",
    ...over,
  };
}

describe("a broken engine reads as broken, with a reason", () => {
  it("says the engine is not running rather than that nothing was found", () => {
    const board = emptyBoard(health(), "WEATHER", "weather");
    expect(board.kind).toBe("stopped");
    expect(board.headline).toContain(STOPPED_WORD);
    expect(board.headline).not.toMatch(/no high-confidence edges/i);
  });

  it("carries the server's reason, not a paraphrase of the state", () => {
    const board = emptyBoard(health(), "WEATHER", "weather");
    expect(board.body).toBe(WEATHER_REASON);
  });

  it("never uses the sentence that would collapse the two states", () => {
    // This is the load-bearing assertion. "Found no qualifying opportunity" is the natural thing to
    // write for an empty tab, which is exactly why it must be forbidden next to a stopped engine.
    for (const tab of ["WEATHER", "MACRO", ""]) {
      const board = emptyBoard(health(), tab, "weather");
      expect(`${board.headline} ${board.body ?? ""}`.toLowerCase()).not.toContain(
        FOUND_NOTHING_PHRASE,
      );
    }
    expect(FOUND_NOTHING_PHRASE).toBe("found no qualifying opportunity");
  });

  it("names the wired engine and not the one no scanner calls", () => {
    // `WeatherMaker` is a real defect and stays in the ruling, but nothing calls it, so it cannot
    // be the headline cause of an empty board.
    const engine = stoppedEngineOf(health(), "WEATHER");
    expect(engine?.name).toBe("WeatherEngine");
    expect(engine?.wired_to_a_scanner).toBe(true);
  });

  it("treats case and spacing as nothing, because the writer upper-cases the column", () => {
    for (const variant of ["weather", " Weather ", "WEATHER"]) {
      expect(emptyBoard(health(), variant, "weather").kind).toBe("stopped");
    }
  });

  it("reports the unfiltered board as stopped without a second rule in the client", () => {
    const board = emptyBoard(health(), "", "all");
    expect(board.kind).toBe("stopped");
    expect(board.headline).toContain("1 of 2");
    expect(board.body).toBe(WEATHER_REASON);
  });
});

describe("an engine that ran and found nothing still reads as quiet", () => {
  it("keeps the finding it is entitled to", () => {
    const board = emptyBoard(health(), "SPORTS", "sports");
    expect(board.kind).toBe("quiet");
    expect(board.headline).toBe("No high-confidence edges detected in sports");
    expect(board.body).toBe(QUIET_REASON);
  });

  it("does not mention a stopped engine on a tab nothing stopped", () => {
    const board = emptyBoard(health(), "SPORTS", "sports");
    expect(`${board.headline} ${board.body ?? ""}`).not.toContain(STOPPED_WORD);
  });

  it("still says nothing detected on the unfiltered board when the ruling is clean", () => {
    const clean = health({
      edge_types: [quietSports()],
      edge_types_total: 1,
      edge_types_could_not_run: 0,
      edge_types_ran: 1,
      board_state: "ran",
      board_reason: null,
      sites: [],
      sites_total: 0,
      sites_wired: 0,
      sites_unwired: 0,
    });
    const board = emptyBoard(clean, "", "all");
    expect(board.kind).toBe("quiet");
    expect(board.headline).toBe("No high-confidence edges detected in all");
  });

  it("carries no reason on a running engine, so the two states cannot look alike", () => {
    expect(edgeTypeStateOf(health(), "SPORTS")?.reason).toBeNull();
  });
});

describe("a missing figure is a word or a null, never 0", () => {
  it("draws the stopped engine's opportunity count as a dash", () => {
    expect(opportunitiesFoundText(stoppedWeather())).toBe(NOT_MEASURED);
  });

  it("does not print a zero anywhere in its place", () => {
    expect(opportunitiesFoundText(stoppedWeather())).not.toMatch(/\d/);
    expect(NOT_MEASURED).not.toMatch(/\d/);
  });

  it("says what the dash is not", () => {
    const reason = opportunitiesFoundReason(stoppedWeather());
    expect(reason).toBeTruthy();
    expect(reason?.toLowerCase()).toContain("not a count of zero");
  });

  it("gives a dash, not a zero, when there is no entry at all", () => {
    expect(opportunitiesFoundText(null)).toBe(NOT_MEASURED);
    expect(opportunitiesFoundText(undefined)).toBe(NOT_MEASURED);
    expect(opportunitiesFoundReason(null)).toBeTruthy();
  });

  it("distinguishes not-measured from not-counted-here", () => {
    // Two different facts. Collapsing them would leave a reader unsure whether a running engine had
    // anything to report either.
    expect(opportunitiesFoundReason(stoppedWeather())).toContain("nothing ran");
    expect(opportunitiesFoundReason(quietSports())).toContain("Not counted here");
  });

  it("still prints a real number when one is ever measured, rather than a permanent dash", () => {
    // The dash is a fail-safe, not a hardcoded string. A field that could only ever be a dash would
    // be a field nobody reads.
    const measured = { ...quietSports(), opportunities_found: 4 };
    expect(opportunitiesFoundText(measured)).toBe("4");
    expect(opportunitiesFoundReason(measured)).toBeNull();
  });
});

describe("a ruling that could not be read claims nothing either way", () => {
  it("does not say an engine found nothing when the ruling failed", () => {
    const board = emptyBoard(null, "WEATHER", "weather", "500 from /api/engine-health");
    expect(board.kind).toBe("unchecked");
    expect(board.headline).not.toMatch(/no high-confidence edges/i);
    // The error is quoted AND its consequence stated, so the reader is not left holding a status
    // line and having to work out whether the empty board below it means anything.
    expect(board.body).toContain(HEALTH_UNREAD_REASON);
    expect(board.body).toContain("500 from /api/engine-health");
  });

  it("does not say an engine is broken when the ruling failed either", () => {
    // The other half. Guessing "stopped" on a failed read is the same fabrication with the sign
    // flipped, and it would page someone about an outage.
    const board = emptyBoard(null, "WEATHER", "weather", "boom");
    expect(board.body).not.toContain(STOPPED_WORD);
  });

  it("says so before the ruling has arrived, which is the same state", () => {
    const board = emptyBoard(null, "WEATHER", "weather");
    expect(board.kind).toBe("unchecked");
    expect(board.body).toBe(HEALTH_UNREAD_REASON);
  });

  it("treats a response with no entry for this tab as a gap rather than a quiet engine", () => {
    const board = emptyBoard(health(), "ENERGY", "energy");
    expect(board.kind).toBe("unchecked");
    expect(board.headline).not.toMatch(/no high-confidence edges/i);
  });

  it("never lets a failed read fall through to the quiet branch", () => {
    // The specific regression: a null `health` defaulting to "ran" would restore the original
    // defect for the length of one outage.
    for (const tab of ["WEATHER", "MACRO", "SPORTS", "CRYPTO", "ENERGY", ""]) {
      expect(emptyBoard(undefined, tab, tab || "all", "boom").kind).not.toBe("quiet");
      expect(emptyBoard(null, tab, tab || "all").kind).not.toBe("quiet");
    }
  });
});

describe("the counts are the server's", () => {
  it("each count agrees its own noun", () => {
    expect(edgeTypesText(health())).toBe("2 boards · 1 cannot run · 1 ran");
    const one = health({ edge_types_total: 1, edge_types_could_not_run: 1, edge_types_ran: 0 });
    expect(edgeTypesText(one)).toBe("1 board · 1 cannot run · 0 ran");
  });

  it("words a missing ruling as a failure, never as zero", () => {
    expect(edgeTypesText(null)).toBe("engine states not in the response — the ruling did not arrive");
    expect(edgeTypesText(null)).not.toMatch(/\b0\b/);
  });
});
